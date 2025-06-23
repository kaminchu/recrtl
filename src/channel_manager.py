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
        
        # 全国放送局データベース
        from japan_broadcasting_database import JapanBroadcastingDatabase
        self._broadcast_db = JapanBroadcastingDatabase()
        
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
    
    
    def get_all_prefectures(self) -> List[str]:
        """利用可能な都道府県コード一覧を取得"""
        return self._broadcast_db.get_prefectures()
    
    def get_prefecture_stations(self, prefecture_code: str) -> List[Tuple[int, Dict]]:
        """指定都道府県のすべての放送局を取得"""
        stations = self._broadcast_db.get_all_stations_by_prefecture(prefecture_code)
        result = []
        
        for channel, trans_code, trans_name, station in stations:
            # チャンネル情報を構築
            info = self._physical_channels[channel].copy()
            info['channel'] = channel
            info['transmitter'] = {'code': trans_code, 'name': trans_name}
            info['station'] = station.copy()
            
            # 都道府県情報を追加
            pref_info = self._broadcast_db.get_prefecture_info(prefecture_code)
            if pref_info:
                info['station']['prefecture'] = pref_info['name']
                info['station']['region'] = pref_info['region']
            
            result.append((channel, info))
        
        return result
    
    def get_transmitters_by_prefecture(self, prefecture_code: str) -> Optional[Dict]:
        """指定都道府県の送信所一覧を取得"""
        return self._broadcast_db.get_transmitters(prefecture_code)
    
    def search_by_channel(self, channel: int) -> List[Dict]:
        """物理チャンネルで全国の放送局を検索"""
        results = self._broadcast_db.search_stations_by_channel(channel)
        detailed_results = []
        
        for pref_code, trans_code, trans_name, station in results:
            pref_info = self._broadcast_db.get_prefecture_info(pref_code)
            
            result = {
                'channel': channel,
                'prefecture_code': pref_code,
                'prefecture_name': pref_info['name'] if pref_info else '不明',
                'region': pref_info['region'] if pref_info else '不明',
                'transmitter_code': trans_code,
                'transmitter_name': trans_name,
                'station': station
            }
            detailed_results.append(result)
        
        return detailed_results
    
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
            area: 特定地域の情報を取得する場合の地域キー（47都道府県対応）
            
        Returns:
            dict: チャンネル情報、無効なチャンネルの場合None
        """
        if channel not in self._physical_channels:
            return None
            
        info = self._physical_channels[channel].copy()
        info['channel'] = channel
        
        # 47都道府県データベースから放送局情報を検索
        if area and area in self._broadcast_db.get_prefectures():
            # 指定都道府県の情報を取得
            pref_stations = self.get_prefecture_stations(area)
            for ch, station_info in pref_stations:
                if ch == channel:
                    info.update(station_info)
                    break
        else:
            # 全国から検索（最初に見つかったもの）
            found_stations = self._broadcast_db.search_stations_by_channel(channel)
            if found_stations:
                pref_code, trans_code, trans_name, station = found_stations[0]
                pref_info = self._broadcast_db.get_prefecture_info(pref_code)
                
                info['transmitter'] = {'code': trans_code, 'name': trans_name}
                info['station'] = station.copy()
                if pref_info:
                    info['station']['prefecture'] = pref_info['name']
                    info['station']['region'] = pref_info['region']
        
        return info
    
    def get_station_info(self, channel: int, area: str = 'tokyo') -> Optional[Dict]:
        """
        指定地域の放送局情報を取得
        
        Args:
            channel: 物理チャンネル番号
            area: 都道府県コード（47都道府県対応）
            
        Returns:
            dict: 放送局情報、該当なしの場合None
        """
        if area in self._broadcast_db.get_prefectures():
            pref_stations = self.get_prefecture_stations(area)
            for ch, station_info in pref_stations:
                if ch == channel:
                    return station_info.get('station')
        return None
    
    def list_channels(self, area: Optional[str] = None) -> List[Tuple[int, Dict]]:
        """
        利用可能なチャンネル一覧を取得
        
        Args:
            area: 都道府県コード（47都道府県対応）
            
        Returns:
            List[Tuple[int, Dict]]: (チャンネル番号, 情報)のリスト
        """
        if area is None:
            # 全物理チャンネル
            channels = []
            for channel in sorted(self._physical_channels.keys()):
                info = self.get_channel_info(channel)
                channels.append((channel, info))
            return channels
        elif area in self._broadcast_db.get_prefectures():
            # 47都道府県対応
            return self.get_prefecture_stations(area)
        else:
            # 無効な地域コード - 空リストを返す
            return []
    
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
            'prefectures_supported': self._broadcast_db.get_prefectures()
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