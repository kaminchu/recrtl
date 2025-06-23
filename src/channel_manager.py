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
        """主要都市の放送局情報を構築"""
        # 東京（関東）の主要放送局
        tokyo_stations = {
            27: {'name': 'NHK総合・東京', 'call_sign': 'JOAK-DTV', 'area': '関東'},
            26: {'name': 'NHK Eテレ東京', 'call_sign': 'JOAB-DTV', 'area': '関東'},
            25: {'name': '日本テレビ', 'call_sign': 'JOAX-DTV', 'area': '関東'},
            22: {'name': 'TBSテレビ', 'call_sign': 'JORX-DTV', 'area': '関東'},
            21: {'name': 'フジテレビ', 'call_sign': 'JOCX-DTV', 'area': '関東'},
            24: {'name': 'テレビ朝日', 'call_sign': 'JOEX-DTV', 'area': '関東'},
            23: {'name': 'テレビ東京', 'call_sign': 'JOTX-DTV', 'area': '関東'},
            16: {'name': '東京MX', 'call_sign': 'JOMX-DTV', 'area': '東京'},
        }
        
        # 大阪（関西）の主要放送局
        osaka_stations = {
            24: {'name': 'NHK総合・大阪', 'call_sign': 'JOOK-DTV', 'area': '関西'},
            13: {'name': 'NHK Eテレ大阪', 'call_sign': 'JOOB-DTV', 'area': '関西'},
            25: {'name': '毎日放送', 'call_sign': 'JOOR-DTV', 'area': '関西'},
            22: {'name': '関西テレビ', 'call_sign': 'JODX-DTV', 'area': '関西'},
            26: {'name': '朝日放送テレビ', 'call_sign': 'JOAY-DTV', 'area': '関西'},
            15: {'name': 'テレビ大阪', 'call_sign': 'JOTV-DTV', 'area': '関西'},
        }
        
        # 名古屋（中京）の主要放送局
        nagoya_stations = {
            20: {'name': 'NHK総合・名古屋', 'call_sign': 'JOCK-DTV', 'area': '中京'},
            13: {'name': 'NHK Eテレ名古屋', 'call_sign': 'JOCB-DTV', 'area': '中京'},
            21: {'name': '中京テレビ', 'call_sign': 'JOCH-DTV', 'area': '中京'},
            25: {'name': 'CBCテレビ', 'call_sign': 'JOGX-DTV', 'area': '中京'},
            26: {'name': 'メ〜テレ', 'call_sign': 'JOCI-DTV', 'area': '中京'},
            27: {'name': 'テレビ愛知', 'call_sign': 'JOCI-DTV', 'area': '中京'},
        }
        
        self._station_info = {
            'tokyo': tokyo_stations,
            'osaka': osaka_stations,
            'nagoya': nagoya_stations
        }
        
        logger.debug("放送局情報構築完了")
    
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
    
    def get_channel_info(self, channel: int) -> Optional[Dict]:
        """
        チャンネルの詳細情報を取得
        
        Args:
            channel: 物理チャンネル番号（13-62）
            
        Returns:
            dict: チャンネル情報、無効なチャンネルの場合None
        """
        if channel not in self._physical_channels:
            return None
            
        info = self._physical_channels[channel].copy()
        info['channel'] = channel
        
        # 放送局情報があれば追加
        for area, stations in self._station_info.items():
            if channel in stations:
                info['station'] = stations[channel]
                info['station']['area_key'] = area
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
                info = self.get_channel_info(channel)
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