#!/usr/bin/env python3
"""
シンプルなISDB-T Mode3テスト
"""

import sys
import os

# プロジェクトのsrcディレクトリをPythonパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

def test_mode3_import():
    """Mode3機能のインポートテスト"""
    try:
        from isdb_decoder import ISDBDecoder
        decoder = ISDBDecoder(sample_rate=2048000)
        
        # Mode3関連メソッドの存在チェック
        methods = [
            'extract_segment_carriers',
            'demodulate_qpsk', 
            'demodulate_16qam',
            'demodulate_64qam',
            'process_oneseg_symbol',
            'process_isdb_mode3_stream'
        ]
        
        for method in methods:
            if hasattr(decoder, method):
                print(f"✓ {method}: 実装済み")
            else:
                print(f"✗ {method}: 未実装")
                return False
        
        return True
    except Exception as e:
        print(f"✗ インポートエラー: {e}")
        return False

def test_basic_mode3_functions():
    """基本Mode3機能のテスト"""
    try:
        from isdb_decoder import ISDBDecoder
        decoder = ISDBDecoder(sample_rate=2048000)
        
        # 1. セグメント抽出テスト
        print("セグメント抽出テスト:")
        test_freq = [complex(0.1, 0.1)] * decoder.FFT_SIZE
        
        for seg_id in [0, 1, 12]:
            carriers = decoder.extract_segment_carriers(test_freq, seg_id)
            print(f"  セグメント{seg_id}: {len(carriers)}キャリア")
        
        # 2. QPSK復調テスト
        print("QPSK復調テスト:")
        qpsk_carriers = [complex(1, 0), complex(0, 1), complex(-1, 0), complex(0, -1)]
        qpsk_bits = decoder.demodulate_qpsk(qpsk_carriers)
        print(f"  QPSK: {len(qpsk_carriers)}キャリア → {len(qpsk_bits)}ビット")
        
        # 3. 16QAM復調テスト
        print("16QAM復調テスト:")
        qam16_carriers = [complex(0.7, 0.7), complex(-0.7, 0.7)]
        qam16_bits = decoder.demodulate_16qam(qam16_carriers)
        print(f"  16QAM: {len(qam16_carriers)}キャリア → {len(qam16_bits)}ビット")
        
        # 4. 64QAM復調テスト
        print("64QAM復調テスト:")
        qam64_carriers = [complex(0.5, 0.5), complex(-0.5, 0.5)]
        qam64_bits = decoder.demodulate_64qam(qam64_carriers)
        print(f"  64QAM: {len(qam64_carriers)}キャリア → {len(qam64_bits)}ビット")
        
        return True
        
    except Exception as e:
        print(f"✗ 基本機能テストエラー: {e}")
        return False

def main():
    """メイン実行関数"""
    print("ISDB-T Mode3 シンプルテスト")
    print("=" * 40)
    
    tests = [
        ("インポート・メソッド存在確認", test_mode3_import),
        ("基本Mode3機能", test_basic_mode3_functions)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ テスト例外: {e}")
            results.append((test_name, False))
    
    # 結果サマリー
    print(f"\n" + "=" * 40)
    print("テスト結果:")
    
    success_count = 0
    for test_name, result in results:
        status = "✓ 成功" if result else "✗ 失敗"
        print(f"  {status}: {test_name}")
        if result:
            success_count += 1
    
    print(f"\n成功率: {success_count}/{len(results)} ({100*success_count/len(results):.1f}%)")
    
    if success_count == len(results):
        print("🎉 Mode3機能テスト完了！")
        return 0
    else:
        print("⚠️  一部のテストが失敗しました")
        return 1

if __name__ == "__main__":
    sys.exit(main())