"""
MPEG-2 Transport Stream Parser

ISDB-T から復調されたエラー訂正済みデータから MPEG-2 Transport Stream を解析し、
PAT (Program Association Table) と PMT (Program Map Table) を解析して
ビデオ・オーディオストリームの PID を抽出する。
"""

import logging
from typing import List, Dict, Optional, Tuple, Union
import struct

logger = logging.getLogger(__name__)

class TSPacket:
    """
    MPEG-2 Transport Stream パケット
    
    各パケットは188バイトで構成される：
    - 同期バイト (0x47): 1バイト
    - ヘッダー: 3バイト
    - ペイロード: 184バイト
    """
    
    PACKET_SIZE = 188
    SYNC_BYTE = 0x47
    
    def __init__(self, data: bytes):
        """
        TSパケットを初期化
        
        Args:
            data: 188バイトのTSパケットデータ
        """
        if len(data) != self.PACKET_SIZE:
            raise ValueError(f"TSパケットサイズが不正: {len(data)} != {self.PACKET_SIZE}")
        
        if data[0] != self.SYNC_BYTE:
            raise ValueError(f"同期バイトが不正: 0x{data[0]:02X} != 0x{self.SYNC_BYTE:02X}")
        
        self.data = data
        self._parse_header()
    
    def _parse_header(self):
        """TSパケットヘッダーを解析"""
        # ヘッダー部分（4バイト）を解析
        header = struct.unpack('>I', self.data[:4])[0]
        
        # ビットフィールドの解析
        self.sync_byte = (header >> 24) & 0xFF
        self.transport_error_indicator = bool((header >> 23) & 0x1)
        self.payload_unit_start_indicator = bool((header >> 22) & 0x1)
        self.transport_priority = bool((header >> 21) & 0x1)
        self.pid = (header >> 8) & 0x1FFF
        self.transport_scrambling_control = (header >> 6) & 0x3
        self.adaptation_field_control = (header >> 4) & 0x3
        self.continuity_counter = header & 0xF
        
        # アダプテーションフィールドの解析
        self.adaptation_field_length = 0
        self.payload_start = 4
        
        if self.adaptation_field_control in [0x2, 0x3]:  # アダプテーションフィールドあり
            if len(self.data) > 4:
                self.adaptation_field_length = self.data[4]
                self.payload_start = 5 + self.adaptation_field_length
    
    def get_payload(self) -> bytes:
        """ペイロードデータを取得"""
        if self.adaptation_field_control in [0x1, 0x3]:  # ペイロードあり
            return self.data[self.payload_start:]
        return b''
    
    def has_payload(self) -> bool:
        """ペイロードを持つかチェック"""
        return self.adaptation_field_control in [0x1, 0x3]
    
    def __str__(self):
        return (f"TSPacket(PID=0x{self.pid:04X}, "
                f"PUSI={self.payload_unit_start_indicator}, "
                f"CC={self.continuity_counter})")

class PATParser:
    """
    Program Association Table (PAT) パーサー
    
    PAT は PID 0x0000 で送信され、番組とPMTのPIDの対応を示す
    """
    
    PAT_PID = 0x0000
    
    def __init__(self):
        """PATパーサーを初期化"""
        self.programs = {}  # program_number -> pmt_pid
        logger.debug("PATパーサー初期化")
    
    def parse(self, ts_packet: TSPacket) -> bool:
        """
        PATを解析
        
        Args:
            ts_packet: PID 0x0000 の TSパケット
            
        Returns:
            bool: 解析成功フラグ
        """
        if ts_packet.pid != self.PAT_PID:
            logger.error(f"PAT解析: 不正なPID 0x{ts_packet.pid:04X}")
            return False
        
        if not ts_packet.has_payload():
            logger.debug("PAT解析: ペイロードなし")
            return False
        
        payload = ts_packet.get_payload()
        if len(payload) < 1:
            logger.debug("PAT解析: ペイロード長不足")
            return False
        
        try:
            # PSI (Program Specific Information) の解析
            if ts_packet.payload_unit_start_indicator:
                # ポインターフィールド
                pointer_field = payload[0]
                section_start = 1 + pointer_field
                
                if section_start >= len(payload):
                    logger.debug("PAT解析: セクション開始位置が不正")
                    return False
                
                # PAT セクションの解析
                section = payload[section_start:]
                if len(section) < 8:
                    logger.debug("PAT解析: セクション長不足")
                    return False
                
                # セクションヘッダー
                table_id = section[0]
                if table_id != 0x00:  # PAT のテーブルID
                    logger.debug(f"PAT解析: 不正なテーブルID 0x{table_id:02X}")
                    return False
                
                section_length = ((section[1] & 0x0F) << 8) | section[2]
                if section_length > len(section) - 3:
                    logger.debug(f"PAT解析: セクション長が不正 {section_length}")
                    return False
                
                # PAT データ部分
                transport_stream_id = (section[3] << 8) | section[4]
                version_number = (section[5] >> 1) & 0x1F
                current_next_indicator = section[5] & 0x01
                section_number = section[6]
                last_section_number = section[7]
                
                logger.debug(f"PAT: TSID=0x{transport_stream_id:04X}, Ver={version_number}")
                
                # プログラム情報の解析
                programs_data = section[8:8 + section_length - 9]  # CRC32を除く
                
                for i in range(0, len(programs_data), 4):
                    if i + 3 < len(programs_data):
                        program_number = (programs_data[i] << 8) | programs_data[i + 1]
                        pmt_pid = ((programs_data[i + 2] & 0x1F) << 8) | programs_data[i + 3]
                        
                        if program_number == 0:
                            # Network PID (通常は0x0010)
                            logger.debug(f"PAT: Network PID=0x{pmt_pid:04X}")
                        else:
                            # プログラムのPMT PID
                            self.programs[program_number] = pmt_pid
                            logger.info(f"PAT: Program {program_number} -> PMT PID=0x{pmt_pid:04X}")
                
                return len(self.programs) > 0
                
        except Exception as e:
            logger.error(f"PAT解析エラー: {e}")
            return False
        
        return False
    
    def get_programs(self) -> Dict[int, int]:
        """発見されたプログラムとPMT PIDの辞書を取得"""
        return self.programs.copy()

class PMTParser:
    """
    Program Map Table (PMT) パーサー
    
    PMT は各プログラムのストリーム構成情報を含む
    """
    
    def __init__(self, pmt_pid: int):
        """
        PMTパーサーを初期化
        
        Args:
            pmt_pid: PMTのPID
        """
        self.pmt_pid = pmt_pid
        self.program_number = 0
        self.pcr_pid = 0
        self.streams = {}  # stream_type -> [pid_list]
        self.stream_info = {}  # pid -> {stream_type, descriptors}
        
        logger.debug(f"PMTパーサー初期化: PID=0x{pmt_pid:04X}")
    
    def parse(self, ts_packet: TSPacket) -> bool:
        """
        PMTを解析
        
        Args:
            ts_packet: PMT PID の TSパケット
            
        Returns:
            bool: 解析成功フラグ
        """
        if ts_packet.pid != self.pmt_pid:
            logger.error(f"PMT解析: 不正なPID 0x{ts_packet.pid:04X}")
            return False
        
        if not ts_packet.has_payload():
            logger.debug("PMT解析: ペイロードなし")
            return False
        
        payload = ts_packet.get_payload()
        if len(payload) < 1:
            logger.debug("PMT解析: ペイロード長不足")
            return False
        
        try:
            if ts_packet.payload_unit_start_indicator:
                # ポインターフィールド
                pointer_field = payload[0]
                section_start = 1 + pointer_field
                
                if section_start >= len(payload):
                    logger.debug("PMT解析: セクション開始位置が不正")
                    return False
                
                # PMT セクションの解析
                section = payload[section_start:]
                if len(section) < 12:
                    logger.debug("PMT解析: セクション長不足")
                    return False
                
                # セクションヘッダー
                table_id = section[0]
                if table_id != 0x02:  # PMT のテーブルID
                    logger.debug(f"PMT解析: 不正なテーブルID 0x{table_id:02X}")
                    return False
                
                section_length = ((section[1] & 0x0F) << 8) | section[2]
                if section_length > len(section) - 3:
                    logger.debug(f"PMT解析: セクション長が不正 {section_length}")
                    return False
                
                # PMT データ部分
                self.program_number = (section[3] << 8) | section[4]
                version_number = (section[5] >> 1) & 0x1F
                current_next_indicator = section[5] & 0x01
                section_number = section[6]
                last_section_number = section[7]
                self.pcr_pid = ((section[8] & 0x1F) << 8) | section[9]
                program_info_length = ((section[10] & 0x0F) << 8) | section[11]
                
                logger.debug(f"PMT: Program={self.program_number}, PCR_PID=0x{self.pcr_pid:04X}")
                
                # プログラム記述子をスキップ
                stream_info_start = 12 + program_info_length
                stream_info_data = section[stream_info_start:stream_info_start + section_length - 13 - program_info_length]
                
                # ストリーム情報の解析
                i = 0
                while i < len(stream_info_data):
                    if i + 4 >= len(stream_info_data):
                        break
                    
                    stream_type = stream_info_data[i]
                    elementary_pid = ((stream_info_data[i + 1] & 0x1F) << 8) | stream_info_data[i + 2]
                    es_info_length = ((stream_info_data[i + 3] & 0x0F) << 8) | stream_info_data[i + 4]
                    
                    # ストリーム情報を記録
                    if stream_type not in self.streams:
                        self.streams[stream_type] = []
                    self.streams[stream_type].append(elementary_pid)
                    
                    self.stream_info[elementary_pid] = {
                        'stream_type': stream_type,
                        'descriptors': stream_info_data[i + 5:i + 5 + es_info_length]
                    }
                    
                    # ストリームタイプの判定
                    stream_name = self._get_stream_type_name(stream_type)
                    logger.info(f"PMT: {stream_name} PID=0x{elementary_pid:04X} (Type=0x{stream_type:02X})")
                    
                    i += 5 + es_info_length
                
                return len(self.stream_info) > 0
                
        except Exception as e:
            logger.error(f"PMT解析エラー: {e}")
            return False
        
        return False
    
    def _get_stream_type_name(self, stream_type: int) -> str:
        """ストリームタイプから名前を取得"""
        stream_types = {
            0x01: "MPEG-1 Video",
            0x02: "MPEG-2 Video", 
            0x03: "MPEG-1 Audio",
            0x04: "MPEG-2 Audio",
            0x06: "Private PES",
            0x0F: "MPEG-2 AAC Audio",
            0x1B: "H.264/AVC Video",
            0x24: "H.265/HEVC Video",
            0x81: "Private Stream"
        }
        return stream_types.get(stream_type, f"Unknown(0x{stream_type:02X})")
    
    def get_video_pids(self) -> List[int]:
        """ビデオストリームのPIDリストを取得"""
        video_types = [0x01, 0x02, 0x1B, 0x24]  # MPEG-1/2, H.264, H.265
        pids = []
        for stream_type in video_types:
            if stream_type in self.streams:
                pids.extend(self.streams[stream_type])
        return pids
    
    def get_audio_pids(self) -> List[int]:
        """オーディオストリームのPIDリストを取得"""
        audio_types = [0x03, 0x04, 0x0F]  # MPEG-1/2 Audio, AAC
        pids = []
        for stream_type in audio_types:
            if stream_type in self.streams:
                pids.extend(self.streams[stream_type])
        return pids
    
    def get_all_stream_pids(self) -> Dict[int, dict]:
        """全ストリーム情報を取得"""
        return self.stream_info.copy()

class TSParser:
    """
    MPEG-2 Transport Stream パーサー
    
    エラー訂正済みデータから TS パケットを抽出し、
    PAT/PMT を解析してストリーム構成を把握する
    """
    
    def __init__(self):
        """TSパーサーを初期化"""
        self.pat_parser = PATParser()
        self.pmt_parsers = {}  # pmt_pid -> PMTParser
        self.sync_position = 0
        self.packet_buffer = b''
        self.parsed_programs = {}  # program_number -> PMTParser
        
        logger.info("Transport Stream パーサー初期化")
    
    def find_sync_byte(self, data: bytes, start_pos: int = 0) -> int:
        """
        TSパケットの同期バイト (0x47) を検索
        
        Args:
            data: 検索対象データ
            start_pos: 検索開始位置
            
        Returns:
            int: 同期バイト位置 (-1 = 見つからない)
        """
        for i in range(start_pos, len(data)):
            if data[i] == TSPacket.SYNC_BYTE:
                # 次の同期バイトもチェック（188バイト後）
                next_sync_pos = i + TSPacket.PACKET_SIZE
                if next_sync_pos < len(data) and data[next_sync_pos] == TSPacket.SYNC_BYTE:
                    return i
                elif next_sync_pos >= len(data):
                    # データ末尾の場合は暫定的に有効とする
                    return i
        return -1
    
    def parse_data(self, data: bytes) -> List[TSPacket]:
        """
        データからTSパケットを抽出・解析
        
        Args:
            data: 入力データ（エラー訂正済み）
            
        Returns:
            List[TSPacket]: 抽出されたTSパケットリスト
        """
        self.packet_buffer += data
        packets = []
        
        while len(self.packet_buffer) >= TSPacket.PACKET_SIZE:
            # 同期バイトを探す
            sync_pos = self.find_sync_byte(self.packet_buffer, self.sync_position)
            
            if sync_pos == -1:
                # 同期バイトが見つからない場合、バッファをクリア
                logger.warning("TSパーサー: 同期バイトが見つかりません")
                self.packet_buffer = self.packet_buffer[-TSPacket.PACKET_SIZE:]
                self.sync_position = 0
                break
            
            # 同期位置を調整
            if sync_pos > 0:
                self.packet_buffer = self.packet_buffer[sync_pos:]
                logger.debug(f"TSパーサー: 同期位置調整 {sync_pos}バイト")
            
            # パケットサイズ分のデータがあるかチェック
            if len(self.packet_buffer) < TSPacket.PACKET_SIZE:
                break
            
            try:
                # TSパケットを作成
                packet_data = self.packet_buffer[:TSPacket.PACKET_SIZE]
                ts_packet = TSPacket(packet_data)
                packets.append(ts_packet)
                
                # パケットを解析
                self._analyze_packet(ts_packet)
                
                # バッファから処理済みデータを削除
                self.packet_buffer = self.packet_buffer[TSPacket.PACKET_SIZE:]
                
            except ValueError as e:
                logger.debug(f"TSパケット作成失敗: {e}")
                # 1バイト進めて再試行
                self.packet_buffer = self.packet_buffer[1:]
        
        return packets
    
    def _analyze_packet(self, ts_packet: TSPacket):
        """TSパケットを解析してPAT/PMTを処理"""
        try:
            # PAT解析
            if ts_packet.pid == PATParser.PAT_PID:
                if self.pat_parser.parse(ts_packet):
                    logger.debug("PAT解析成功")
                    
                    # 新しいプログラムが見つかった場合、PMTパーサーを作成
                    for program_num, pmt_pid in self.pat_parser.get_programs().items():
                        if pmt_pid not in self.pmt_parsers:
                            self.pmt_parsers[pmt_pid] = PMTParser(pmt_pid)
                            logger.info(f"PMTパーサー作成: PID=0x{pmt_pid:04X} (Program {program_num})")
            
            # PMT解析
            elif ts_packet.pid in self.pmt_parsers:
                pmt_parser = self.pmt_parsers[ts_packet.pid]
                if pmt_parser.parse(ts_packet):
                    self.parsed_programs[pmt_parser.program_number] = pmt_parser
                    logger.info(f"PMT解析成功: Program {pmt_parser.program_number}")
                    
        except Exception as e:
            logger.error(f"TSパケット解析エラー: {e}")
    
    def get_stream_info(self) -> Dict[int, Dict]:
        """
        解析されたストリーム情報を取得
        
        Returns:
            Dict: {program_number: {video_pids: [], audio_pids: [], all_pids: {}}}
        """
        stream_info = {}
        
        for program_num, pmt_parser in self.parsed_programs.items():
            stream_info[program_num] = {
                'video_pids': pmt_parser.get_video_pids(),
                'audio_pids': pmt_parser.get_audio_pids(),
                'all_pids': pmt_parser.get_all_stream_pids(),
                'pcr_pid': pmt_parser.pcr_pid
            }
        
        return stream_info
    
    def extract_stream_data(self, ts_packets: List[TSPacket], target_pids: List[int]) -> bytes:
        """
        指定されたPIDのストリームデータを抽出
        
        Args:
            ts_packets: TSパケットリスト
            target_pids: 抽出対象PIDリスト
            
        Returns:
            bytes: 抽出されたストリームデータ
        """
        stream_data = b''
        
        for packet in ts_packets:
            if packet.pid in target_pids and packet.has_payload():
                payload = packet.get_payload()
                stream_data += payload
        
        return stream_data
    
    def generate_output_ts(self, ts_packets: List[TSPacket], target_pids: Optional[List[int]] = None) -> bytes:
        """
        指定されたPIDのTSパケットを出力用に生成
        
        Args:
            ts_packets: 入力TSパケットリスト
            target_pids: 出力対象PIDリスト (None = 全て)
            
        Returns:
            bytes: 出力用TSストリーム
        """
        output_data = b''
        
        for packet in ts_packets:
            if target_pids is None or packet.pid in target_pids:
                output_data += packet.data
        
        return output_data
    
    def get_parser_stats(self) -> Dict:
        """パーサー統計情報を取得"""
        return {
            'programs_found': len(self.parsed_programs),
            'pmt_parsers': len(self.pmt_parsers),
            'buffer_size': len(self.packet_buffer),
            'stream_info': self.get_stream_info()
        }