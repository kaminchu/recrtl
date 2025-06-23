#!/usr/bin/env python3
"""
Transport Stream パーサーユニットテスト

TSPacket、PATParser、PMTParser、TSParser クラスのテスト
"""

import sys
import os

# プロジェクトのsrcディレクトリをPythonパスに追加
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

def test_ts_packet():
    """TSPacketクラスのテスト"""
    print("TSPacketテスト:")
    
    try:
        from ts_parser import TSPacket
        
        # 正常なTSパケットの作成
        test_data = b'\x47' + b'\x00\x10\x01' + b'\x00' * 184  # PID=0x0010のパケット
        packet = TSPacket(test_data)
        
        print(f"  ✓ TSパケット作成成功: PID=0x{packet.pid:04X}")
        print(f"  ✓ 同期バイト: 0x{packet.sync_byte:02X}")
        print(f"  ✓ PUSI: {packet.payload_unit_start_indicator}")
        print(f"  ✓ 連続性カウンタ: {packet.continuity_counter}")
        
        # ペイロード取得テスト
        payload = packet.get_payload()
        print(f"  ✓ ペイロード取得: {len(payload)}バイト")
        
        # 不正なパケットサイズテスト
        try:
            invalid_packet = TSPacket(b'\x47' + b'\x00' * 100)  # 短すぎる
            print("  ✗ 不正パケットサイズチェック失敗")
            return False
        except ValueError:
            print("  ✓ 不正パケットサイズチェック成功")
        
        # 不正な同期バイトテスト
        try:
            invalid_sync = TSPacket(b'\x48' + b'\x00' * 187)  # 同期バイト不正
            print("  ✗ 不正同期バイトチェック失敗")
            return False
        except ValueError:
            print("  ✓ 不正同期バイトチェック成功")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_pat_parser():
    """PATParserクラスのテスト"""
    print("PATParserテスト:")
    
    try:
        from ts_parser import PATParser, TSPacket
        
        parser = PATParser()
        print("  ✓ PATパーサー初期化成功")
        
        # PAT パケットの作成（簡略版）
        # 同期バイト + ヘッダー (PID=0x0000, PUSI=1) + ペイロード
        pat_header = b'\x47\x40\x00\x10'  # PID=0x0000, PUSI=1, CC=0
        pat_payload = (
            b'\x00'        # ポインターフィールド
            b'\x00'        # テーブルID (PAT)
            b'\x80\x0D'    # セクション長=13
            b'\x00\x01'    # トランスポートストリームID
            b'\xC1'        # バージョン=0, current=1
            b'\x00\x00'    # セクション番号
            b'\x00\x01'    # プログラム番号=1
            b'\xE1\x00'    # PMT PID=0x0100
            b'\x00\x00\x00\x00'  # CRC32 (ダミー)
        )
        
        # パディング
        padding_size = 184 - len(pat_payload)
        pat_data = pat_header + pat_payload + b'\xFF' * padding_size
        
        # TSパケット作成
        pat_packet = TSPacket(pat_data)
        print(f"  ✓ PATパケット作成: PID=0x{pat_packet.pid:04X}")
        
        # PAT解析
        result = parser.parse(pat_packet)
        print(f"  ✓ PAT解析結果: {result}")
        
        # プログラム情報取得
        programs = parser.get_programs()
        print(f"  ✓ 発見プログラム数: {len(programs)}")
        
        for prog_num, pmt_pid in programs.items():
            print(f"    Program {prog_num}: PMT PID=0x{pmt_pid:04X}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_pmt_parser():
    """PMTParserクラスのテスト"""
    print("PMTParserテスト:")
    
    try:
        from ts_parser import PMTParser, TSPacket
        
        pmt_pid = 0x0100
        parser = PMTParser(pmt_pid)
        print(f"  ✓ PMTパーサー初期化: PID=0x{pmt_pid:04X}")
        
        # PMT パケットの作成（簡略版）
        pmt_header = b'\x47\x41\x00\x10'  # PID=0x0100, PUSI=1, CC=0
        pmt_payload = (
            b'\x00'        # ポインターフィールド
            b'\x02'        # テーブルID (PMT)
            b'\x80\x17'    # セクション長=23
            b'\x00\x01'    # プログラム番号=1
            b'\xC1'        # バージョン=0, current=1
            b'\x00\x00'    # セクション番号
            b'\xE1\x11'    # PCR PID=0x0111
            b'\xF0\x00'    # プログラム情報長=0
            # ストリーム情報
            b'\x02'        # ストリームタイプ (MPEG-2 Video)
            b'\xE1\x11'    # Elementary PID=0x0111
            b'\xF0\x00'    # ES情報長=0
            b'\x04'        # ストリームタイプ (MPEG-2 Audio)
            b'\xE1\x12'    # Elementary PID=0x0112
            b'\xF0\x00'    # ES情報長=0
            b'\x00\x00\x00\x00'  # CRC32 (ダミー)
        )
        
        # パディング
        padding_size = 184 - len(pmt_payload)
        pmt_data = pmt_header + pmt_payload + b'\xFF' * padding_size
        
        # TSパケット作成
        pmt_packet = TSPacket(pmt_data)
        print(f"  ✓ PMTパケット作成: PID=0x{pmt_packet.pid:04X}")
        
        # PMT解析
        result = parser.parse(pmt_packet)
        print(f"  ✓ PMT解析結果: {result}")
        
        # ストリーム情報取得
        video_pids = parser.get_video_pids()
        audio_pids = parser.get_audio_pids()
        all_streams = parser.get_all_stream_pids()
        
        print(f"  ✓ ビデオPID数: {len(video_pids)}")
        print(f"  ✓ オーディオPID数: {len(audio_pids)}")
        print(f"  ✓ 全ストリーム数: {len(all_streams)}")
        
        for pid in video_pids:
            print(f"    ビデオ: PID=0x{pid:04X}")
        
        for pid in audio_pids:
            print(f"    オーディオ: PID=0x{pid:04X}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_ts_parser_integration():
    """TSParserクラス統合テスト"""
    print("TSParser統合テスト:")
    
    try:
        from ts_parser import TSParser, TSPacket
        
        parser = TSParser()
        print("  ✓ TSパーサー初期化成功")
        
        # テストデータ作成（PAT + PMT パケット）
        # PAT パケット
        pat_header = b'\x47\x40\x00\x10'
        pat_payload = (
            b'\x00\x00\x80\x0D\x00\x01\xC1\x00\x00'
            b'\x00\x01\xE1\x00'
            b'\x00\x00\x00\x00'
        )
        pat_data = pat_header + pat_payload + b'\xFF' * (184 - len(pat_payload))
        
        # PMT パケット
        pmt_header = b'\x47\x41\x00\x10'
        pmt_payload = (
            b'\x00\x02\x80\x17\x00\x01\xC1\x00\x00'
            b'\xE1\x11\xF0\x00'
            b'\x02\xE1\x11\xF0\x00'
            b'\x04\xE1\x12\xF0\x00'
            b'\x00\x00\x00\x00'
        )
        pmt_data = pmt_header + pmt_payload + b'\xFF' * (184 - len(pmt_payload))
        
        # テストデータの解析
        test_data = pat_data + pmt_data
        packets = parser.parse_data(test_data)
        
        print(f"  ✓ 解析パケット数: {len(packets)}")
        
        # ストリーム情報取得
        stream_info = parser.get_stream_info()
        print(f"  ✓ 発見プログラム数: {len(stream_info)}")
        
        for program_num, info in stream_info.items():
            print(f"    Program {program_num}:")
            print(f"      ビデオPID: {[f'0x{pid:04X}' for pid in info['video_pids']]}")
            print(f"      オーディオPID: {[f'0x{pid:04X}' for pid in info['audio_pids']]}")
            print(f"      PCR PID: 0x{info['pcr_pid']:04X}")
        
        # 統計情報取得
        stats = parser.get_parser_stats()
        print(f"  ✓ パーサー統計: {stats['programs_found']}プログラム, {stats['pmt_parsers']}PMT")
        
        return True
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def test_sync_detection():
    """同期バイト検出テスト"""
    print("同期バイト検出テスト:")
    
    try:
        from ts_parser import TSParser
        
        parser = TSParser()
        
        # 正常な同期パターン
        normal_data = b'\x47' + b'\x00' * 187 + b'\x47' + b'\x01' * 187
        sync_pos = parser.find_sync_byte(normal_data)
        print(f"  ✓ 正常同期検出: 位置={sync_pos}")
        
        # ノイズ付きデータ
        noisy_data = b'\xFF' * 10 + b'\x47' + b'\x02' * 187 + b'\x47' + b'\x03' * 187
        sync_pos_noisy = parser.find_sync_byte(noisy_data)
        print(f"  ✓ ノイズ付き同期検出: 位置={sync_pos_noisy}")
        
        # 同期バイトなし
        no_sync_data = b'\xFF' * 400
        sync_pos_none = parser.find_sync_byte(no_sync_data)
        print(f"  ✓ 同期なし検出: 位置={sync_pos_none}")
        
        return sync_pos == 0 and sync_pos_noisy == 10 and sync_pos_none == -1
        
    except Exception as e:
        print(f"  ✗ エラー: {e}")
        return False

def main():
    """メイン実行関数"""
    print("Transport Stream パーサーユニットテスト")
    print("=" * 50)
    
    tests = [
        ("TSPacket", test_ts_packet),
        ("PATParser", test_pat_parser),
        ("PMTParser", test_pmt_parser),
        ("TSParser統合", test_ts_parser_integration),
        ("同期バイト検出", test_sync_detection)
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
        print("🎉 すべてのTSパーサーテストが成功しました！")
        return 0
    else:
        print("⚠️  一部のTSパーサーテストが失敗しました")
        return 1

if __name__ == "__main__":
    sys.exit(main())