"""
チャンネル・周波数管理

日本の地上デジタル放送チャンネルと周波数の対応、放送局情報を管理する。
"""

import logging
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger(__name__)

class ChannelManager:
    """日本の地上デジタル放送チャンネル管理クラス"""
    
    def __init__(self):
        """チャンネルマネージャーを初期化"""
        # UHF帯域の物理チャンネル（13-62ch）
        self._physical_channels = {}
        self._build_channel_map()
        
        # 主要都市の放送局情報（東京・大阪・名古屋など）
        self._station_info = {}
        self._build_station_info()
        
        logger.debug("チャンネルマネージャー初期化完了")
    
    def _build_channel_map(self):
        """物理チャンネルと周波数のマッピングを構築"""
        # UHF帯域（13-62ch）の周波数計算
        # 周波数 = (ch - 13) × 6 + 473.142857 MHz
        for ch in range(13, 63):
            freq_mhz = (ch - 13) * 6 + 473.142857
            self._physical_channels[ch] = {
                'frequency_hz': int(freq_mhz * 1e6),
                'frequency_mhz': freq_mhz,
                'band': 'UHF'
            }
        
        logger.debug(f"物理チャンネルマップ構築: {len(self._physical_channels)}チャンネル")
    
    def _build_station_info(self):
        """全国の放送局情報を構築"""
        
        # 北海道・東北ブロック
        hokkaido_stations = {
            15: {'name': 'NHK総合・札幌', 'call_sign': 'JOIK-DTV', 'area': '北海道', 'region': '北海道・東北'},
            13: {'name': 'NHK Eテレ札幌', 'call_sign': 'JOIB-DTV', 'area': '北海道', 'region': '北海道・東北'},
            17: {'name': '北海道放送', 'call_sign': 'JOIR-DTV', 'area': '北海道', 'region': '北海道・東北'},
            19: {'name': '札幌テレビ', 'call_sign': 'JOSI-DTV', 'area': '北海道', 'region': '北海道・東北'},
            21: {'name': '北海道テレビ', 'call_sign': 'JOHH-DTV', 'area': '北海道', 'region': '北海道・東北'},
            27: {'name': '北海道文化放送', 'call_sign': 'JOEM-DTV', 'area': '北海道', 'region': '北海道・東北'},
            25: {'name': 'テレビ北海道', 'call_sign': 'JOTI-DTV', 'area': '北海道', 'region': '北海道・東北'},
        }
        
        aomori_stations = {
            15: {'name': 'NHK総合・青森', 'call_sign': 'JOAI-DTV', 'area': '青森県', 'region': '北海道・東北'},
            13: {'name': 'NHK Eテレ青森', 'call_sign': 'JOAB-DTV', 'area': '青森県', 'region': '北海道・東北'},
            31: {'name': '青森放送', 'call_sign': 'JORY-DTV', 'area': '青森県', 'region': '北海道・東北'},
            33: {'name': '青森テレビ', 'call_sign': 'JORY-DTV', 'area': '青森県', 'region': '北海道・東北'},
            35: {'name': '青森朝日放送', 'call_sign': 'JORY-DTV', 'area': '青森県', 'region': '北海道・東北'},
        }
        
        # 関東ブロック
        tokyo_stations = {
            27: {'name': 'NHK総合・東京', 'call_sign': 'JOAK-DTV', 'area': '東京都', 'region': '関東'},
            26: {'name': 'NHK Eテレ東京', 'call_sign': 'JOAB-DTV', 'area': '東京都', 'region': '関東'},
            25: {'name': '日本テレビ', 'call_sign': 'JOAX-DTV', 'area': '関東', 'region': '関東'},
            22: {'name': 'TBSテレビ', 'call_sign': 'JORX-DTV', 'area': '関東', 'region': '関東'},
            21: {'name': 'フジテレビ', 'call_sign': 'JOCX-DTV', 'area': '関東', 'region': '関東'},
            24: {'name': 'テレビ朝日', 'call_sign': 'JOEX-DTV', 'area': '関東', 'region': '関東'},
            23: {'name': 'テレビ東京', 'call_sign': 'JOTX-DTV', 'area': '関東', 'region': '関東'},
            16: {'name': '東京MX', 'call_sign': 'JOMX-DTV', 'area': '東京都', 'region': '関東'},
            18: {'name': '放送大学', 'call_sign': 'JOUD-DTV', 'area': '関東', 'region': '関東'},
        }
        
        # 中部ブロック
        nagoya_stations = {
            20: {'name': 'NHK総合・名古屋', 'call_sign': 'JOCK-DTV', 'area': '愛知県', 'region': '中部'},
            13: {'name': 'NHK Eテレ名古屋', 'call_sign': 'JOCB-DTV', 'area': '愛知県', 'region': '中部'},
            21: {'name': '中京テレビ', 'call_sign': 'JOCH-DTV', 'area': '中京', 'region': '中部'},
            25: {'name': 'CBCテレビ', 'call_sign': 'JOGX-DTV', 'area': '中京', 'region': '中部'},
            26: {'name': 'メ〜テレ', 'call_sign': 'JOCI-DTV', 'area': '中京', 'region': '中部'},
            27: {'name': 'テレビ愛知', 'call_sign': 'JOCI-DTV', 'area': '愛知県', 'region': '中部'},
        }
        
        # 近畿ブロック
        osaka_stations = {
            24: {'name': 'NHK総合・大阪', 'call_sign': 'JOOK-DTV', 'area': '大阪府', 'region': '近畿'},
            13: {'name': 'NHK Eテレ大阪', 'call_sign': 'JOOB-DTV', 'area': '大阪府', 'region': '近畿'},
            25: {'name': '毎日放送', 'call_sign': 'JOOR-DTV', 'area': '近畿', 'region': '近畿'},
            22: {'name': '関西テレビ', 'call_sign': 'JODX-DTV', 'area': '近畿', 'region': '近畿'},
            26: {'name': '朝日放送テレビ', 'call_sign': 'JOAY-DTV', 'area': '近畿', 'region': '近畿'},
            15: {'name': 'テレビ大阪', 'call_sign': 'JOTV-DTV', 'area': '大阪府', 'region': '近畿'},
            30: {'name': 'サンテレビ', 'call_sign': 'JOTV-DTV', 'area': '兵庫県', 'region': '近畿'},
            14: {'name': 'KBS京都', 'call_sign': 'JOTV-DTV', 'area': '京都府', 'region': '近畿'},
            18: {'name': 'テレビ和歌山', 'call_sign': 'JOTV-DTV', 'area': '和歌山県', 'region': '近畿'},
        }
        
        # 中国・四国ブロック
        hiroshima_stations = {
            19: {'name': 'NHK総合・広島', 'call_sign': 'JOFK-DTV', 'area': '広島県', 'region': '中国・四国'},
            13: {'name': 'NHK Eテレ広島', 'call_sign': 'JOFB-DTV', 'area': '広島県', 'region': '中国・四国'},
            25: {'name': '中国放送', 'call_sign': 'JOER-DTV', 'area': '広島県', 'region': '中国・四国'},
            31: {'name': '広島テレビ', 'call_sign': 'JOGH-DTV', 'area': '広島県', 'region': '中国・四国'},
            35: {'name': '広島ホームテレビ', 'call_sign': 'JOGM-DTV', 'area': '広島県', 'region': '中国・四国'},
            33: {'name': 'テレビ新広島', 'call_sign': 'JOGI-DTV', 'area': '広島県', 'region': '中国・四国'},
        }
        
        # 九州・沖縄ブロック
        fukuoka_stations = {
            18: {'name': 'NHK総合・福岡', 'call_sign': 'JOLK-DTV', 'area': '福岡県', 'region': '九州・沖縄'},
            13: {'name': 'NHK Eテレ福岡', 'call_sign': 'JOLB-DTV', 'area': '福岡県', 'region': '九州・沖縄'},
            20: {'name': 'RKB毎日放送', 'call_sign': 'JOFR-DTV', 'area': '福岡県', 'region': '九州・沖縄'},
            24: {'name': 'FBS福岡放送', 'call_sign': 'JOFH-DTV', 'area': '福岡県', 'region': '九州・沖縄'},
            26: {'name': 'KBC九州朝日放送', 'call_sign': 'JOTY-DTV', 'area': '福岡県', 'region': '九州・沖縄'},
            28: {'name': 'テレビ西日本', 'call_sign': 'JOCI-DTV', 'area': '福岡県', 'region': '九州・沖縄'},
            35: {'name': 'TVQ九州放送', 'call_sign': 'JOTY-DTV', 'area': '福岡県', 'region': '九州・沖縄'},
        }
        
        okinawa_stations = {
            15: {'name': 'NHK総合・沖縄', 'call_sign': 'JORK-DTV', 'area': '沖縄県', 'region': '九州・沖縄'},
            13: {'name': 'NHK Eテレ沖縄', 'call_sign': 'JORB-DTV', 'area': '沖縄県', 'region': '九州・沖縄'},
            19: {'name': '琉球放送', 'call_sign': 'JORY-DTV', 'area': '沖縄県', 'region': '九州・沖縄'},
            21: {'name': '沖縄テレビ', 'call_sign': 'JOPY-DTV', 'area': '沖縄県', 'region': '九州・沖縄'},
            23: {'name': '琉球朝日放送', 'call_sign': 'JOPY-DTV', 'area': '沖縄県', 'region': '九州・沖縄'},
        }
        
        # 都道府県別マッピング（主要局のみ）
        self._station_info = {
            # 北海道・東北
            'hokkaido': hokkaido_stations,
            'aomori': aomori_stations,
            
            # 関東（既存の'tokyo'キーは維持）
            'tokyo': tokyo_stations,
            
            # 中部（既存の'nagoya'キーは維持） 
            'nagoya': nagoya_stations,
            
            # 近畿（既存の'osaka'キーは維持）
            'osaka': osaka_stations,
            
            # 中国・四国
            'hiroshima': hiroshima_stations,
            
            # 九州・沖縄
            'fukuoka': fukuoka_stations,
            'okinawa': okinawa_stations,
        }
        
        # 地域ブロック情報
        self._regions = {
            '北海道・東北': ['hokkaido', 'aomori'],
            '関東': ['tokyo'],
            '中部': ['nagoya'], 
            '近畿': ['osaka'],
            '中国・四国': ['hiroshima'],
            '九州・沖縄': ['fukuoka', 'okinawa'],
        }
        
        logger.debug(f"放送局情報構築完了: {len(self._station_info)}地域, {sum(len(stations) for stations in self._station_info.values())}局")
    
    def get_frequency_hz(self, channel: int) -> Optional[int]:
        """
        物理チャンネル番号から周波数（Hz）を取得
        
        Args:
            channel: 物理チャンネル番号（13-62）
            
        Returns:
            int: 周波数（Hz）、無効なチャンネルの場合None
        """
        if channel in self._physical_channels:
            return self._physical_channels[channel]['frequency_hz']
        return None
    
    def get_frequency_mhz(self, channel: int) -> Optional[float]:
        """
        物理チャンネル番号から周波数（MHz）を取得
        
        Args:
            channel: 物理チャンネル番号（13-62）
            
        Returns:
            float: 周波数（MHz）、無効なチャンネルの場合None
        """
        if channel in self._physical_channels:
            return self._physical_channels[channel]['frequency_mhz']
        return None
    
    def get_channel_info(self, channel: int, area: Optional[str] = None) -> Optional[Dict]:
        """
        チャンネルの詳細情報を取得
        
        Args:
            channel: 物理チャンネル番号（13-62）
            area: 特定地域の情報を取得する場合の地域キー
            
        Returns:
            dict: チャンネル情報、無効なチャンネルの場合None
        """
        if channel not in self._physical_channels:
            return None
            
        info = self._physical_channels[channel].copy()
        info['channel'] = channel
        
        # 放送局情報があれば追加
        if area and area in self._station_info and channel in self._station_info[area]:
            # 特定地域の情報を取得
            info['station'] = self._station_info[area][channel]
            info['station']['area_key'] = area
        else:
            # 全地域から検索（最初に見つかったもの）
            for area_key, stations in self._station_info.items():
                if channel in stations:
                    info['station'] = stations[channel]
                    info['station']['area_key'] = area_key
                    break
        
        return info
    
    def get_station_info(self, channel: int, area: str = 'tokyo') -> Optional[Dict]:
        """
        指定地域の放送局情報を取得
        
        Args:
            channel: 物理チャンネル番号
            area: 地域キー（'tokyo', 'osaka', 'nagoya'）
            
        Returns:
            dict: 放送局情報、該当なしの場合None
        """
        if area in self._station_info and channel in self._station_info[area]:
            return self._station_info[area][channel]
        return None
    
    def list_channels(self, area: Optional[str] = None) -> List[Tuple[int, Dict]]:
        """
        利用可能なチャンネル一覧を取得
        
        Args:
            area: 地域キー（指定時はその地域の放送局のみ）
            
        Returns:
            List[Tuple[int, Dict]]: (チャンネル番号, 情報)のリスト
        """
        channels = []
        
        if area and area in self._station_info:
            # 指定地域の放送局のみ
            for channel in sorted(self._station_info[area].keys()):
                info = self.get_channel_info(channel, area)
                if info:
                    channels.append((channel, info))
        else:
            # 全物理チャンネル
            for channel in sorted(self._physical_channels.keys()):
                info = self.get_channel_info(channel)
                channels.append((channel, info))
        
        return channels
    
    def find_channel_by_frequency(self, freq_hz: float, tolerance_hz: float = 1000) -> Optional[int]:
        """
        周波数から最も近い物理チャンネルを検索
        
        Args:
            freq_hz: 検索する周波数（Hz）
            tolerance_hz: 許容誤差（Hz）
            
        Returns:
            int: 物理チャンネル番号、見つからない場合None
        """
        best_channel = None
        min_diff = float('inf')
        
        for channel, info in self._physical_channels.items():
            diff = abs(info['frequency_hz'] - freq_hz)
            if diff < min_diff and diff <= tolerance_hz:
                min_diff = diff
                best_channel = channel
        
        return best_channel
    
    def validate_channel(self, channel: int) -> bool:
        """
        チャンネル番号の有効性をチェック
        
        Args:
            channel: チャンネル番号
            
        Returns:
            bool: 有効な場合True
        """
        return channel in self._physical_channels
    
    def validate_frequency(self, freq_hz: float) -> bool:
        """
        周波数がUHF帯域内かチェック
        
        Args:
            freq_hz: 周波数（Hz）
            
        Returns:
            bool: UHF帯域内の場合True
        """
        # UHF帯域: 470-770MHz
        return 470e6 <= freq_hz <= 770e6
    
    def get_uhf_band_info(self) -> Dict:
        """
        UHF帯域の情報を取得
        
        Returns:
            dict: UHF帯域情報
        """
        return {
            'band_name': 'UHF (Ultra High Frequency)',
            'frequency_range': '470-770 MHz',
            'channel_range': '13-62',
            'channel_bandwidth': '6 MHz',
            'total_channels': len(self._physical_channels),
            'areas_supported': list(self._station_info.keys())
        }
    
    @staticmethod
    def calculate_frequency(channel: int) -> Optional[float]:
        """
        物理チャンネル番号から周波数を計算（静的メソッド）
        
        Args:
            channel: 物理チャンネル番号（13-62）
            
        Returns:
            float: 周波数（MHz）、無効なチャンネルの場合None
        """
        if 13 <= channel <= 62:
            return (channel - 13) * 6 + 473.142857
        return None
    
    @staticmethod
    def calculate_channel(freq_mhz: float) -> Optional[int]:
        """
        周波数から物理チャンネル番号を計算（静的メソッド）
        
        Args:
            freq_mhz: 周波数（MHz）
            
        Returns:
            int: 物理チャンネル番号、範囲外の場合None
        """
        if 470 <= freq_mhz <= 770:
            channel = round((freq_mhz - 473.142857) / 6) + 13
            if 13 <= channel <= 62:
                return channel
        return None