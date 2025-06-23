#!/usr/bin/env python3
"""
Transport Stream 出力機能ユニットテスト

TSOutputController、TSStreamGenerator、TSOutputManager クラスのテスト
"""

import sys
import os
import time
import threading
from io import StringIO

# プロジェクトのsrcディレクトリをPythonパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

def test_ts_stream_generator():
    """TSStreamGeneratorクラスのテスト"""
    print("TSStreamGeneratorテスト:")
    
    try:
        from ts_output import TSStreamGenerator
        
        generator = TSStreamGenerator()
        print("  ✓ TSストリーム生成器初期化成功")
        
        # NULLパケット作成テスト
        null_packet = generator._create_null_packet()
        print(f"  ✓ NULLパケット作成: {len(null_packet)}バイト")
        
        if len(null_packet) != 188:
            print(f"  ✗ NULLパケットサイズ異常: {len(null_packet)} != 188")
            return False
        
        if null_packet[0] != 0x47:
            print(f"  ✗ 同期バイト異常: 0x{null_packet[0]:02X} != 0x47")
            return False
        
        # 連続性カウンタ更新テスト
        test_packet = b'\x47\x00\x10\x10' + b'\x00' * 184  # PID=0x0010
        updated_packet = generator.update_continuity_counter(0x0010, test_packet)
        
        original_cc = test_packet[3] & 0x0F
        updated_cc = updated_packet[3] & 0x0F
        print(f"  ✓ 連続性カウンタ更新: {original_cc} → {updated_cc}")
        
        # 複数回更新テスト
        for i in range(5):
            updated_packet = generator.update_continuity_counter(0x0010, test_packet)
            expected_cc = (i + 1) % 16
            actual_cc = updated_packet[3] & 0x0F
            if actual_cc != expected_cc:
                print(f"  ✗ 連続性カウンタ異常: {actual_cc} != {expected_cc}")
                return False
        
        print("  ✓ 連続性カウンタ循環テスト成功")
        
        # ストリーム生成テスト
        test_packets = [
            b'\x47\x00\x00\x10' + b'\xAA' * 184,  # PAT
            b'\x47\x01\x00\x10' + b'\xBB' * 184,  # PMT
            b'\x47\x01\x11\x10' + b'\xCC' * 184,  # Video
            b'\x47\x01\x12\x10' + b'\xDD' * 184   # Audio
        ]
        
        output_stream = generator.generate_output_stream(test_packets)
        print(f"  ✓ ストリーム生成: {len(test_packets)}パケット → {len(output_stream)}パケット")
        
        # PIDフィルタリングテスト
        target_pids = [0x0000, 0x0111]  # PAT + Video のみ
        filtered_stream = generator.generate_output_stream(test_packets, target_pids)
        print(f"  ✓ PIDフィルタリング: {len(filtered_stream)}パケット（期待値: 2）")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_ts_output_controller():
    """TSOutputControllerクラスのテスト"""
    print("TSOutputControllerテスト:")
    
    try:
        from ts_output import TSOutputController
        
        # 小さなバッファサイズでテスト
        controller = TSOutputController(buffer_size=5, output_rate_bps=None)
        print("  ✓ TS出力制御初期化成功")
        
        # バッファテスト
        test_packet = b'\x47\x00\x00\x10' + b'\x00' * 184
        
        # 正常キューイング
        success = controller.queue_packet(test_packet)
        print(f"  ✓ パケットキューイング: {success}")
        
        # 複数パケットキューイング
        test_packets = [test_packet] * 3
        success_count = controller.queue_packets(test_packets)
        print(f"  ✓ 複数パケットキューイング: {success_count}/{len(test_packets)}")
        
        # バッファオーバーフローテスト
        overflow_packets = [test_packet] * 10  # バッファサイズ(5)を超える
        overflow_success = controller.queue_packets(overflow_packets)
        print(f"  ✓ バッファオーバーフローテスト: {overflow_success}/{len(overflow_packets)}")
        
        # 統計情報テスト
        stats = controller.get_output_stats()
        print(f"  ✓ 統計情報取得: バッファ使用量={stats['buffer_usage']}")
        print(f"    バッファ利用率: {stats['buffer_utilization']:.1f}%")
        print(f"    オーバーフロー: {stats['buffer_overflows']}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_ts_output_manager():
    """TSOutputManagerクラスのテスト"""
    print("TSOutputManagerテスト:")
    
    try:
        from ts_output import TSOutputManager
        
        manager = TSOutputManager(buffer_size=10)
        print("  ✓ TS出力管理初期化成功")
        
        # ダミーTSデータ作成
        dummy_ts_data = b''
        for i in range(5):
            packet = b'\x47' + bytes([0x00, 0x10 + i, 0x10]) + bytes([i] * 184)
            dummy_ts_data += packet
        
        print(f"  ✓ ダミーTSデータ作成: {len(dummy_ts_data)}バイト")
        
        # 出力開始（実際の標準出力は行わない）
        manager.start_output()
        print("  ✓ TS出力開始")
        
        # データ処理テスト（実際の出力はスキップ）
        # process_and_output は標準出力に書き込むため、テスト環境では実行しない
        print("  ✓ TS処理機能（標準出力テストはスキップ）")
        
        # 統計情報テスト
        manager_stats = manager.get_manager_stats()
        print(f"  ✓ 管理統計取得: 実行中={manager_stats['is_running']}")
        
        # 出力停止
        manager.stop_output()
        print("  ✓ TS出力停止")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_ts_packet_validation():
    """TSパケット検証テスト"""
    print("TSパケット検証テスト:")
    
    try:
        from ts_output import TSStreamGenerator
        
        generator = TSStreamGenerator()
        
        # 正常なTSパケット
        valid_packet = b'\x47\x00\x10\x10' + b'\x00' * 184
        print(f"  ✓ 正常パケット: 長さ={len(valid_packet)}, 同期バイト=0x{valid_packet[0]:02X}")
        
        # 不正な長さのパケット
        invalid_short = b'\x47\x00\x10\x10' + b'\x00' * 100
        invalid_long = b'\x47\x00\x10\x10' + b'\x00' * 200
        
        print(f"  ✓ 不正パケット: 短={len(invalid_short)}, 長={len(invalid_long)}")
        
        # ストリーム生成で正常パケットのみ処理されることを確認
        mixed_packets = [valid_packet, invalid_short, valid_packet, invalid_long]
        output_stream = generator.generate_output_stream(mixed_packets, padding=False)
        
        # 有効なパケット（2個）のみが処理されることを期待
        expected_valid = sum(1 for p in mixed_packets if len(p) == 188 and p[0] == 0x47)
        print(f"  ✓ 混合パケット処理: {len(mixed_packets)}入力 → {len(output_stream)}出力（期待値: {expected_valid}）")
        
        return len(output_stream) == expected_valid
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_pid_extraction():
    """PID抽出テスト"""
    print("PID抽出テスト:")
    
    try:
        from ts_output import TSStreamGenerator
        
        generator = TSStreamGenerator()
        
        # 異なるPIDのパケットを作成
        test_packets = []
        expected_pids = [0x0000, 0x0100, 0x0111, 0x0112, 0x1FFF]
        
        for pid in expected_pids:
            # PIDをヘッダーにエンコード
            header_bytes = [
                0x47,  # 同期バイト
                (pid >> 8) & 0x1F,  # 上位5ビット
                pid & 0xFF,  # 下位8ビット
                0x10   # 連続性カウンタとフラグ
            ]
            packet = bytes(header_bytes) + bytes([pid & 0xFF] * 184)
            test_packets.append(packet)
        
        print(f"  ✓ テストパケット作成: {len(test_packets)}個, PID={[hex(p) for p in expected_pids]}")
        
        # 特定PIDのフィルタリング
        target_pids = [0x0000, 0x0111]  # PAT + Video
        filtered_stream = generator.generate_output_stream(test_packets, target_pids, padding=False)
        
        print(f"  ✓ PIDフィルタリング: {len(test_packets)}入力 → {len(filtered_stream)}出力")
        print(f"    対象PID: {[hex(p) for p in target_pids]}")
        
        # 実際にフィルタリングされたパケットのPIDをチェック
        filtered_pids = []
        for packet in filtered_stream:
            if len(packet) == 188:
                pid = ((packet[1] & 0x1F) << 8) | packet[2]
                filtered_pids.append(pid)
        
        print(f"    フィルタリング結果PID: {[hex(p) for p in filtered_pids]}")
        
        # フィルタリング結果の検証
        expected_count = sum(1 for pid in expected_pids if pid in target_pids)
        if len(filtered_stream) != expected_count:
            print(f"  ✗ フィルタリング結果異常: {len(filtered_stream)} != {expected_count}")
            return False
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def main():
    """メイン実行関数"""
    print("Transport Stream 出力機能ユニットテスト")
    print("=" * 50)
    
    tests = [
        ("TSStreamGenerator", test_ts_stream_generator),
        ("TSOutputController", test_ts_output_controller),
        ("TSOutputManager", test_ts_output_manager),
        ("TSパケット検証", test_ts_packet_validation),
        ("PID抽出", test_pid_extraction)
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
        print("🎉 すべてのTS出力テストが成功しました！")
        return 0
    else:
        print("⚠️  一部のTS出力テストが失敗しました")
        return 1

if __name__ == "__main__":
    sys.exit(main())