#!/usr/bin/env python3
"""
シンプルなISDB復調器テスト（numpy非依存）
"""

import sys
import os
import logging

# プロジェクトのsrcディレクトリをPythonパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

def setup_logging():
    """ログ設定"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s',
        stream=sys.stderr
    )

def test_isdb_import():
    """ISDB復調器のインポートテスト"""
    try:
        from isdb_decoder import ISDBDecoder
        print("✓ ISDBDecoder インポート成功")
        return True
    except Exception as e:
        print(f"✗ ISDBDecoder インポート失敗: {e}")
        return False

def test_isdb_initialization():
    """ISDB復調器の初期化テスト"""
    try:
        from isdb_decoder import ISDBDecoder
        
        decoder = ISDBDecoder(sample_rate=2048000)
        print("✓ ISDBDecoder 初期化成功")
        
        # 基本パラメータ確認
        print(f"  サンプリングレート: {decoder.sample_rate}")
        print(f"  目標レート: {decoder.target_rate}")
        print(f"  DC除去α: {decoder.dc_removal_alpha}")
        print(f"  AGC参照レベル: {decoder.agc_reference}")
        
        return True
    except Exception as e:
        print(f"✗ ISDBDecoder 初期化失敗: {e}")
        return False

def test_basic_operations():
    """基本操作のテスト"""
    try:
        from isdb_decoder import ISDBDecoder
        
        decoder = ISDBDecoder(sample_rate=1000000)
        
        # テストサンプル作成（複素数リスト）
        test_samples = [1+0j, 0.5+0.5j, 0+1j, -0.5+0.5j, -1+0j]
        print(f"テストサンプル: {test_samples}")
        
        # DC除去テスト
        dc_removed = decoder.remove_dc(test_samples)
        print(f"✓ DC除去実行成功")
        
        # AGCテスト
        agc_applied = decoder.apply_agc(test_samples)
        print(f"✓ AGC実行成功")
        
        # 統計取得
        stats = decoder.get_signal_stats()
        print(f"✓ 統計取得成功: {len(stats)}項目")
        
        # 状態リセット
        decoder.reset_state()
        print(f"✓ 状態リセット成功")
        
        return True
    except Exception as e:
        print(f"✗ 基本操作テスト失敗: {e}")
        return False

def test_signal_generation():
    """信号生成テスト"""
    try:
        from isdb_decoder import ISDBDecoder
        
        # テスト信号生成
        test_signal = ISDBDecoder.generate_test_signal(
            duration_sec=0.001,  # 1ms
            sample_rate=1000000,  # 1MHz
            signal_freq=10000,    # 10kHz
            noise_power=0.01
        )
        
        print(f"✓ テスト信号生成成功: {len(test_signal)}サンプル")
        
        # 信号の基本チェック
        if len(test_signal) > 0:
            print(f"  最初のサンプル: {test_signal[0]}")
            print(f"  信号タイプ: {type(test_signal[0])}")
        
        return True
    except Exception as e:
        print(f"✗ 信号生成テスト失敗: {e}")
        return False

def main():
    """メイン実行関数"""
    setup_logging()
    
    print("ISDB復調器 シンプルテスト開始")
    print("=" * 40)
    
    # テスト実行
    tests = [
        ("インポート", test_isdb_import),
        ("初期化", test_isdb_initialization),
        ("基本操作", test_basic_operations),
        ("信号生成", test_signal_generation)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}テスト:")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ {test_name}テスト例外: {e}")
            results.append((test_name, False))
    
    # 結果サマリー
    print(f"\n" + "=" * 40)
    print(f"テスト結果サマリー:")
    
    success_count = 0
    for test_name, result in results:
        status = "✓ 成功" if result else "✗ 失敗"
        print(f"  {status}: {test_name}")
        if result:
            success_count += 1
    
    total_count = len(results)
    print(f"\n成功率: {success_count}/{total_count} ({100*success_count/total_count:.1f}%)")
    
    if success_count == total_count:
        print("🎉 すべてのテストが成功しました！")
        return 0
    else:
        print("⚠️  一部のテストが失敗しました")
        return 1

if __name__ == "__main__":
    sys.exit(main())