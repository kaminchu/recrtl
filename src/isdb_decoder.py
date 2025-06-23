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
    
    def extract_segment_carriers(self, frequency_domain_signal, segment_id=0):
        """
        ISDB-T Mode3の13セグメント構成から特定セグメントのキャリアを抽出
        
        Args:
            frequency_domain_signal: FFT後の周波数領域信号
            segment_id: セグメント番号（0=ワンセグ, 1-12=ハイビジョン）
            
        Returns:
            List: 指定セグメントのキャリア
        """
        if len(frequency_domain_signal) < self.FFT_SIZE:
            logger.warning(f"FFTサイズ不足: {len(frequency_domain_signal)} < {self.FFT_SIZE}")
            return frequency_domain_signal
        
        # ISDB-T Mode3: 13セグメント構成
        # 1セグメント = 108キャリア
        # セグメント配置: 中央にセグメント0（ワンセグ）、両側にセグメント1-12
        
        if segment_id == 0:
            # ワンセグ（セグメント0）: 中央108キャリア
            start_idx = self.ONESEG_START
            end_idx = self.ONESEG_END
            
            logger.debug(f"ワンセグ抽出: [{start_idx}:{end_idx}] ({self.ONESEG_CARRIERS}キャリア)")
        else:
            # ハイビジョン用セグメント（1-12）
            # セグメント1-6: ワンセグの右側
            # セグメント7-12: ワンセグの左側
            carriers_per_segment = 108
            
            if 1 <= segment_id <= 6:
                # 右側セグメント
                segment_offset = (segment_id - 1) * carriers_per_segment
                start_idx = self.ONESEG_END + segment_offset
                end_idx = start_idx + carriers_per_segment
            elif 7 <= segment_id <= 12:
                # 左側セグメント
                segment_offset = (segment_id - 7) * carriers_per_segment
                end_idx = self.ONESEG_START - segment_offset
                start_idx = end_idx - carriers_per_segment
            else:
                logger.error(f"無効なセグメント番号: {segment_id} (0-12のみ対応)")
                return []
            
            logger.debug(f"セグメント{segment_id}抽出: [{start_idx}:{end_idx}] ({carriers_per_segment}キャリア)")
        
        # 範囲チェック
        if start_idx < 0 or end_idx > len(frequency_domain_signal):
            logger.warning(f"セグメント範囲エラー: [{start_idx}:{end_idx}] > {len(frequency_domain_signal)}")
            return []
        
        segment_carriers = frequency_domain_signal[start_idx:end_idx]
        logger.debug(f"セグメント{segment_id}キャリア抽出完了: {len(segment_carriers)}キャリア")
        
        return segment_carriers
    
    def demodulate_qpsk(self, carriers):
        """
        QPSK復調（ワンセグで使用）
        
        Args:
            carriers: 複素キャリア信号
            
        Returns:
            List: 復調ビット列
        """
        if len(carriers) == 0:
            return []
        
        bits = []
        
        for carrier in carriers:
            # QPSK: 4つの位相状態（0°, 90°, 180°, 270°）
            # 各キャリアから2ビットを復調
            
            # 位相角度を計算
            phase = cmath.phase(carrier)
            
            # 位相を4象限に分割
            # 0°-90°: 00, 90°-180°: 01, 180°-270°: 11, 270°-360°: 10
            if -math.pi/4 <= phase < math.pi/4:
                # 0°付近: 00
                bits.extend([0, 0])
            elif math.pi/4 <= phase < 3*math.pi/4:
                # 90°付近: 01
                bits.extend([0, 1])
            elif 3*math.pi/4 <= phase <= math.pi or -math.pi <= phase < -3*math.pi/4:
                # 180°付近: 11
                bits.extend([1, 1])
            else:
                # 270°付近: 10
                bits.extend([1, 0])
        
        logger.debug(f"QPSK復調: {len(carriers)}キャリア → {len(bits)}ビット")
        return bits
    
    def demodulate_16qam(self, carriers):
        """
        16QAM復調（ハイビジョン用セグメントで使用）
        
        Args:
            carriers: 複素キャリア信号
            
        Returns:
            List: 復調ビット列
        """
        if len(carriers) == 0:
            return []
        
        bits = []
        
        for carrier in carriers:
            # 16QAM: 16の振幅・位相状態
            # 各キャリアから4ビットを復調
            
            # 正規化（簡易版）
            magnitude = abs(carrier)
            if magnitude > 0:
                normalized = carrier / magnitude
            else:
                normalized = 0+0j
            
            # I/Q成分を取得
            i_val = normalized.real
            q_val = normalized.imag
            
            # 4x4グリッドにマッピング（簡易版）
            i_bit = 1 if i_val >= 0 else 0
            q_bit = 1 if q_val >= 0 else 0
            
            # 振幅レベル判定（簡易版）
            amp_i = 1 if abs(i_val) > 0.5 else 0
            amp_q = 1 if abs(q_val) > 0.5 else 0
            
            # 4ビット生成
            bits.extend([i_bit, amp_i, q_bit, amp_q])
        
        logger.debug(f"16QAM復調: {len(carriers)}キャリア → {len(bits)}ビット")
        return bits
    
    def demodulate_64qam(self, carriers):
        """
        64QAM復調（ハイビジョン用セグメントで使用）
        
        Args:
            carriers: 複素キャリア信号
            
        Returns:
            List: 復調ビット列
        """
        if len(carriers) == 0:
            return []
        
        bits = []
        
        for carrier in carriers:
            # 64QAM: 64の振幅・位相状態
            # 各キャリアから6ビットを復調
            
            # 正規化（簡易版）
            magnitude = abs(carrier)
            if magnitude > 0:
                normalized = carrier / magnitude
            else:
                normalized = 0+0j
            
            # I/Q成分を取得
            i_val = normalized.real
            q_val = normalized.imag
            
            # 8x8グリッドにマッピング（簡易版）
            # 3ビットずつでI/Q成分を表現
            
            # I成分3ビット
            i_bits = []
            i_level = int((i_val + 1.0) * 4)  # -1.0〜1.0 を 0〜8 にマップ
            i_level = max(0, min(7, i_level))  # 0-7の範囲にクリップ
            for j in range(3):
                i_bits.append((i_level >> (2-j)) & 1)
            
            # Q成分3ビット
            q_bits = []
            q_level = int((q_val + 1.0) * 4)  # -1.0〜1.0 を 0〜8 にマップ
            q_level = max(0, min(7, q_level))  # 0-7の範囲にクリップ
            for j in range(3):
                q_bits.append((q_level >> (2-j)) & 1)
            
            # 6ビット結合
            bits.extend(i_bits + q_bits)
        
        logger.debug(f"64QAM復調: {len(carriers)}キャリア → {len(bits)}ビット")
        return bits
    
    def process_oneseg_symbol(self, ofdm_symbol):
        """
        単一OFDMシンボルからワンセグデータを抽出・復調
        
        Args:
            ofdm_symbol: 時間領域OFDMシンボル
            
        Returns:
            dict: ワンセグ復調結果
        """
        if len(ofdm_symbol) < self.SYMBOL_SIZE:
            logger.warning(f"OFDMシンボルサイズ不足: {len(ofdm_symbol)}")
            return {}
        
        # 1. ガードインターバル除去
        fft_input = self.remove_guard_interval(ofdm_symbol)
        
        # 2. FFT実行
        frequency_domain = self.apply_fft(fft_input)
        
        # 3. ワンセグセグメント（セグメント0）抽出
        oneseg_carriers = self.extract_segment_carriers(frequency_domain, segment_id=0)
        
        if not oneseg_carriers:
            logger.warning("ワンセグキャリア抽出失敗")
            return {}
        
        # 4. QPSK復調（ワンセグはQPSKを使用）
        demodulated_bits = self.demodulate_qpsk(oneseg_carriers)
        
        # 5. 結果をまとめる
        result = {
            'segment_id': 0,
            'modulation': 'QPSK',
            'carriers': oneseg_carriers,
            'carrier_count': len(oneseg_carriers),
            'demodulated_bits': demodulated_bits,
            'bit_count': len(demodulated_bits),
            'symbol_power': sum(abs(c)**2 for c in oneseg_carriers) / len(oneseg_carriers) if oneseg_carriers else 0
        }
        
        logger.debug(f"ワンセグ復調完了: {result['carrier_count']}キャリア → {result['bit_count']}ビット")
        return result
    
    def process_isdb_mode3_stream(self, samples):
        """
        ISDB-T Mode3ストリーム処理（13セグメント対応）
        
        Args:
            samples: 連続I/Qサンプル
            
        Returns:
            List: ワンセグ復調結果のリスト
        """
        if len(samples) < self.SYMBOL_SIZE:
            logger.warning("ISDB-T Mode3処理: サンプル数不足")
            return []
        
        oneseg_results = []
        current_pos = 0
        
        # シンボル同期
        sync_offset, sync_confidence = self.symbol_synchronization(samples[current_pos:])
        
        if sync_confidence < 0.3:  # 同期信頼度しきい値を緩和
            logger.warning(f"ISDB-T Mode3同期失敗: 信頼度={sync_confidence:.3f}")
            return []
        
        current_pos += sync_offset
        logger.info(f"ISDB-T Mode3同期成功: オフセット={sync_offset}, 信頼度={sync_confidence:.3f}")
        
        # 連続するシンボルを処理
        symbol_count = 0
        while current_pos + self.SYMBOL_SIZE <= len(samples):
            # 現在のシンボルを抽出
            current_symbol = samples[current_pos:current_pos + self.SYMBOL_SIZE]
            
            # ワンセグ復調実行
            oneseg_result = self.process_oneseg_symbol(current_symbol)
            
            if oneseg_result:
                oneseg_results.append(oneseg_result)
                symbol_count += 1
            
            # 次のシンボルに進む
            current_pos += self.SYMBOL_SIZE
        
        logger.info(f"ISDB-T Mode3処理完了: {symbol_count}シンボル処理, {len(oneseg_results)}個の有効なワンセグデータ")
        return oneseg_results
    
    def apply_error_correction(self, oneseg_bits: List[int], modulation: str = "QPSK") -> Tuple[List[int], dict]:
        """
        ワンセグビットデータにエラー訂正を適用
        
        Args:
            oneseg_bits: ワンセグから復調されたビット列
            modulation: 変調方式
            
        Returns:
            Tuple[List[int], dict]: (エラー訂正後データ, 処理統計)
        """
        try:
            from error_correction import ErrorCorrectionProcessor
            
            # ワンセグではQPSK、符号化率1/2が一般的
            ecc_processor = ErrorCorrectionProcessor(
                modulation=modulation,
                code_rate="1/2"
            )
            
            corrected_data, stats = ecc_processor.process(oneseg_bits)
            
            logger.debug(f"エラー訂正適用: {len(oneseg_bits)}ビット → {len(corrected_data)}バイト")
            return corrected_data, stats
            
        except ImportError:
            logger.warning("エラー訂正モジュールが利用できません")
            return [], {}
        except Exception as e:
            logger.error(f"エラー訂正処理エラー: {e}")
            return [], {}
    
    def process_oneseg_with_ecc(self, ofdm_symbol):
        """
        エラー訂正付きワンセグ処理
        
        Args:
            ofdm_symbol: 時間領域OFDMシンボル
            
        Returns:
            dict: エラー訂正を含む完全なワンセグ処理結果
        """
        # 基本的なワンセグ復調
        basic_result = self.process_oneseg_symbol(ofdm_symbol)
        
        if not basic_result or 'demodulated_bits' not in basic_result:
            return basic_result
        
        # エラー訂正適用
        corrected_data, ecc_stats = self.apply_error_correction(
            basic_result['demodulated_bits'],
            basic_result['modulation']
        )
        
        # 結果に統合
        enhanced_result = basic_result.copy()
        enhanced_result.update({
            'corrected_data': corrected_data,
            'corrected_bytes': len(corrected_data),
            'error_correction_stats': ecc_stats,
            'ecc_success': len(corrected_data) > 0
        })
        
        logger.debug(f"エラー訂正付きワンセグ処理: {enhanced_result['bit_count']}ビット → {enhanced_result['corrected_bytes']}バイト")
        return enhanced_result
    
    def process_isdb_mode3_with_ecc(self, samples):
        """
        エラー訂正付きISDB-T Mode3ストリーム処理
        
        Args:
            samples: 連続I/Qサンプル
            
        Returns:
            List: エラー訂正付きワンセグ処理結果のリスト
        """
        if len(samples) < self.SYMBOL_SIZE:
            logger.warning("ISDB-T Mode3+ECC処理: サンプル数不足")
            return []
        
        ecc_results = []
        current_pos = 0
        
        # シンボル同期
        sync_offset, sync_confidence = self.symbol_synchronization(samples[current_pos:])
        
        if sync_confidence < 0.3:
            logger.warning(f"ISDB-T Mode3+ECC同期失敗: 信頼度={sync_confidence:.3f}")
            return []
        
        current_pos += sync_offset
        logger.info(f"ISDB-T Mode3+ECC同期成功: オフセット={sync_offset}, 信頼度={sync_confidence:.3f}")
        
        # 連続するシンボルを処理
        symbol_count = 0
        total_corrected_bytes = 0
        
        while current_pos + self.SYMBOL_SIZE <= len(samples):
            # 現在のシンボルを抽出
            current_symbol = samples[current_pos:current_pos + self.SYMBOL_SIZE]
            
            # エラー訂正付きワンセグ処理実行
            ecc_result = self.process_oneseg_with_ecc(current_symbol)
            
            if ecc_result and ecc_result.get('ecc_success', False):
                ecc_results.append(ecc_result)
                total_corrected_bytes += ecc_result.get('corrected_bytes', 0)
                symbol_count += 1
            
            # 次のシンボルに進む
            current_pos += self.SYMBOL_SIZE
        
        logger.info(f"ISDB-T Mode3+ECC処理完了: {symbol_count}シンボル処理, 合計{total_corrected_bytes}バイト訂正")
        return ecc_results
    
    def extract_transport_stream(self, ecc_results: List[dict]) -> bytes:
        """
        エラー訂正済み結果からMPEG-2 Transport Streamを抽出
        
        Args:
            ecc_results: エラー訂正処理結果リスト
            
        Returns:
            bytes: 抽出されたTransport Streamデータ
        """
        if not ecc_results:
            logger.warning("TS抽出: エラー訂正結果が空です")
            return b''
        
        # エラー訂正済みデータを結合
        ts_data = b''
        total_bytes = 0
        
        for result in ecc_results:
            if result.get('ecc_success', False) and 'corrected_data' in result:
                corrected_data = result['corrected_data']
                if isinstance(corrected_data, list):
                    # リスト形式の場合はバイト配列に変換
                    ts_data += bytes(corrected_data)
                elif isinstance(corrected_data, bytes):
                    ts_data += corrected_data
                total_bytes += len(corrected_data)
        
        logger.info(f"TS抽出: 合計{total_bytes}バイトのTransport Streamデータを抽出")
        return ts_data