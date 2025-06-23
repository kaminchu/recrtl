#!/usr/bin/env python3
"""
エラー訂正機能ユニットテスト

リードソロモン符号、畳み込み符号、デインターリーブ機能のテスト
"""

import sys
import os

# プロジェクトのsrcディレクトリをPythonパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

def test_reed_solomon_decoder():
    """リードソロモンデコーダーのテスト"""
    print("リードソロモンデコーダーテスト:")
    
    try:
        from error_correction import ReedSolomonDecoder
        
        decoder = ReedSolomonDecoder()
        print(f"  ✓ RS({decoder.n},{decoder.k})デコーダー初期化成功")
        
        # エラーなしデータのテスト
        clean_data = list(range(204))  # 0-203のテストデータ
        decoded, success = decoder.decode(clean_data)
        
        print(f"  ✓ エラーなし復号: {len(decoded)}バイト, 成功={success}")
        
        # ガロア体演算テスト
        result1 = decoder.gf_mul(2, 3)
        result2 = decoder.gf_div(6, 2)
        print(f"  ✓ ガロア体演算: 2×3={result1}, 6÷2={result2}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_convolutional_decoder():
    """畳み込みデコーダーのテスト"""
    print("畳み込みデコーダーテスト:")
    
    try:
        from error_correction import ConvolutionalDecoder
        
        # 符号化率1/2のテスト
        decoder_12 = ConvolutionalDecoder("1/2")
        print(f"  ✓ 符号化率1/2デコーダー初期化")
        
        # 符号化率2/3のテスト
        decoder_23 = ConvolutionalDecoder("2/3")
        print(f"  ✓ 符号化率2/3デコーダー初期化")
        
        # テストビット列
        test_bits = [1, 0, 1, 1, 0, 0, 1, 0] * 4  # 32ビット
        
        # ビタビ復号テスト
        decoded_12 = decoder_12.viterbi_decode(test_bits)
        decoded_23 = decoder_23.viterbi_decode(test_bits)
        
        print(f"  ✓ ビタビ復号1/2: {len(test_bits)}→{len(decoded_12)}ビット")
        print(f"  ✓ ビタビ復号2/3: {len(test_bits)}→{len(decoded_23)}ビット")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_bit_deinterleaver():
    """ビットデインターリーバーのテスト"""
    print("ビットデインターリーバーテスト:")
    
    try:
        from error_correction import BitDeinterleaver
        
        # QPSK用デインターリーバー
        deinterleaver_qpsk = BitDeinterleaver("QPSK")
        print(f"  ✓ QPSKデインターリーバー初期化: {deinterleaver_qpsk.bits_per_symbol}ビット/シンボル")
        
        # 16QAM用デインターリーバー
        deinterleaver_16qam = BitDeinterleaver("16QAM")
        print(f"  ✓ 16QAMデインターリーバー初期化: {deinterleaver_16qam.bits_per_symbol}ビット/シンボル")
        
        # テストビット列
        test_bits = [1, 0, 1, 1, 0, 0, 1, 0] * 2  # 16ビット
        
        # デインターリーブテスト
        deinterleaved_qpsk = deinterleaver_qpsk.deinterleave(test_bits)
        deinterleaved_16qam = deinterleaver_16qam.deinterleave(test_bits)
        
        print(f"  ✓ QPSKデインターリーブ: {len(test_bits)}→{len(deinterleaved_qpsk)}ビット")
        print(f"  ✓ 16QAMデインターリーブ: {len(test_bits)}→{len(deinterleaved_16qam)}ビット")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_byte_deinterleaver():
    """バイトデインターリーバーのテスト"""
    print("バイトデインターリーバーテスト:")
    
    try:
        from error_correction import ByteDeinterleaver
        
        deinterleaver = ByteDeinterleaver()
        print(f"  ✓ バイトデインターリーバー初期化: 深度{deinterleaver.convolutional_interleave_depth}")
        
        # テストバイト列
        test_bytes = list(range(48))  # 48バイトのテストデータ
        
        # デインターリーブテスト
        deinterleaved = deinterleaver.deinterleave(test_bytes)
        
        print(f"  ✓ バイトデインターリーブ: {len(test_bytes)}→{len(deinterleaved)}バイト")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_error_correction_processor():
    """エラー訂正処理統合クラスのテスト"""
    print("エラー訂正処理統合テスト:")
    
    try:
        from error_correction import ErrorCorrectionProcessor
        
        # QPSKエラー訂正処理
        processor_qpsk = ErrorCorrectionProcessor("QPSK", "1/2")
        print(f"  ✓ QPSK+1/2エラー訂正処理初期化")
        
        # 16QAMエラー訂正処理
        processor_16qam = ErrorCorrectionProcessor("16QAM", "2/3")
        print(f"  ✓ 16QAM+2/3エラー訂正処理初期化")
        
        # テストビット列（十分な長さ）
        test_bits = ([1, 0, 1, 1, 0, 0, 1, 0] * 256)  # 2048ビット
        
        # 完全エラー訂正処理テスト
        corrected_qpsk, stats_qpsk = processor_qpsk.process(test_bits)
        corrected_16qam, stats_16qam = processor_16qam.process(test_bits)
        
        print(f"  ✓ QPSK完全処理: {stats_qpsk['input_bits']}ビット→{stats_qpsk['output_bytes']}バイト")
        print(f"  ✓ 16QAM完全処理: {stats_16qam['input_bits']}ビット→{stats_16qam['output_bytes']}バイト")
        
        # 統計情報テスト
        stats_info_qpsk = processor_qpsk.get_correction_stats()
        stats_info_16qam = processor_16qam.get_correction_stats()
        
        print(f"  ✓ QPSK統計: {stats_info_qpsk['modulation']}, {stats_info_qpsk['rs_parameters']}")
        print(f"  ✓ 16QAM統計: {stats_info_16qam['modulation']}, {stats_info_16qam['rs_parameters']}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def main():
    """メイン実行関数"""
    print("エラー訂正機能ユニットテスト")
    print("=" * 50)
    
    tests = [
        ("リードソロモンデコーダー", test_reed_solomon_decoder),
        ("畳み込みデコーダー", test_convolutional_decoder),
        ("ビットデインターリーバー", test_bit_deinterleaver),
        ("バイトデインターリーバー", test_byte_deinterleaver),
        ("エラー訂正処理統合", test_error_correction_processor)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"  ✗ テスト例外: {e}")
            results.append((test_name, False))
    
    # 結果サマリー
    print(f"\n" + "=" * 50)
    print("テスト結果サマリー:")
    
    success_count = 0
    for test_name, result in results:
        status = "✓ 成功" if result else "✗ 失敗"
        print(f"  {status}: {test_name}")
        if result:
            success_count += 1
    
    total_count = len(results)
    print(f"\n成功率: {success_count}/{total_count} ({100*success_count/total_count:.1f}%)")
    
    if success_count == total_count:
        print("🎉 すべてのエラー訂正テストが成功しました！")
        return 0
    else:
        print("⚠️  一部のエラー訂正テストが失敗しました")
        return 1

if __name__ == "__main__":
    sys.exit(main())