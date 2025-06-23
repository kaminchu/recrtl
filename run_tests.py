#!/usr/bin/env python3
"""
ワンセグCLI テストランナー

プロジェクト内の全テストを実行する統合テストランナー
"""

import sys
import os
import subprocess
import time

def run_test_suite(test_path, test_name):
    """
    指定されたテストスイートを実行
    
    Args:
        test_path: テストファイルのパス
        test_name: テスト名（表示用）
        
    Returns:
        bool: テスト成功時True
    """
    print(f"\n{'='*60}")
    print(f"実行中: {test_name}")
    print(f"ファイル: {test_path}")
    print('='*60)
    
    try:
        start_time = time.time()
        result = subprocess.run([sys.executable, test_path], 
                              capture_output=True, text=True, timeout=30)
        end_time = time.time()
        
        print(f"実行時間: {end_time - start_time:.2f}秒")
        
        if result.returncode == 0:
            print("✓ テスト成功")
            if result.stdout:
                # 成功時は要約のみ表示
                lines = result.stdout.strip().split('\n')
                summary_lines = [line for line in lines if '成功率' in line or '🎉' in line or 'テスト結果' in line]
                for line in summary_lines:
                    print(f"  {line}")
            return True
        else:
            print("✗ テスト失敗")
            if result.stdout:
                print("STDOUT:")
                print(result.stdout)
            if result.stderr:
                print("STDERR:")
                print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print("✗ テストタイムアウト（30秒）")
        return False
    except Exception as e:
        print(f"✗ テスト実行エラー: {e}")
        return False

def main():
    """メイン実行関数"""
    print("ワンセグCLI テストスイート実行")
    print(f"実行時刻: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # テスト定義（カテゴリ別）
    test_suites = [
        # Unit Tests
        ("tests/unit/test_isdb_basic.py", "Unit: ISDB基本機能テスト"),
        ("tests/unit/test_mode3_basic.py", "Unit: Mode3基本機能テスト"),
        ("tests/unit/test_error_correction.py", "Unit: エラー訂正機能テスト"),
        ("tests/unit/test_ts_parser.py", "Unit: Transport Streamパーサーテスト"),
        ("tests/unit/test_ts_output.py", "Unit: Transport Stream出力テスト"),
        
        # Integration Tests  
        ("tests/integration/test_isdb_pipeline.py", "Integration: ISDB信号処理パイプライン"),
        ("tests/integration/test_ofdm_pipeline.py", "Integration: OFDM復調パイプライン"),
        
        # System Tests
        ("tests/system/test_mode3_system.py", "System: Mode3完全システム"),
    ]
    
    # 存在するテストのみを実行
    available_tests = []
    for test_path, test_name in test_suites:
        if os.path.exists(test_path):
            available_tests.append((test_path, test_name))
        else:
            print(f"⚠️  テストファイルが見つかりません: {test_path}")
    
    if not available_tests:
        print("❌ 実行可能なテストが見つかりませんでした")
        return 1
    
    print(f"\n発見されたテスト: {len(available_tests)}個")
    
    # 各テストスイートを実行
    results = []
    for test_path, test_name in available_tests:
        success = run_test_suite(test_path, test_name)
        results.append((test_name, success))
    
    # 最終結果サマリー
    print(f"\n{'='*60}")
    print("最終テスト結果サマリー")
    print('='*60)
    
    success_count = 0
    for test_name, success in results:
        status = "✓ 成功" if success else "✗ 失敗"
        print(f"{status}: {test_name}")
        if success:
            success_count += 1
    
    total_count = len(results)
    success_rate = (success_count / total_count) * 100 if total_count > 0 else 0
    
    print(f"\n全体成功率: {success_count}/{total_count} ({success_rate:.1f}%)")
    
    if success_count == total_count:
        print("🎉 すべてのテストが成功しました！")
        return 0
    else:
        print("⚠️  一部のテストが失敗しました")
        return 1

if __name__ == "__main__":
    sys.exit(main())