"""
RTL-SDRインターフェース

RTL2832ベースのUSBチューナーを制御するためのインターフェースクラス。
pyrtlsdrライブラリを使用してデバイスの初期化、設定、データ取得を行う。
"""

import logging
from typing import Optional, List, Tuple

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from rtlsdr import RtlSdr
    RTLSDR_AVAILABLE = True
except ImportError:
    RTLSDR_AVAILABLE = False
    # 開発環境でライブラリがない場合のダミークラス
    class RtlSdr:
        def __init__(self, device_index=0):
            pass
        def close(self):
            pass

logger = logging.getLogger(__name__)

class RTLInterface:
    """RTL-SDRデバイス制御クラス"""
    
    def __init__(self, device_id: int = 0):
        """
        RTL-SDRインターフェースを初期化
        
        Args:
            device_id: RTL-SDRデバイスID（デフォルト: 0）
        """
        self.device_id = device_id
        self.sdr = None
        self.is_open = False
        
        # デフォルト設定値
        self._frequency = 473142857  # Hz (チャンネル13)
        self._sample_rate = 2048000  # Hz
        self._gain = None  # None = 自動ゲイン
        
        logger.info(f"RTL-SDRインターフェース初期化: device_id={device_id}")
        
        if not RTLSDR_AVAILABLE:
            logger.warning("pyrtlsdrライブラリが利用できません（開発モード）")
    
    def open(self) -> bool:
        """
        RTL-SDRデバイスを開く
        
        Returns:
            bool: 成功時True、失敗時False
        """
        if self.is_open:
            logger.warning("デバイスは既に開かれています")
            return True
        
        try:
            if not RTLSDR_AVAILABLE:
                logger.info("開発モード: RTL-SDRデバイスのシミュレーション")
                self.is_open = True
                return True
            
            logger.info(f"RTL-SDRデバイス {self.device_id} を開いています...")
            self.sdr = RtlSdr(device_index=self.device_id)
            
            # 初期設定を適用
            self.sdr.sample_rate = self._sample_rate
            self.sdr.center_freq = self._frequency
            
            if self._gain is not None:
                self.sdr.gain = self._gain
            else:
                self.sdr.gain = 'auto'
            
            self.is_open = True
            logger.info("RTL-SDRデバイスが正常に開かれました")
            logger.info(f"  サンプリングレート: {self.sdr.sample_rate} Hz")
            logger.info(f"  中心周波数: {self.sdr.center_freq} Hz")
            logger.info(f"  ゲイン: {self.sdr.gain}")
            
            return True
            
        except Exception as e:
            logger.error(f"RTL-SDRデバイスのオープンに失敗: {e}")
            self.is_open = False
            return False
    
    def close(self):
        """RTL-SDRデバイスを閉じる"""
        if not self.is_open:
            return
        
        try:
            if RTLSDR_AVAILABLE and self.sdr:
                self.sdr.close()
                logger.info("RTL-SDRデバイスを閉じました")
            else:
                logger.info("開発モード: RTL-SDRデバイスシミュレーション終了")
            
            self.sdr = None
            self.is_open = False
            
        except Exception as e:
            logger.error(f"RTL-SDRデバイスのクローズでエラー: {e}")
    
    def set_frequency(self, freq_hz: float) -> bool:
        """
        中心周波数を設定
        
        Args:
            freq_hz: 周波数（Hz）
            
        Returns:
            bool: 設定成功時True
        """
        try:
            self._frequency = int(freq_hz)
            
            if self.is_open and RTLSDR_AVAILABLE and self.sdr:
                self.sdr.center_freq = self._frequency
                logger.debug(f"中心周波数設定: {self._frequency} Hz")
            else:
                logger.debug(f"開発モード: 中心周波数設定 {self._frequency} Hz")
            
            return True
            
        except Exception as e:
            logger.error(f"周波数設定エラー: {e}")
            return False
    
    def set_sample_rate(self, rate: int) -> bool:
        """
        サンプリングレートを設定
        
        Args:
            rate: サンプリングレート（Hz）
            
        Returns:
            bool: 設定成功時True
        """
        try:
            self._sample_rate = rate
            
            if self.is_open and RTLSDR_AVAILABLE and self.sdr:
                self.sdr.sample_rate = self._sample_rate
                logger.debug(f"サンプリングレート設定: {self._sample_rate} Hz")
            else:
                logger.debug(f"開発モード: サンプリングレート設定 {self._sample_rate} Hz")
            
            return True
            
        except Exception as e:
            logger.error(f"サンプリングレート設定エラー: {e}")
            return False
    
    def set_gain(self, gain_db: Optional[float]) -> bool:
        """
        RF ゲインを設定
        
        Args:
            gain_db: ゲイン値（dB）、Noneで自動ゲイン
            
        Returns:
            bool: 設定成功時True
        """
        try:
            self._gain = gain_db
            
            if self.is_open and RTLSDR_AVAILABLE and self.sdr:
                if gain_db is not None:
                    self.sdr.gain = gain_db
                    logger.debug(f"ゲイン設定: {gain_db} dB")
                else:
                    self.sdr.gain = 'auto'
                    logger.debug("ゲイン設定: 自動")
            else:
                if gain_db is not None:
                    logger.debug(f"開発モード: ゲイン設定 {gain_db} dB")
                else:
                    logger.debug("開発モード: ゲイン設定 自動")
            
            return True
            
        except Exception as e:
            logger.error(f"ゲイン設定エラー: {e}")
            return False
    
    def read_samples(self, num_samples: int):
        """
        I/Qサンプルを読み取り
        
        Args:
            num_samples: 読み取るサンプル数
            
        Returns:
            numpy.ndarray or list: 複素数のI/Qサンプル、エラー時None
        """
        if not self.is_open:
            logger.error("デバイスが開かれていません")
            return None
        
        try:
            if RTLSDR_AVAILABLE and self.sdr:
                # 実際のRTL-SDRから読み取り
                samples = self.sdr.read_samples(num_samples)
                logger.debug(f"読み取りサンプル数: {len(samples)}")
                return samples
            else:
                # 開発モード: ダミーのI/Qサンプルを生成
                logger.debug(f"開発モード: ダミーサンプル生成 {num_samples}個")
                
                if NUMPY_AVAILABLE:
                    # ISDB-Tに近い信号構造をシミュレート
                    t = np.arange(num_samples) / self._sample_rate
                    
                    # 複数のキャリアを持つOFDM様信号をシミュレート
                    signal = np.zeros(num_samples, dtype=complex)
                    
                    # ISDB-T Mode3のキャリア数（13セグメント）をシミュレート
                    carrier_spacing = 1000  # キャリア間隔
                    num_carriers = 13  # セグメント数
                    
                    for i in range(num_carriers):
                        carrier_freq = (i - num_carriers//2) * carrier_spacing
                        # ランダム位相・振幅でキャリアを生成
                        amplitude = 0.05 + 0.03 * np.random.random()
                        phase = 2 * np.pi * np.random.random()
                        carrier = amplitude * np.exp(1j * (2 * np.pi * carrier_freq * t + phase))
                        signal += carrier
                    
                    # ノイズ追加
                    noise_power = 0.05
                    noise = noise_power * (np.random.randn(num_samples) + 1j * np.random.randn(num_samples))
                    
                    samples = signal + noise
                    return samples.astype(np.complex64)
                else:
                    # numpyがない場合は単純なダミーデータ
                    import random
                    samples = []
                    for _ in range(num_samples):
                        # 簡単な複素数データ
                        real = random.uniform(-0.1, 0.1)
                        imag = random.uniform(-0.1, 0.1)
                        samples.append(complex(real, imag))
                    return samples
                
        except Exception as e:
            logger.error(f"サンプル読み取りエラー: {e}")
            return None
    
    def get_device_info(self) -> dict:
        """
        デバイス情報を取得
        
        Returns:
            dict: デバイス情報
        """
        info = {
            'device_id': self.device_id,
            'is_open': self.is_open,
            'frequency': self._frequency,
            'sample_rate': self._sample_rate,
            'gain': self._gain,
            'rtlsdr_available': RTLSDR_AVAILABLE
        }
        
        if self.is_open and RTLSDR_AVAILABLE and self.sdr:
            try:
                info.update({
                    'actual_frequency': self.sdr.center_freq,
                    'actual_sample_rate': self.sdr.sample_rate,
                    'actual_gain': self.sdr.gain,
                })
            except:
                pass
        
        return info
    
    @staticmethod
    def _check_hardware_presence() -> bool:
        """
        実際のRTL-SDRハードウェアの存在を確認
        
        Returns:
            bool: ハードウェアが検出された場合True
        """
        try:
            import subprocess
            import re
            
            # lsusbコマンドでRTL2832Uデバイスを検索
            result = subprocess.run(['lsusb'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                # RTL2832U関連のUSBデバイスを検索
                rtl_patterns = [
                    r'0bda:2832',  # Realtek RTL2832U
                    r'0bda:2838',  # Realtek RTL2838
                    r'RTL2832U',
                    r'RTL-SDR'
                ]
                
                for pattern in rtl_patterns:
                    if re.search(pattern, result.stdout, re.IGNORECASE):
                        logger.debug(f"RTL-SDRハードウェア検出: {pattern}")
                        return True
            
            # /dev/swradio* デバイスファイルの存在確認
            import glob
            swradio_devices = glob.glob('/dev/swradio*')
            if swradio_devices:
                logger.debug(f"Software Radio デバイス検出: {swradio_devices}")
                return True
                
            return False
            
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            logger.debug("lsusbコマンドでのデバイス検索に失敗")
            return False
        except Exception as e:
            logger.debug(f"ハードウェア検出エラー: {e}")
            return False

    @staticmethod
    def list_devices() -> List[Tuple[int, str]]:
        """
        利用可能なRTL-SDRデバイスを一覧表示
        
        Returns:
            List[Tuple[int, str]]: (device_id, description)のリスト
        """
        devices = []
        
        if not RTLSDR_AVAILABLE:
            logger.warning("pyrtlsdrライブラリが利用できません")
            # まず実際のハードウェア検出を試行
            if RTLInterface._check_hardware_presence():
                logger.info("RTL-SDRハードウェアが検出されましたが、pyrtlsdrライブラリが不足しています")
                devices.append((0, "RTL2832U (ドライバ不足・要pyrtlsdr)"))
            else:
                logger.info("RTL-SDRハードウェアが検出されません")
                # ハードウェアなしの場合は空のリストを返す
            return devices
        
        try:
            # RTL-SDRデバイスを検索
            for i in range(10):  # 最大10台まで検索
                try:
                    test_sdr = RtlSdr(device_index=i)
                    # デバイス情報を取得（可能であれば）
                    device_name = f"RTL2832U Device {i}"
                    test_sdr.close()
                    devices.append((i, device_name))
                    logger.debug(f"RTL-SDRデバイス検出: {i}")
                except:
                    # デバイスが存在しない場合はループを抜ける
                    break
                    
        except Exception as e:
            logger.error(f"デバイス検索エラー: {e}")
        
        if not devices:
            logger.info("RTL-SDRデバイスが見つかりませんでした")
        
        return devices
    
    def __enter__(self):
        """コンテキストマネージャ: with文でのエントリー"""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャ: with文での終了"""
        self.close()
    
    def __del__(self):
        """デストラクタ: オブジェクト削除時にデバイスを閉じる"""
        self.close()