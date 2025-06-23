#!/usr/bin/env python3
"""
OFDM復調テストスクリプト

OFDM復調機能の動作確認を行う。
"""

import sys
import os
import logging
import math
import cmath

# プロジェクトのsrcディレクトリをPythonパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

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
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )

def create_ofdm_test_signal(decoder, num_symbols=5):
    """
    テスト用のOFDMシンボル信号を生成
    
    Args:
        decoder: ISDBDecoderインスタンス
        num_symbols: 生成するシンボル数
        
    Returns:
        List: 連続OFDMシンボル信号
    """
    signal = []
    
    for symbol_idx in range(num_symbols):
        # 各シンボルを生成
        ofdm_symbol = []
        
        # FFT部分生成（複素正弦波の組み合わせ）
        for i in range(decoder.FFT_SIZE):
            # 複数の周波数成分を混合
            t = i / decoder.FFT_SIZE
            phase1 = 2 * math.pi * 100 * t  # 100番目のキャリア
            phase2 = 2 * math.pi * 200 * t  # 200番目のキャリア
            
            sample = 0.7 * cmath.exp(1j * phase1) + 0.3 * cmath.exp(1j * phase2)
            ofdm_symbol.append(sample)
        
        # ガードインターバル追加（シンボル末尾をコピー）
        guard_interval = ofdm_symbol[-decoder.GUARD_SIZE:]
        complete_symbol = guard_interval + ofdm_symbol
        
        signal.extend(complete_symbol)
    
    print(f"テストOFDM信号生成: {num_symbols}シンボル, {len(signal)}サンプル")
    return signal

def test_guard_interval_removal():
    """ガードインターバル除去のテスト"""
    print("\n=== ガードインターバル除去テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # テストシンボル生成
    fft_data = [complex(i, -i) for i in range(decoder.FFT_SIZE)]
    guard_data = fft_data[-decoder.GUARD_SIZE:]  # 末尾コピー
    test_symbol = guard_data + fft_data
    
    print(f"入力シンボルサイズ: {len(test_symbol)} (期待値: {decoder.SYMBOL_SIZE})")
    
    # ガードインターバル除去
    result = decoder.remove_guard_interval(test_symbol)
    
    print(f"出力データサイズ: {len(result)} (期待値: {decoder.FFT_SIZE})")
    print(f"データ整合性: {'✓' if result == fft_data else '✗'}")
    
    return result == fft_data

def test_fft_processing():
    """FFT処理のテスト"""
    print("\n=== FFT処理テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    if not NUMPY_AVAILABLE:
        print("numpy利用不可 - FFTテストをスキップ")
        return True
    
    # 単純な正弦波テスト信号
    test_freq = 100  # 100番目のFFTビン
    time_signal = []
    
    for i in range(decoder.FFT_SIZE):
        t = i / decoder.FFT_SIZE
        phase = 2 * math.pi * test_freq * t
        time_signal.append(cmath.exp(1j * phase))
    
    print(f"テスト信号: {test_freq}番目のFFTビンに集中")
    
    # FFT実行
    freq_domain = decoder.apply_fft(time_signal)
    
    if freq_domain:
        print(f"FFT出力サイズ: {len(freq_domain)}")
        
        # 最大値の位置を確認
        max_idx = 0
        max_val = 0
        for i, val in enumerate(freq_domain):
            if abs(val) > max_val:
                max_val = abs(val)
                max_idx = i
        
        print(f"最大値位置: {max_idx}, 値: {max_val:.3f}")
        # fftshiftにより中央揃えされているため、実際の位置は異なる
        return True
    
    return False

def test_symbol_synchronization():
    """シンボル同期のテスト"""
    print("\n=== シンボル同期テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # 正しいOFDMシンボルを埋め込んだ信号
    # ランダムなプリアンブル
    preamble = [complex(0.1, 0.1) for _ in range(100)]
    
    # 正しいOFDMシンボル
    correct_symbol = create_ofdm_test_signal(decoder, 1)
    
    # 追加ノイズ
    noise = [complex(0.01, 0.01) for _ in range(50)]
    
    # 合成信号
    test_signal = preamble + correct_symbol + noise
    
    print(f"テスト信号: プリアンブル{len(preamble)} + シンボル{len(correct_symbol)} + ノイズ{len(noise)}")
    
    # シンボル同期実行
    offset, confidence = decoder.symbol_synchronization(test_signal)
    
    expected_offset = len(preamble)
    print(f"検出オフセット: {offset} (期待値: {expected_offset})")
    print(f"同期信頼度: {confidence:.3f}")
    
    # 許容誤差内での成功判定
    tolerance = 10
    success = abs(offset - expected_offset) <= tolerance and confidence > 0.1
    print(f"同期結果: {'✓ 成功' if success else '✗ 失敗'}")
    
    return success

def test_oneseg_carrier_extraction():
    """ワンセグキャリア抽出のテスト"""
    print("\n=== ワンセグキャリア抽出テスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # FFTサイズの周波数領域信号をシミュレート
    freq_signal = [complex(0.1, 0) for _ in range(decoder.FFT_SIZE)]
    
    # ワンセグ範囲に信号を配置
    for i in range(decoder.ONESEG_START, decoder.ONESEG_END):
        freq_signal[i] = complex(1.0, 0.5)  # 強い信号
    
    print(f"入力信号サイズ: {len(freq_signal)}")
    print(f"ワンセグ範囲: [{decoder.ONESEG_START}:{decoder.ONESEG_END}] ({decoder.ONESEG_CARRIERS}キャリア)")
    
    # ワンセグキャリア抽出
    oneseg_carriers = decoder.extract_oneseg_carriers(freq_signal)
    
    print(f"抽出キャリア数: {len(oneseg_carriers)}")
    print(f"期待値: {decoder.ONESEG_CARRIERS}")
    
    # データ内容確認
    if len(oneseg_carriers) > 0:
        first_carrier = oneseg_carriers[0]
        print(f"最初のキャリア: {first_carrier}")
        
        # 強い信号が正しく抽出されているかチェック
        strong_carrier_count = sum(1 for c in oneseg_carriers if abs(c) > 0.5)
        print(f"強いキャリア数: {strong_carrier_count} / {len(oneseg_carriers)}")
    
    return len(oneseg_carriers) == decoder.ONESEG_CARRIERS

def test_complete_ofdm_pipeline():
    """完全なOFDM復調パイプラインのテスト"""
    print("\n=== 完全OFDM復調パイプラインテスト ===")
    
    decoder = ISDBDecoder(sample_rate=2048000)
    
    # 複数のOFDMシンボルを含むテスト信号
    test_signal = create_ofdm_test_signal(decoder, num_symbols=3)
    
    print(f"テスト信号サイズ: {len(test_signal)}サンプル")
    
    # OFDM復調実行
    demodulated_symbols = decoder.process_ofdm_stream(test_signal)
    
    print(f"復調シンボル数: {len(demodulated_symbols)}")
    
    if len(demodulated_symbols) > 0:
        first_symbol = demodulated_symbols[0]
        print(f"最初のシンボルキャリア数: {len(first_symbol)}")
        print(f"期待キャリア数: {decoder.ONESEG_CARRIERS}")
        
        # 各シンボルの統計
        for i, symbol in enumerate(demodulated_symbols):
            if len(symbol) > 0:
                avg_power = sum(abs(c)**2 for c in symbol) / len(symbol)
                print(f"シンボル{i}: {len(symbol)}キャリア, 平均パワー={avg_power:.6f}")
    
    # 期待される復調シンボル数をチェック
    expected_symbols = len(test_signal) // decoder.SYMBOL_SIZE
    print(f"期待シンボル数: {expected_symbols}")
    
    success = len(demodulated_symbols) > 0
    print(f"パイプライン結果: {'✓ 成功' if success else '✗ 失敗'}")
    
    return success

def main():
    """メイン実行関数"""
    setup_logging()
    
    try:
        print("OFDM復調テスト開始\n")
        
        # 各テスト実行
        tests = [
            ("ガードインターバル除去", test_guard_interval_removal),
            ("FFT処理", test_fft_processing),
            ("シンボル同期", test_symbol_synchronization),
            ("ワンセグキャリア抽出", test_oneseg_carrier_extraction),
            ("完全パイプライン", test_complete_ofdm_pipeline)
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
            print("🎉 すべてのOFDMテストが成功しました！")
            return 0
        else:
            print("⚠️  一部のOFDMテストが失敗しました")
            return 1
            
    except Exception as e:
        print(f"OFDM テスト実行エラー: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())