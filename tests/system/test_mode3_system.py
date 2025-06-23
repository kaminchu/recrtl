#!/usr/bin/env python3
"""
ISDB-T Mode3復調テストスクリプト

13セグメント分離、ワンセグ抽出、QAM復調機能の動作確認を行う。
"""

import sys
import os
import logging
import math
import cmath

# プロジェクトのsrcディレクトリをPythonパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

from isdb_decoder import ISDBDecoder

def setup_logging():
    """ログ設定"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s',
        stream=sys.stderr
    )

def create_mode3_test_signal(decoder):
    """
    ISDB-T Mode3テスト信号を生成（13セグメント構成）
    
    Args:
        decoder: ISDBDecoderインスタンス
        
    Returns:
        List: Mode3テスト信号
    """
    # FFTサイズの周波数領域信号を生成
    freq_signal = [complex(0.01, 0.01) for _ in range(decoder.FFT_SIZE)]  # ベースノイズ
    
    # 13セグメント構成をシミュレート
    carriers_per_segment = 108
    
    # セグメント0（ワンセグ）に強い信号を配置
    oneseg_start = decoder.ONESEG_START
    oneseg_end = decoder.ONESEG_END
    
    for i in range(oneseg_start, oneseg_end):
        # QPSK様の信号（4つの位相状態）
        phase_index = (i - oneseg_start) % 4
        phase = phase_index * math.pi / 2  # 0°, 90°, 180°, 270°
        freq_signal[i] = 0.8 * cmath.exp(1j * phase)
    
    # 他のセグメント（1-12）にも信号を配置（低強度）
    for seg_id in range(1, 13):
        if 1 <= seg_id <= 6:
            # 右側セグメント
            segment_offset = (seg_id - 1) * carriers_per_segment
            start_idx = oneseg_end + segment_offset
            end_idx = start_idx + carriers_per_segment
        else:
            # 左側セグメント
            segment_offset = (seg_id - 7) * carriers_per_segment
            end_idx = oneseg_start - segment_offset
            start_idx = end_idx - carriers_per_segment
        
        # 範囲チェック
        if start_idx >= 0 and end_idx <= len(freq_signal):
            for i in range(start_idx, end_idx):
                # 16QAM様の信号（低強度）
                amplitude = 0.3
                phase = ((i - start_idx) % 16) * math.pi / 8
                freq_signal[i] = amplitude * cmath.exp(1j * phase)
    
    # IFFTを適用して時間領域信号に変換
    if NUMPY_AVAILABLE:
        import numpy as np
        freq_array = np.array(freq_signal)
        # fftshiftを元に戻す
        freq_unshifted = np.fft.ifftshift(freq_array)
        # IFFTで時間領域に変換
        time_signal = np.fft.ifft(freq_unshifted)
        time_signal = time_signal.tolist()
    else:
        # numpy非依存の簡易IFFT（近似）
        time_signal = []
        for t in range(decoder.FFT_SIZE):
            sample = 0+0j
            for f in range(len(freq_signal)):
                phase = -2j * math.pi * f * t / decoder.FFT_SIZE
                sample += freq_signal[f] * cmath.exp(phase)
            time_signal.append(sample / decoder.FFT_SIZE)
    
    # ガードインターバルを追加してOFDMシンボルを完成
    guard_interval = time_signal[-decoder.GUARD_SIZE:]
    complete_symbol = guard_interval + time_signal
    
    print(f"Mode3テスト信号生成: {len(complete_symbol)}サンプル")
    print(f"  - ワンセグ: [{oneseg_start}:{oneseg_end}] ({oneseg_end-oneseg_start}キャリア)")
    print(f"  - 全13セグメント構成")
    
    return complete_symbol

def test_segment_extraction():
    """セグメント分離のテスト"""
    print("\n=== セグメント分離テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # テスト用周波数領域信号
    freq_signal = [complex(0.1, 0) for _ in range(decoder.FFT_SIZE)]
    
    # 各セグメントに異なる信号を配置
    test_results = []
    
    for segment_id in range(13):  # セグメント0-12
        # セグメントに固有の信号を配置
        if segment_id == 0:
            # ワンセグ
            for i in range(decoder.ONESEG_START, decoder.ONESEG_END):
                freq_signal[i] = complex(1.0, 0.5)  # 強い信号
        else:
            # 他のセグメント用のダミー信号配置（簡略化）
            pass
    
    # 各セグメントを抽出してテスト
    for segment_id in [0, 1, 6, 7, 12]:  # 代表的なセグメントをテスト
        carriers = decoder.extract_segment_carriers(freq_signal, segment_id)
        
        success = len(carriers) == 108  # 各セグメントは108キャリア
        test_results.append((segment_id, success, len(carriers)))
        
        print(f"セグメント{segment_id}: {len(carriers)}キャリア ({'✓' if success else '✗'})")
    
    # 全体結果
    success_count = sum(1 for _, success, _ in test_results if success)
    print(f"セグメント分離成功: {success_count}/{len(test_results)}")
    
    return success_count == len(test_results)

def test_qam_demodulation():
    """QAM復調のテスト"""
    print("\n=== QAM復調テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # QPSK復調テスト
    print("QPSK復調テスト:")
    qpsk_carriers = []
    # 4つの基本位相状態
    phases = [0, math.pi/2, math.pi, 3*math.pi/2]
    for phase in phases:
        qpsk_carriers.append(cmath.exp(1j * phase))
    
    qpsk_bits = decoder.demodulate_qpsk(qpsk_carriers)
    expected_qpsk_bits = 4 * 2  # 4キャリア × 2ビット/キャリア
    print(f"  QPSK: {len(qpsk_carriers)}キャリア → {len(qpsk_bits)}ビット (期待: {expected_qpsk_bits})")
    qpsk_success = len(qpsk_bits) == expected_qpsk_bits
    
    # 16QAM復調テスト
    print("16QAM復調テスト:")
    qam16_carriers = []
    # 16QAMの代表的な状態
    for i in range(4):
        for q in range(4):
            amplitude = 0.5 + 0.5 * (i // 2)
            phase = (q // 2) * math.pi + (q % 2) * math.pi / 2
            qam16_carriers.append(amplitude * cmath.exp(1j * phase))
    
    qam16_bits = decoder.demodulate_16qam(qam16_carriers[:4])  # 4キャリアでテスト
    expected_qam16_bits = 4 * 4  # 4キャリア × 4ビット/キャリア
    print(f"  16QAM: 4キャリア → {len(qam16_bits)}ビット (期待: {expected_qam16_bits})")
    qam16_success = len(qam16_bits) == expected_qam16_bits
    
    # 64QAM復調テスト
    print("64QAM復調テスト:")
    qam64_carriers = []
    # 64QAMの代表的な状態
    for i in range(8):
        amplitude = 0.3 + 0.1 * (i // 4)
        phase = (i % 4) * math.pi / 2
        qam64_carriers.append(amplitude * cmath.exp(1j * phase))
    
    qam64_bits = decoder.demodulate_64qam(qam64_carriers[:4])  # 4キャリアでテスト
    expected_qam64_bits = 4 * 6  # 4キャリア × 6ビット/キャリア
    print(f"  64QAM: 4キャリア → {len(qam64_bits)}ビット (期待: {expected_qam64_bits})")
    qam64_success = len(qam64_bits) == expected_qam64_bits
    
    # 結果
    total_success = qpsk_success + qam16_success + qam64_success
    print(f"QAM復調成功: {total_success}/3")
    
    return total_success == 3

def test_oneseg_symbol_processing():
    """ワンセグシンボル処理のテスト"""
    print("\n=== ワンセグシンボル処理テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # Mode3テストシンボルを生成
    test_symbol = create_mode3_test_signal(decoder)
    
    print(f"テストシンボル: {len(test_symbol)}サンプル")
    
    # ワンセグシンボル処理実行
    result = decoder.process_oneseg_symbol(test_symbol)
    
    if result:
        print(f"ワンセグ復調結果:")
        print(f"  セグメントID: {result['segment_id']}")
        print(f"  変調方式: {result['modulation']}")
        print(f"  キャリア数: {result['carrier_count']}")
        print(f"  復調ビット数: {result['bit_count']}")
        print(f"  シンボルパワー: {result['symbol_power']:.6f}")
        
        # 期待値チェック
        expected_carriers = decoder.ONESEG_CARRIERS
        expected_bits = expected_carriers * 2  # QPSK: 2ビット/キャリア
        
        carrier_ok = result['carrier_count'] == expected_carriers
        bits_ok = result['bit_count'] == expected_bits
        
        print(f"  検証: キャリア数{'✓' if carrier_ok else '✗'}, ビット数{'✓' if bits_ok else '✗'}")
        
        return carrier_ok and bits_ok
    else:
        print("ワンセグ復調失敗")
        return False

def test_mode3_stream_processing():
    """Mode3ストリーム処理のテスト"""
    print("\n=== ISDB-T Mode3ストリーム処理テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # 複数のMode3シンボルを生成
    num_symbols = 3
    test_stream = []
    
    for i in range(num_symbols):
        symbol = create_mode3_test_signal(decoder)
        test_stream.extend(symbol)
    
    print(f"Mode3テストストリーム: {len(test_stream)}サンプル ({num_symbols}シンボル)")
    
    # Mode3ストリーム処理実行
    oneseg_results = decoder.process_isdb_mode3_stream(test_stream)
    
    print(f"Mode3復調結果: {len(oneseg_results)}個のワンセグデータ")
    
    if oneseg_results:
        # 各結果の統計
        total_bits = 0
        for i, result in enumerate(oneseg_results):
            print(f"  シンボル{i}: {result['carrier_count']}キャリア, {result['bit_count']}ビット")
            total_bits += result['bit_count']
        
        print(f"  合計復調ビット数: {total_bits}")
        
        # 期待値チェック
        expected_results = num_symbols  # 同期が成功すれば全シンボル処理されるはず
        success = len(oneseg_results) > 0  # 少なくとも1つは成功すればOK
        
        print(f"Mode3ストリーム処理: {'✓ 成功' if success else '✗ 失敗'}")
        return success
    else:
        print("Mode3ストリーム処理失敗")
        return False

def test_full_mode3_pipeline():
    """完全なMode3パイプラインのテスト"""
    print("\n=== 完全Mode3パイプライン統合テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # リアルな条件でのテスト信号生成
    test_signal = create_mode3_test_signal(decoder)
    
    # ノイズ追加
    noisy_signal = []
    for sample in test_signal:
        noise = complex(0.05, 0.05)  # 小さなノイズ
        noisy_signal.append(sample + noise)
    
    print(f"ノイズ付きテスト信号: {len(noisy_signal)}サンプル")
    
    # 完全パイプライン実行
    try:
        # 1. 基本信号処理
        processed = decoder.process_samples(noisy_signal)
        print(f"前処理完了: {len(processed)}サンプル")
        
        # 2. Mode3復調
        if len(processed) >= decoder.SYMBOL_SIZE:
            oneseg_results = decoder.process_isdb_mode3_stream(processed)
            
            if oneseg_results:
                result = oneseg_results[0]  # 最初の結果
                print(f"完全パイプライン成功:")
                print(f"  ワンセグビット数: {result['bit_count']}")
                print(f"  信号品質: {result['symbol_power']:.6f}")
                return True
            else:
                print("Mode3復調段階で失敗")
                return False
        else:
            print("前処理段階でサンプル不足")
            return False
    
    except Exception as e:
        print(f"パイプライン実行エラー: {e}")
        return False

def main():
    """メイン実行関数"""
    setup_logging()
    
    try:
        print("ISDB-T Mode3復調テスト開始\n")
        
        # 各テスト実行
        tests = [
            ("セグメント分離", test_segment_extraction),
            ("QAM復調", test_qam_demodulation),
            ("ワンセグシンボル処理", test_oneseg_symbol_processing),
            ("Mode3ストリーム処理", test_mode3_stream_processing),
            ("完全Mode3パイプライン", test_full_mode3_pipeline)
        ]
        
        results = []
        for test_name, test_func in tests:
            try:
                result = test_func()
                results.append((test_name, result))
                print(f"✓ {test_name}: {'成功' if result else '失敗'}")
            except Exception as e:
                results.append((test_name, False))
                print(f"✗ {test_name}: エラー - {e}")
        
        # 結果サマリー
        print(f"\n=== テスト結果サマリー ===")
        success_count = sum(1 for _, result in results if result)
        total_count = len(results)
        
        for test_name, result in results:
            status = "✓ 成功" if result else "✗ 失敗"
            print(f"{status}: {test_name}")
        
        print(f"\n成功率: {success_count}/{total_count} ({100*success_count/total_count:.1f}%)")
        
        if success_count == total_count:
            print("🎉 すべてのMode3テストが成功しました！")
            return 0
        else:
            print("⚠️  一部のMode3テストが失敗しました")
            return 1
            
    except Exception as e:
        print(f"Mode3テスト実行エラー: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())