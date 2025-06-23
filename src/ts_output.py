"""
MPEG-2 Transport Stream 出力制御

Transport Stream データを標準出力に効率的に出力し、
ffmpeg や VLC などのメディアプレイヤーとの連携を提供する。
"""

import sys
import logging
import threading
import time
import queue
from typing import List, Optional, Dict
import struct

logger = logging.getLogger(__name__)

class TSOutputController:
    """
    Transport Stream 出力制御クラス
    
    TSパケットをバッファリングして効率的に標準出力に送信する。
    リアルタイム性能とバッファ管理を最適化。
    """
    
    def __init__(self, buffer_size: int = 1024, output_rate_bps: Optional[int] = None):
        """
        TS出力制御を初期化
        
        Args:
            buffer_size: バッファサイズ（TSパケット数）
            output_rate_bps: 出力レート制限（bps、None=無制限）
        """
        self.buffer_size = buffer_size
        self.output_rate_bps = output_rate_bps
        self.packet_buffer = queue.Queue(maxsize=buffer_size)
        self.output_thread = None
        self.stop_event = threading.Event()
        self.stats = {
            'packets_output': 0,
            'bytes_output': 0,
            'buffer_overflows': 0,
            'output_errors': 0,
            'start_time': None
        }
        
        logger.info(f"TS出力制御初期化: バッファ={buffer_size}パケット, レート制限={'無制限' if output_rate_bps is None else f'{output_rate_bps}bps'}")
    
    def start_output(self):
        """出力スレッドを開始"""
        if self.output_thread and self.output_thread.is_alive():
            logger.warning("TS出力スレッドは既に動作中です")
            return
        
        self.stop_event.clear()
        self.stats['start_time'] = time.time()
        self.output_thread = threading.Thread(target=self._output_worker, daemon=True)
        self.output_thread.start()
        logger.info("TS出力スレッド開始")
    
    def stop_output(self):
        """出力スレッドを停止"""
        if self.output_thread and self.output_thread.is_alive():
            self.stop_event.set()
            self.output_thread.join(timeout=2.0)
            logger.info("TS出力スレッド停止")
    
    def _output_worker(self):
        """出力ワーカースレッド"""
        last_output_time = time.time()
        bytes_in_second = 0
        
        while not self.stop_event.is_set():
            try:
                # タイムアウト付きでパケットを取得
                packet_data = self.packet_buffer.get(timeout=0.1)
                
                # レート制限チェック
                if self.output_rate_bps:
                    current_time = time.time()
                    if current_time - last_output_time >= 1.0:
                        # 1秒経過したらリセット
                        last_output_time = current_time
                        bytes_in_second = 0
                    
                    packet_size = len(packet_data)
                    if bytes_in_second + packet_size > self.output_rate_bps // 8:
                        # レート制限に達した場合は待機
                        sleep_time = 1.0 - (current_time - last_output_time)
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                        last_output_time = time.time()
                        bytes_in_second = 0
                
                # 標準出力に書き込み
                try:
                    sys.stdout.buffer.write(packet_data)
                    sys.stdout.buffer.flush()
                    
                    # 統計更新
                    self.stats['packets_output'] += 1
                    self.stats['bytes_output'] += len(packet_data)
                    bytes_in_second += len(packet_data)
                    
                except (BrokenPipeError, IOError) as e:
                    logger.error(f"TS出力エラー: {e}")
                    self.stats['output_errors'] += 1
                    break
                
                self.packet_buffer.task_done()
                
            except queue.Empty:
                # タイムアウト（正常）
                continue
            except Exception as e:
                logger.error(f"TS出力ワーカーエラー: {e}")
                self.stats['output_errors'] += 1
    
    def queue_packet(self, packet_data: bytes) -> bool:
        """
        TSパケットをキューに追加
        
        Args:
            packet_data: TSパケットデータ（188バイト）
            
        Returns:
            bool: キューイング成功フラグ
        """
        try:
            self.packet_buffer.put_nowait(packet_data)
            return True
        except queue.Full:
            self.stats['buffer_overflows'] += 1
            logger.warning("TSパケットバッファオーバーフロー")
            return False
    
    def queue_packets(self, packets_data: List[bytes]) -> int:
        """
        複数のTSパケットをキューに追加
        
        Args:
            packets_data: TSパケットデータリスト
            
        Returns:
            int: 成功したパケット数
        """
        success_count = 0
        for packet_data in packets_data:
            if self.queue_packet(packet_data):
                success_count += 1
        return success_count
    
    def get_output_stats(self) -> Dict:
        """出力統計情報を取得"""
        stats = self.stats.copy()
        if stats['start_time']:
            elapsed_time = time.time() - stats['start_time']
            stats['elapsed_time'] = elapsed_time
            stats['average_bitrate'] = (stats['bytes_output'] * 8) / elapsed_time if elapsed_time > 0 else 0
            stats['packet_rate'] = stats['packets_output'] / elapsed_time if elapsed_time > 0 else 0
        
        stats['buffer_usage'] = self.packet_buffer.qsize()
        stats['buffer_utilization'] = (self.packet_buffer.qsize() / self.buffer_size) * 100
        
        return stats

class TSStreamGenerator:
    """
    Transport Stream ストリーム生成クラス
    
    解析されたTSパケットから有効なTSストリームを生成し、
    メディアプレイヤー用に最適化する。
    """
    
    def __init__(self):
        """TSストリーム生成器を初期化"""
        self.continuity_counters = {}  # PID -> 連続性カウンタ
        self.null_packet_template = self._create_null_packet()
        logger.debug("TSストリーム生成器初期化")
    
    def _create_null_packet(self) -> bytes:
        """NULL パケット（PID=0x1FFF）を作成"""
        # 同期バイト + ヘッダー (PID=0x1FFF, 連続性カウンタ=0) + ペイロード(0xFF)
        header = struct.pack('>I', 0x471FFF10)  # 同期バイト + PID=0x1FFF + フラグ
        payload = b'\xFF' * 184  # NULL ペイロード
        return header + payload
    
    def update_continuity_counter(self, pid: int, packet_data: bytes) -> bytes:
        """
        連続性カウンタを更新
        
        Args:
            pid: パケットPID
            packet_data: 元のTSパケットデータ
            
        Returns:
            bytes: 連続性カウンタ更新済みパケット
        """
        if pid not in self.continuity_counters:
            self.continuity_counters[pid] = 0
        
        # 現在のカウンタを取得・更新
        current_cc = self.continuity_counters[pid]
        self.continuity_counters[pid] = (current_cc + 1) % 16
        
        # パケットデータを更新
        updated_packet = bytearray(packet_data)
        updated_packet[3] = (updated_packet[3] & 0xF0) | current_cc
        
        return bytes(updated_packet)
    
    def generate_output_stream(self, ts_packets: List[bytes], target_pids: Optional[List[int]] = None, 
                             padding: bool = True) -> List[bytes]:
        """
        出力用TSストリームを生成
        
        Args:
            ts_packets: 入力TSパケットリスト
            target_pids: 出力対象PIDリスト（None=全て）
            padding: NULLパケットでパディングするか
            
        Returns:
            List[bytes]: 出力用TSパケットリスト
        """
        output_packets = []
        
        for packet_data in ts_packets:
            if len(packet_data) != 188:
                logger.warning(f"不正なTSパケットサイズ: {len(packet_data)}バイト")
                continue
            
            # PIDを抽出
            pid = ((packet_data[1] & 0x1F) << 8) | packet_data[2]
            
            # PIDフィルタリング
            if target_pids is not None and pid not in target_pids:
                continue
            
            # 連続性カウンタ更新
            updated_packet = self.update_continuity_counter(pid, packet_data)
            output_packets.append(updated_packet)
        
        # パディング追加
        if padding and len(output_packets) < len(ts_packets):
            null_count = len(ts_packets) - len(output_packets)
            for _ in range(null_count):
                output_packets.append(self.null_packet_template)
        
        logger.debug(f"TSストリーム生成: {len(ts_packets)}パケット → {len(output_packets)}パケット")
        return output_packets
    
    def create_program_stream(self, stream_info: Dict, all_packets: List[bytes]) -> List[bytes]:
        """
        プログラム用ストリームを作成
        
        Args:
            stream_info: ストリーム情報（PAT/PMT解析結果）
            all_packets: 全TSパケット
            
        Returns:
            List[bytes]: プログラム用TSパケット
        """
        essential_pids = set([0x0000])  # PAT
        
        for info in stream_info.values():
            # PMT PID、PCR PID、ビデオ・オーディオPIDを追加
            if 'pmt_pid' in info:
                essential_pids.add(info['pmt_pid'])
            essential_pids.add(info.get('pcr_pid', 0))
            essential_pids.update(info.get('video_pids', []))
            essential_pids.update(info.get('audio_pids', []))
        
        # 必要なPIDのパケットのみを抽出
        program_packets = []
        for packet_data in all_packets:
            if len(packet_data) >= 3:
                pid = ((packet_data[1] & 0x1F) << 8) | packet_data[2]
                if pid in essential_pids:
                    program_packets.append(packet_data)
        
        logger.info(f"プログラムストリーム作成: {len(essential_pids)}PID, {len(program_packets)}パケット")
        return self.generate_output_stream(program_packets)
    
    def get_stream_stats(self) -> Dict:
        """ストリーム生成統計を取得"""
        return {
            'tracked_pids': len(self.continuity_counters),
            'continuity_counters': self.continuity_counters.copy()
        }

class TSOutputManager:
    """
    Transport Stream 出力管理クラス
    
    TSParser、TSStreamGenerator、TSOutputController を統合し、
    完全なTS出力パイプラインを提供する。
    """
    
    def __init__(self, buffer_size: int = 1024, output_rate_bps: Optional[int] = None):
        """
        TS出力管理を初期化
        
        Args:
            buffer_size: 出力バッファサイズ
            output_rate_bps: 出力レート制限
        """
        self.stream_generator = TSStreamGenerator()
        self.output_controller = TSOutputController(buffer_size, output_rate_bps)
        self.is_running = False
        
        logger.info("TS出力管理初期化完了")
    
    def start_output(self):
        """TS出力を開始"""
        self.output_controller.start_output()
        self.is_running = True
        logger.info("TS出力開始")
    
    def stop_output(self):
        """TS出力を停止"""
        self.output_controller.stop_output()
        self.is_running = False
        logger.info("TS出力停止")
    
    def process_and_output(self, ts_data: bytes, stream_info: Optional[Dict] = None, 
                          target_pids: Optional[List[int]] = None) -> bool:
        """
        TSデータを処理して出力
        
        Args:
            ts_data: 生のTSデータ
            stream_info: ストリーム情報（PAT/PMT解析結果）
            target_pids: 出力対象PID（None=自動選択）
            
        Returns:
            bool: 処理成功フラグ
        """
        if not self.is_running:
            logger.warning("TS出力が開始されていません")
            return False
        
        try:
            # TSパケットに分割
            packets = []
            for i in range(0, len(ts_data), 188):
                if i + 188 <= len(ts_data):
                    packet = ts_data[i:i+188]
                    if len(packet) == 188 and packet[0] == 0x47:
                        packets.append(packet)
            
            if not packets:
                logger.debug("有効なTSパケットが見つかりません")
                return False
            
            # ストリーム情報がある場合はプログラムストリームを作成
            if stream_info:
                output_packets_data = self.stream_generator.create_program_stream(stream_info, packets)
            else:
                output_packets_data = self.stream_generator.generate_output_stream(packets, target_pids)
            
            # 出力キューに追加
            success_count = self.output_controller.queue_packets(output_packets_data)
            
            logger.debug(f"TS処理・出力: {len(packets)}パケット処理, {success_count}パケット出力")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"TS処理・出力エラー: {e}")
            return False
    
    def output_dummy_stream(self, duration_seconds: float = 1.0, bitrate_bps: int = 1000000):
        """
        ダミーTSストリームを出力（テスト用）
        
        Args:
            duration_seconds: 出力時間（秒）
            bitrate_bps: 出力ビットレート
        """
        if not self.is_running:
            self.start_output()
        
        packets_per_second = bitrate_bps // (188 * 8)  # 1秒あたりのパケット数
        total_packets = int(duration_seconds * packets_per_second)
        
        logger.info(f"ダミーTSストリーム出力: {duration_seconds}秒, {bitrate_bps}bps, {total_packets}パケット")
        
        for i in range(total_packets):
            # ダミーパケット生成
            dummy_packet = self.stream_generator.null_packet_template
            self.output_controller.queue_packet(dummy_packet)
            
            # レート制御
            if i % packets_per_second == 0:
                time.sleep(1.0)
    
    def get_manager_stats(self) -> Dict:
        """出力管理統計を取得"""
        return {
            'is_running': self.is_running,
            'output_stats': self.output_controller.get_output_stats(),
            'stream_stats': self.stream_generator.get_stream_stats()
        }