"""
ISDB-T信号処理・復調器

ISDB-T Mode 3（13セグメント）からワンセグ（セグメント0）を復調する。
I/Qサンプルの前処理、DC除去、AGC、ローパスフィルタ、ダウンサンプリングを実装。
"""

import logging
import math
import cmath
from typing import Optional, Tuple, Union, List

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    # numpy代替実装
    class MockArray:
        def __init__(self, data):
            self.data = data if isinstance(data, list) else [data]
        
        def __len__(self):
            return len(self.data)
        
        def __getitem__(self, key):
            if isinstance(key, slice):
                return MockArray(self.data[key])
            return self.data[key]
        
        def __setitem__(self, key, value):
            self.data[key] = value
        
        def copy(self):
            return MockArray(self.data.copy())
        
        def __iter__(self):
            return iter(self.data)
    
    class MockNumpy:
        @staticmethod
        def array(data):
            return MockArray(data)
        
        @staticmethod
        def zeros_like(arr):
            if hasattr(arr, 'data'):
                return MockArray([0+0j] * len(arr.data))
            return MockArray([0+0j] * len(arr))
        
        @staticmethod
        def iscomplexobj(obj):
            if hasattr(obj, 'data'):
                return any(isinstance(x, complex) for x in obj.data)
            return any(isinstance(x, complex) for x in obj)
        
        @staticmethod
        def mean(data):
            if hasattr(data, 'data'):
                data = data.data
            return sum(data) / len(data)
        
        @staticmethod
        def abs(data):
            if hasattr(data, 'data'):
                return MockArray([abs(x) for x in data.data])
            if isinstance(data, (int, float, complex)):
                return abs(data)
            return [abs(x) for x in data]
        
        @staticmethod
        def sqrt(x):
            return math.sqrt(x)
        
        @staticmethod
        def clip(x, min_val, max_val):
            return max(min_val, min(max_val, x))
        
        @staticmethod
        def arange(n):
            return MockArray(list(range(n)))
        
        @staticmethod
        def exp(x):
            if isinstance(x, (int, float)):
                return cmath.exp(x)
            return MockArray([cmath.exp(val) for val in x])
        
        pi = math.pi
    
    np = MockNumpy()

try:
    import scipy.signal
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

logger = logging.getLogger(__name__)

class ISDBDecoder:
    """ISDB-T信号復調クラス"""
    
    # ISDB-T Mode 3定数
    ISDB_SAMPLE_RATE = 64e6 / 7  # 約9.14MHz (64/7 MHz)
    SEGMENT_BANDWIDTH = 6e6 / 13  # 約461.5kHz/セグメント
    ONESEG_BANDWIDTH = SEGMENT_BANDWIDTH  # ワンセグは1セグメント
    
    # FFTサイズとガードインターバル
    FFT_SIZE = 8192  # Mode 3のFFTサイズ
    GUARD_INTERVAL_RATIO = 1/4  # ガードインターバル比率
    GUARD_SIZE = int(FFT_SIZE * GUARD_INTERVAL_RATIO)
    SYMBOL_SIZE = FFT_SIZE + GUARD_SIZE  # 10240サンプル
    
    # ワンセグキャリア範囲（中央108キャリア）
    ONESEG_CARRIERS = 108
    ONESEG_START = (8192 - 108) // 2  # 中央付近
    ONESEG_END = ONESEG_START + ONESEG_CARRIERS
    
    def __init__(self, sample_rate: float = 2048000):
        """
        ISDB-T復調器を初期化
        
        Args:
            sample_rate: RTL-SDRからのサンプリングレート（Hz）
        """
        self.sample_rate = sample_rate
        self.target_rate = self.ISDB_SAMPLE_RATE
        
        # 信号処理パラメータ
        self.dc_removal_alpha = 0.001  # DC除去のアルファ値
        self.agc_reference = 0.5  # AGC目標レベル
        self.agc_bandwidth = 0.01  # AGC帯域幅
        
        # 内部状態
        self._dc_estimate = 0.0 + 0.0j  # DC成分推定値
        self._agc_gain = 1.0  # AGC適用ゲイン
        self._agc_power_estimate = 1.0  # 信号パワー推定値
        
        # フィルタ設計
        self._design_filters()
        
        logger.info(f"ISDB復調器初期化: {sample_rate}Hz → {self.target_rate}Hz")
        logger.debug(f"シンボルサイズ: {self.SYMBOL_SIZE}, FFTサイズ: {self.FFT_SIZE}")
    
    def _design_filters(self):
        """ローパスフィルタとダウンサンプリングフィルタを設計"""
        if not SCIPY_AVAILABLE:
            logger.warning("scipy利用不可 - フィルタなしで動作")
            self._lowpass_filter = None
            self._downsample_ratio = 1
            return
        
        # ダウンサンプリング比を計算
        self._downsample_ratio = int(self.sample_rate / self.target_rate)
        if self._downsample_ratio < 1:
            self._downsample_ratio = 1
        
        # ローパスフィルタ設計（ナイキスト周波数の80%）
        cutoff = 0.4 / self._downsample_ratio  # 正規化カットオフ周波数
        filter_order = 51  # FIRフィルタ次数
        
        try:
            self._lowpass_filter = scipy.signal.firwin(
                filter_order, 
                cutoff, 
                window='hamming'
            )
            logger.debug(f"ローパスフィルタ設計完了: 次数{filter_order}, カットオフ{cutoff:.3f}")
        except Exception as e:
            logger.warning(f"フィルタ設計失敗: {e} - フィルタなしで動作")
            self._lowpass_filter = None
    
    def remove_dc(self, samples):
        """
        DC成分除去（1次IIRハイパスフィルタ）
        
        Args:
            samples: 入力I/Qサンプル
            
        Returns:
            List: DC除去後のサンプル
        """
        if len(samples) == 0:
            return samples
        
        # DC成分を推定・除去
        output = []
        for i in range(len(samples)):
            # DC成分推定更新
            self._dc_estimate = (1 - self.dc_removal_alpha) * self._dc_estimate + \
                               self.dc_removal_alpha * samples[i]
            # DC除去
            output.append(samples[i] - self._dc_estimate)
        
        return output
    
    def apply_agc(self, samples):
        """
        自動ゲイン制御（AGC）を適用
        
        Args:
            samples: 入力I/Qサンプル
            
        Returns:
            List: AGC適用後のサンプル
        """
        if len(samples) == 0:
            return samples
        
        output = np.zeros_like(samples)
        
        for i in range(len(samples)):
            # 現在サンプルのパワー
            sample_power = abs(samples[i]) ** 2
            
            # パワー推定値更新（指数移動平均）
            self._agc_power_estimate = (1 - self.agc_bandwidth) * self._agc_power_estimate + \
                                      self.agc_bandwidth * sample_power
            
            # AGCゲイン計算
            if self._agc_power_estimate > 1e-10:  # ゼロ除算回避
                target_power = self.agc_reference ** 2
                self._agc_gain = np.sqrt(target_power / self._agc_power_estimate)
            
            # ゲイン制限（オーバーフローを防ぐ）
            self._agc_gain = np.clip(self._agc_gain, 0.01, 100.0)
            
            # AGC適用
            output[i] = samples[i] * self._agc_gain
        
        return output
    
    def lowpass_filter(self, samples):
        """
        ローパスフィルタを適用
        
        Args:
            samples: 入力I/Qサンプル
            
        Returns:
            List: フィルタ後のサンプル
        """
        if self._lowpass_filter is None or not SCIPY_AVAILABLE:
            return samples
        
        try:
            # FIRフィルタ適用
            filtered = scipy.signal.lfilter(self._lowpass_filter, 1.0, samples)
            return filtered
        except Exception as e:
            logger.warning(f"ローパスフィルタ適用失敗: {e}")
            return samples
    
    def downsample(self, samples):
        """
        ダウンサンプリング実行
        
        Args:
            samples: 入力I/Qサンプル
            
        Returns:
            List: ダウンサンプリング後のサンプル
        """
        if self._downsample_ratio <= 1:
            return samples
        
        # デシメーション（間引き）
        return samples[::self._downsample_ratio]
    
    def process_samples(self, samples):
        """
        I/Qサンプルの前処理パイプライン
        
        Args:
            samples: 生のI/Qサンプル（complexリスト）
            
        Returns:
            List: 前処理済みサンプル
        """
        if len(samples) == 0:
            return samples
        
        # 入力検証
        if not any(isinstance(x, complex) for x in samples[:min(10, len(samples))]):
            logger.warning("入力サンプルが複素数ではありません")
            return samples
        
        processed = samples.copy() if hasattr(samples, 'copy') else list(samples)
        
        # 処理パイプライン
        logger.debug(f"入力サンプル数: {len(processed)}")
        
        # 1. DC成分除去
        processed = self.remove_dc(processed)
        avg_power = sum(abs(x)**2 for x in processed) / len(processed)
        logger.debug(f"DC除去後: 平均パワー={avg_power:.6f}")
        
        # 2. ローパスフィルタ
        processed = self.lowpass_filter(processed)
        
        # 3. AGC適用
        processed = self.apply_agc(processed)
        avg_power = sum(abs(x)**2 for x in processed) / len(processed)
        logger.debug(f"AGC後: ゲイン={self._agc_gain:.3f}, 平均パワー={avg_power:.6f}")
        
        # 4. ダウンサンプリング
        processed = self.downsample(processed)
        logger.debug(f"ダウンサンプリング後: {len(processed)}サンプル")
        
        return processed
    
    def get_signal_stats(self) -> dict:
        """
        現在の信号統計情報を取得
        
        Returns:
            dict: 信号統計情報
        """
        return {
            'dc_estimate': {
                'real': float(self._dc_estimate.real),
                'imag': float(self._dc_estimate.imag),
                'magnitude': float(abs(self._dc_estimate))
            },
            'agc_gain': float(self._agc_gain),
            'agc_power_estimate': float(self._agc_power_estimate),
            'target_sample_rate': float(self.target_rate),
            'downsample_ratio': int(self._downsample_ratio),
            'has_scipy': SCIPY_AVAILABLE
        }
    
    def reset_state(self):
        """
        内部状態をリセット
        """
        self._dc_estimate = 0.0 + 0.0j
        self._agc_gain = 1.0
        self._agc_power_estimate = 1.0
        logger.debug("ISDB復調器状態リセット完了")

    @staticmethod
    def generate_test_signal(duration_sec: float = 1.0, 
                           sample_rate: float = 2048000,
                           signal_freq: float = 100000,
                           noise_power: float = 0.1):
        """
        テスト用のI/Qサンプル信号を生成
        
        Args:
            duration_sec: 信号継続時間（秒）
            sample_rate: サンプリングレート（Hz）
            signal_freq: 信号周波数（Hz）
            noise_power: ノイズパワー
            
        Returns:
            List: テスト信号（complex）
        """
        import random
        
        num_samples = int(duration_sec * sample_rate)
        
        # 基本信号（複素指数関数）
        signal = []
        for i in range(num_samples):
            t = i / sample_rate
            # 複素指数関数: e^(j*2*pi*f*t)
            phase = 2 * math.pi * signal_freq * t
            signal.append(cmath.exp(1j * phase))
        
        # DC成分を追加
        dc_offset = 0.1 + 0.05j
        signal = [s + dc_offset for s in signal]
        
        # 複素ガウシアンノイズを追加
        noise_std = math.sqrt(noise_power / 2)
        for i in range(len(signal)):
            noise_real = random.gauss(0, noise_std)
            noise_imag = random.gauss(0, noise_std)
            signal[i] += complex(noise_real, noise_imag)
        
        return signal
    
    def remove_guard_interval(self, ofdm_symbol):
        """
        OFDMシンボルからガードインターバルを除去
        
        Args:
            ofdm_symbol: ガードインターバル付きOFDMシンボル（complexリスト）
            
        Returns:
            List: ガードインターバル除去後のシンボル
        """
        if len(ofdm_symbol) < self.SYMBOL_SIZE:
            logger.warning(f"シンボルサイズ不足: {len(ofdm_symbol)} < {self.SYMBOL_SIZE}")
            return ofdm_symbol
        
        # ガードインターバル部分をスキップしてFFT部分のみ抽出
        fft_part = ofdm_symbol[self.GUARD_SIZE:self.GUARD_SIZE + self.FFT_SIZE]
        
        logger.debug(f"ガードインターバル除去: {len(ofdm_symbol)} → {len(fft_part)}サンプル")
        return fft_part
    
    def apply_fft(self, time_domain_signal):
        """
        時間領域信号に対してFFTを適用
        
        Args:
            time_domain_signal: 時間領域の複素信号
            
        Returns:
            List: 周波数領域信号（FFT結果）
        """
        if not NUMPY_AVAILABLE:
            logger.warning("numpy利用不可 - FFT処理をスキップ")
            return time_domain_signal
        
        try:
            # numpyのFFTを使用
            import numpy as np
            
            # データをnumpy配列に変換
            if hasattr(time_domain_signal, 'data'):
                signal_array = np.array(time_domain_signal.data)
            else:
                signal_array = np.array(time_domain_signal)
            
            # FFT実行
            fft_result = np.fft.fft(signal_array)
            
            # FFTの結果を中央揃えする（DC成分を中央に配置）
            fft_shifted = np.fft.fftshift(fft_result)
            
            logger.debug(f"FFT処理完了: {len(time_domain_signal)} → {len(fft_shifted)}ポイント")
            return fft_shifted.tolist()
            
        except Exception as e:
            logger.error(f"FFT処理失敗: {e}")
            return time_domain_signal
    
    def extract_oneseg_carriers(self, frequency_domain_signal):
        """
        周波数領域信号からワンセグ用キャリアを抽出
        
        Args:
            frequency_domain_signal: FFT後の周波数領域信号
            
        Returns:
            List: ワンセグキャリア（108キャリア）
        """
        if len(frequency_domain_signal) < self.FFT_SIZE:
            logger.warning(f"FFTサイズ不足: {len(frequency_domain_signal)} < {self.FFT_SIZE}")
            return frequency_domain_signal
        
        # 中央部分からワンセグキャリアを抽出（108キャリア）
        oneseg_carriers = frequency_domain_signal[self.ONESEG_START:self.ONESEG_END]
        
        logger.debug(f"ワンセグキャリア抽出: {len(frequency_domain_signal)} → {len(oneseg_carriers)}キャリア")
        logger.debug(f"抽出範囲: [{self.ONESEG_START}:{self.ONESEG_END}]")
        
        return oneseg_carriers
    
    def symbol_synchronization(self, samples, search_window=512):
        """
        シンボル同期を行い、OFDM シンボルの開始位置を検出
        
        Args:
            samples: 入力I/Qサンプル
            search_window: 同期検索ウィンドウサイズ
            
        Returns:
            tuple: (同期位置, 信頼度)
        """
        if len(samples) < self.SYMBOL_SIZE + search_window:
            logger.warning("シンボル同期: サンプル数不足")
            return 0, 0.0
        
        max_correlation = 0.0
        best_offset = 0
        
        # ガードインターバルの循環特性を利用した同期
        # ガードインターバルは有効シンボルの末尾のコピー
        for offset in range(search_window):
            if offset + self.SYMBOL_SIZE >= len(samples):
                break
            
            # ガードインターバル部分
            guard_part = samples[offset:offset + self.GUARD_SIZE]
            # 対応する有効シンボル末尾部分
            symbol_end = samples[offset + self.FFT_SIZE:offset + self.SYMBOL_SIZE]
            
            if len(guard_part) != len(symbol_end):
                continue
            
            # 相関計算（正規化相関）
            correlation = 0.0
            guard_power = 0.0
            symbol_power = 0.0
            
            for i in range(len(guard_part)):
                correlation += (guard_part[i].conjugate() * symbol_end[i]).real
                guard_power += abs(guard_part[i]) ** 2
                symbol_power += abs(symbol_end[i]) ** 2
            
            # 正規化
            if guard_power > 0 and symbol_power > 0:
                normalized_correlation = correlation / math.sqrt(guard_power * symbol_power)
                
                if normalized_correlation > max_correlation:
                    max_correlation = normalized_correlation
                    best_offset = offset
        
        logger.debug(f"シンボル同期: オフセット={best_offset}, 相関={max_correlation:.3f}")
        return best_offset, max_correlation
    
    def demodulate_ofdm_symbol(self, ofdm_symbol):
        """
        単一のOFDMシンボルを復調
        
        Args:
            ofdm_symbol: 時間領域OFDMシンボル
            
        Returns:
            List: 復調されたワンセグキャリア
        """
        if len(ofdm_symbol) < self.SYMBOL_SIZE:
            logger.warning(f"OFDMシンボルサイズ不足: {len(ofdm_symbol)}")
            return []
        
        # 1. ガードインターバル除去
        fft_input = self.remove_guard_interval(ofdm_symbol)
        
        # 2. FFT実行
        frequency_domain = self.apply_fft(fft_input)
        
        # 3. ワンセグキャリア抽出
        oneseg_carriers = self.extract_oneseg_carriers(frequency_domain)
        
        return oneseg_carriers
    
    def process_ofdm_stream(self, samples):
        """
        連続的なOFDMストリーム処理
        
        Args:
            samples: 連続I/Qサンプル
            
        Returns:
            List: 処理されたワンセグキャリアのリスト
        """
        if len(samples) < self.SYMBOL_SIZE:
            logger.warning("OFDM処理: サンプル数不足")
            return []
        
        demodulated_symbols = []
        current_pos = 0
        
        # 最初のシンボルの同期を取る
        sync_offset, sync_confidence = self.symbol_synchronization(samples[current_pos:])
        
        if sync_confidence < 0.5:  # 同期信頼度が低い場合
            logger.warning(f"シンボル同期失敗: 信頼度={sync_confidence:.3f}")
            return []
        
        current_pos += sync_offset
        logger.info(f"シンボル同期成功: オフセット={sync_offset}, 信頼度={sync_confidence:.3f}")
        
        # 連続するシンボルを処理
        symbol_count = 0
        while current_pos + self.SYMBOL_SIZE <= len(samples):
            # 現在のシンボルを抽出
            current_symbol = samples[current_pos:current_pos + self.SYMBOL_SIZE]
            
            # OFDM復調実行
            carriers = self.demodulate_ofdm_symbol(current_symbol)
            
            if carriers:
                demodulated_symbols.append(carriers)
                symbol_count += 1
            
            # 次のシンボルに進む
            current_pos += self.SYMBOL_SIZE
        
        logger.info(f"OFDM復調完了: {symbol_count}シンボル処理")
        return demodulated_symbols