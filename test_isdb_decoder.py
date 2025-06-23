#!/usr/bin/env python3
"""
ISDB復調器テストスクリプト

基本信号処理パイプラインの動作確認を行う。
"""

import sys
import os
import logging

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    # numpy代替実装
    class MockNumpy:
        @staticmethod
        def array(data):
            return data
        @staticmethod
        def arange(n):
            return list(range(n))
        @staticmethod
        def exp(x):
            import math
            if isinstance(x, (int, float)):
                return math.exp(x)
            return [math.exp(val) for val in x]
        @staticmethod
        def mean(data):
            return sum(data) / len(data)
        @staticmethod
        def abs(data):
            if isinstance(data, (int, float)):
                return abs(data)
            return [abs(x) for x in data]
        @staticmethod
        def max(data):
            return max(data)
        @staticmethod
        def full(n, value, dtype=None):
            return [value] * n
        @staticmethod
        def linspace(start, stop, num):
            step = (stop - start) / (num - 1)
            return [start + i * step for i in range(num)]
        @staticmethod
        def random():
            return MockRandom()
        pi = 3.14159265359
    
    class MockRandom:
        @staticmethod
        def randn(n):
            import random
            return [random.gauss(0, 1) for _ in range(n)]
    
    np = MockNumpy()

# プロジェクトのsrcディレクトリをPythonパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from isdb_decoder import ISDBDecoder

def setup_logging():
    """ログ設定"""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )

def test_basic_signal_processing():
    """基本信号処理のテスト"""
    print("=== ISDB復調器基本テスト ===")
    
    # テスト信号生成
    duration = 0.1  # 100ms
    sample_rate = 2048000  # 2.048MHz
    signal_freq = 50000   # 50kHz
    
    print(f"テスト信号生成: {duration}秒, {sample_rate}Hz, 信号{signal_freq}Hz")
    test_signal = ISDBDecoder.generate_test_signal(
        duration_sec=duration,
        sample_rate=sample_rate,
        signal_freq=signal_freq,
        noise_power=0.01
    )
    
    print(f"生成サンプル数: {len(test_signal)}")
    print(f"入力信号統計:")
    print(f"  平均パワー: {np.mean(np.abs(test_signal)**2):.6f}")
    print(f"  DC成分: {np.mean(test_signal):.6f}")
    print(f"  最大振幅: {np.max(np.abs(test_signal)):.6f}")
    
    # ISDB復調器初期化
    decoder = ISDBDecoder(sample_rate=sample_rate)
    
    # 処理前の統計
    print(f"\n処理前統計:")
    stats = decoder.get_signal_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # 信号処理実行
    print(f"\n信号処理実行...")
    processed_signal = decoder.process_samples(test_signal)
    
    # 処理後の統計
    print(f"\n処理後統計:")
    stats = decoder.get_signal_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print(f"\n出力信号統計:")
    print(f"  出力サンプル数: {len(processed_signal)}")
    print(f"  平均パワー: {np.mean(np.abs(processed_signal)**2):.6f}")
    print(f"  DC成分: {np.mean(processed_signal):.6f}")
    print(f"  最大振幅: {np.max(np.abs(processed_signal)):.6f}")
    
    # ダウンサンプリング効果確認
    original_rate = sample_rate
    effective_rate = sample_rate / stats['downsample_ratio']
    print(f"\nダウンサンプリング効果:")
    print(f"  元サンプリングレート: {original_rate:,.0f} Hz")
    print(f"  実効サンプリングレート: {effective_rate:,.0f} Hz")
    print(f"  圧縮率: {stats['downsample_ratio']:d}:1")
    
    return True

def test_dc_removal():
    """DC除去機能のテスト"""
    print("\n=== DC除去テスト ===")
    
    # DC成分を持つテスト信号
    sample_rate = 1000000
    duration = 0.01
    dc_offset = 0.5 + 0.3j
    
    decoder = ISDBDecoder(sample_rate=sample_rate)
    
    # DC成分のみの信号
    num_samples = int(duration * sample_rate)
    dc_signal = np.full(num_samples, dc_offset, dtype=complex)
    
    print(f"DC信号: {dc_offset}")
    print(f"入力DC成分: {np.mean(dc_signal):.6f}")
    
    # DC除去処理
    processed = decoder.remove_dc(dc_signal)
    
    print(f"出力DC成分: {np.mean(processed):.6f}")
    print(f"DC推定値: {decoder._dc_estimate:.6f}")
    
    # 最終的にDC成分が除去されているかチェック
    final_dc = np.mean(processed[-1000:])  # 最後の部分
    print(f"最終DC成分: {final_dc:.6f}")
    
    return abs(final_dc) < 0.1  # DC成分が十分小さいことを確認

def test_agc():
    """AGC機能のテスト"""
    print("\n=== AGC テスト ===")
    
    decoder = ISDBDecoder(sample_rate=1000000)
    
    # 振幅の異なる信号をテスト
    test_amplitudes = [0.1, 1.0, 10.0]
    
    for amp in test_amplitudes:
        # テスト信号生成
        test_signal = amp * np.exp(1j * np.linspace(0, 20*np.pi, 10000))
        
        print(f"\n振幅 {amp} の信号:")
        print(f"  入力パワー: {np.mean(np.abs(test_signal)**2):.6f}")
        
        # AGC適用
        decoder.reset_state()  # 状態リセット
        processed = decoder.apply_agc(test_signal)
        
        output_power = np.mean(np.abs(processed)**2)
        print(f"  出力パワー: {output_power:.6f}")
        print(f"  適用ゲイン: {decoder._agc_gain:.3f}")
        
        # AGCが目標レベル付近に調整しているかチェック
        target_power = decoder.agc_reference ** 2
        print(f"  目標パワー: {target_power:.6f}")
    
    return True

def test_full_pipeline():
    """完全パイプラインのテスト"""
    print("\n=== 完全パイプラインテスト ===")
    
    # より現実的なテスト信号
    sample_rate = 2048000
    duration = 0.05  # 50ms
    
    # 複数の周波数成分を含む信号
    num_samples = int(duration * sample_rate)
    t = np.arange(num_samples) / sample_rate
    
    # 複合信号生成
    signal = (0.8 * np.exp(1j * 2 * np.pi * 100e3 * t) +  # 100kHz
              0.3 * np.exp(1j * 2 * np.pi * 200e3 * t) +  # 200kHz
              0.1 + 0.05j)  # DC成分
    
    # ノイズ追加
    noise = 0.1 * (np.random.randn(num_samples) + 1j * np.random.randn(num_samples))
    signal += noise
    
    print(f"複合テスト信号: {len(signal)}サンプル")
    
    # パイプライン処理
    decoder = ISDBDecoder(sample_rate=sample_rate)
    processed = decoder.process_samples(signal)
    
    print(f"処理完了: {len(processed)}サンプル出力")
    
    # 結果統計
    stats = decoder.get_signal_stats()
    print(f"最終統計:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    return len(processed) > 0

def main():
    """メイン実行関数"""
    setup_logging()
    
    try:
        print("ISDB復調器テスト開始\n")
        
        # 各テスト実行
        tests = [
            ("基本信号処理", test_basic_signal_processing),
            ("DC除去", test_dc_removal),
            ("AGC", test_agc),
            ("完全パイプライン", test_full_pipeline)
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
            print("🎉 すべてのテストが成功しました！")
            return 0
        else:
            print("⚠️  一部のテストが失敗しました")
            return 1
            
    except Exception as e:
        print(f"テスト実行エラー: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())