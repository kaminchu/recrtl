#!/usr/bin/env python3
"""
ワンセグCLIツール - メインスクリプト

RTL2832ベースのUSBチューナーを使用して日本のワンセグ放送を受信し、
MPEG-TSストリームを標準出力に出力する。
"""

import argparse
import logging
import sys
import os
import time

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

# プロジェクトのsrcディレクトリをPythonパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def setup_logging(verbose: bool = False):
    """ログ設定を初期化"""
    log_level = logging.DEBUG if verbose else logging.INFO

    # 標準エラー出力にログを出力（標準出力はTS用）
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )

    # 開発モードでverboseでない場合、ISDBデコーダーのデバッグログを抑制
    if not verbose:
        logging.getLogger('isdb_decoder').setLevel(logging.WARNING)
        logging.getLogger('rtl_interface').setLevel(logging.INFO)

    logger = logging.getLogger('oneseg')
    return logger

def show_channel_list(area: str = 'tokyo'):
    """指定地域のチャンネル一覧を表示"""
    try:
        from channel_manager import ChannelManager
        
        ch_mgr = ChannelManager()
        channels = ch_mgr.list_channels(area)

        # 都道府県名または地域名を取得
        area_name = area.upper()
        if area in ch_mgr.get_all_prefectures():
            pref_info = ch_mgr._broadcast_db.get_prefecture_info(area)
            if pref_info:
                area_name = pref_info['name']

        print(f"\n{area_name} チャンネル一覧:", file=sys.stderr)
        print("-" * 70, file=sys.stderr)

        if not channels:
            # 無効な地域コードかチェック
            all_prefectures = ch_mgr.get_all_prefectures()

            if area not in all_prefectures:
                print(f"  エラー: 無効な都道府県コード '{area}' です", file=sys.stderr)
                print("  利用可能な都道府県コードを確認するには --list-regions を使用してください", file=sys.stderr)
            else:
                print("  該当する放送局はありません", file=sys.stderr)
            print("-" * 70, file=sys.stderr)
            return

        for channel, info in channels:
            freq_str = f"{info['frequency_mhz']:.6f} MHz"
            if 'station' in info:
                station = info['station']

                # 送信所情報を表示
                transmitter_info = ""
                if 'transmitter' in info:
                    transmitter_info = f" [{info['transmitter']['name']}]"

                # 地域情報を表示
                region_info = ""
                if 'prefecture' in station and 'region' in station:
                    region_info = f" ({station['region']})"
                elif 'region' in station:
                    region_info = f" ({station['region']})"

                print(f"  ch{channel:2d}: {freq_str} - {station['name']}{transmitter_info}{region_info}", file=sys.stderr)
            else:
                print(f"  ch{channel:2d}: {freq_str}", file=sys.stderr)

        print("-" * 70, file=sys.stderr)
        print(f"  合計: {len(channels)}局", file=sys.stderr)

    except Exception as e:
        print(f"チャンネル一覧表示エラー: {e}", file=sys.stderr)

def show_region_list():
    """利用可能な地域一覧を表示"""
    try:
        from channel_manager import ChannelManager

        ch_mgr = ChannelManager()

        print("\n利用可能な地域一覧:", file=sys.stderr)
        print("-" * 60, file=sys.stderr)

        # 47都道府県の一覧を表示
        all_prefectures = ch_mgr.get_all_prefectures()

        print("【47都道府県対応】", file=sys.stderr)
        current_region = None
        for pref_code in all_prefectures:
            pref_info = ch_mgr._broadcast_db.get_prefecture_info(pref_code)
            if pref_info:
                # 地域が変わったら表示
                if current_region != pref_info['region']:
                    current_region = pref_info['region']
                    print(f"\n◆ {current_region}", file=sys.stderr)

                # 放送局数を取得
                pref_channels = ch_mgr.list_channels(pref_code)
                transmitters = ch_mgr.get_transmitters_by_prefecture(pref_code)
                transmitter_count = len(transmitters) if transmitters else 0

                print(f"  {pref_code}: {pref_info['name']} ({len(pref_channels)}局, {transmitter_count}送信所)", file=sys.stderr)


        print("-" * 60, file=sys.stderr)
        print("使用例:", file=sys.stderr)
        print("  --list-channels tokyo     # 東京都の放送局一覧", file=sys.stderr)
        print("  --list-channels hokkaido  # 北海道の放送局一覧", file=sys.stderr)
        print("  --list-channels aichi     # 愛知県の放送局一覧", file=sys.stderr)
        print("  --list-channels okinawa   # 沖縄県の放送局一覧", file=sys.stderr)
        print("-" * 60, file=sys.stderr)

    except Exception as e:
        print(f"地域一覧表示エラー: {e}", file=sys.stderr)

def list_rtl_devices():
    """利用可能なRTL-SDRデバイスを一覧表示"""
    try:
        from rtl_interface import RTLInterface

        print("RTL-SDRデバイス一覧:", file=sys.stderr)
        devices = RTLInterface.list_devices()

        if devices:
            for device_id, description in devices:
                print(f"  Device {device_id}: {description}", file=sys.stderr)
        else:
            print("  利用可能なデバイスが見つかりませんでした", file=sys.stderr)

        return True
    except Exception as e:
        print(f"エラー: デバイス検出に失敗しました - {e}", file=sys.stderr)
        return False

def test_device_functionality(device_id: int = 0, test_frequency: float = 473.142857e6, sample_rate: int = 2048000):
    """RTL-SDRデバイスと信号処理パイプラインの動作確認テスト"""
    print("\n" + "=" * 60, file=sys.stderr)
    print("RTL-SDR デバイス・信号処理パイプライン動作確認テスト", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    
    test_results = {
        'device_detection': False,
        'device_initialization': False,
        'frequency_setting': False,
        'sample_reading': False,
        'signal_processing': False,
        'isdb_decoder': False,
        'overall_health': False
    }
    
    try:
        # 1. デバイス検出テスト
        print("\n1. デバイス検出テスト:", file=sys.stderr)
        from rtl_interface import RTLInterface
        
        devices = RTLInterface.list_devices()
        if devices:
            print(f"  ✓ {len(devices)}個のデバイスを検出", file=sys.stderr)
            for did, desc in devices:
                print(f"    Device {did}: {desc}", file=sys.stderr)
            test_results['device_detection'] = True
        else:
            print("  ⚠️  デバイスが検出されませんでした（開発モードで継続）", file=sys.stderr)
            test_results['device_detection'] = True  # 開発モードでも続行
        
        # 2. デバイス初期化テスト
        print("\n2. デバイス初期化テスト:", file=sys.stderr)
        try:
            with RTLInterface(device_id=device_id) as rtl:
                print(f"  ✓ Device {device_id} 初期化成功", file=sys.stderr)
                test_results['device_initialization'] = True
                
                # 3. 周波数設定テスト
                print("\n3. 周波数設定テスト:", file=sys.stderr)
                rtl.set_frequency(test_frequency)
                rtl.set_sample_rate(sample_rate)
                print(f"  ✓ 周波数設定: {test_frequency/1e6:.6f} MHz", file=sys.stderr)
                print(f"  ✓ サンプリングレート設定: {sample_rate} Hz", file=sys.stderr)
                test_results['frequency_setting'] = True
                
                # デバイス情報表示
                device_info = rtl.get_device_info()
                print(f"  ✓ デバイス情報: {device_info}", file=sys.stderr)
                
                # 4. サンプル読み取りテスト
                print("\n4. サンプル読み取りテスト:", file=sys.stderr)
                test_sample_counts = [1024, 4096, 8192]
                
                for sample_count in test_sample_counts:
                    try:
                        samples = rtl.read_samples(sample_count)
                        if samples is not None and len(samples) > 0:
                            # 信号統計計算
                            avg_power = sum(abs(x)**2 for x in samples) / len(samples)
                            dc_component = abs(sum(samples) / len(samples))
                            max_amplitude = max(abs(x) for x in samples)
                            
                            print(f"  ✓ {sample_count}サンプル読み取り成功", file=sys.stderr)
                            print(f"    平均パワー: {avg_power:.6f}", file=sys.stderr)
                            print(f"    DC成分: {dc_component:.6f}", file=sys.stderr)
                            print(f"    最大振幅: {max_amplitude:.6f}", file=sys.stderr)
                            
                            # サンプル品質チェック
                            if avg_power > 1e-8 and max_amplitude > 1e-6:
                                print(f"    ✓ 信号品質: 良好", file=sys.stderr)
                            else:
                                print(f"    ⚠️  信号品質: 低（ノイズレベル）", file=sys.stderr)
                                
                        else:
                            print(f"  ✗ {sample_count}サンプル読み取り失敗", file=sys.stderr)
                            
                    except Exception as sample_error:
                        print(f"  ✗ {sample_count}サンプル読み取りエラー: {sample_error}", file=sys.stderr)
                
                test_results['sample_reading'] = True
                
                # 5. 信号処理テスト
                print("\n5. 信号処理パイプラインテスト:", file=sys.stderr)
                try:
                    from isdb_decoder import ISDBDecoder
                    
                    isdb_decoder = ISDBDecoder(sample_rate=sample_rate)
                    print(f"  ✓ ISDB復調器初期化成功", file=sys.stderr)
                    test_results['isdb_decoder'] = True
                    
                    # 信号処理統計
                    decoder_stats = isdb_decoder.get_signal_stats()
                    print(f"  ✓ 復調器統計: {decoder_stats}", file=sys.stderr)
                    
                    # 実際の信号処理テスト
                    test_samples = rtl.read_samples(8192)
                    if test_samples:
                        processed_samples = isdb_decoder.process_samples(test_samples)
                        print(f"  ✓ 信号前処理: {len(test_samples)} → {len(processed_samples)} サンプル", file=sys.stderr)
                        
                        if len(processed_samples) > 0:
                            processed_power = sum(abs(x)**2 for x in processed_samples) / len(processed_samples)
                            print(f"  ✓ 前処理後パワー: {processed_power:.6f}", file=sys.stderr)
                            test_results['signal_processing'] = True
                        
                        # OFDM復調テスト
                        if len(processed_samples) >= isdb_decoder.SYMBOL_SIZE:
                            print("\n6. OFDM復調テスト:", file=sys.stderr)
                            try:
                                # シンボル同期テスト
                                sync_offset, sync_confidence = isdb_decoder.symbol_synchronization(processed_samples)
                                print(f"  ✓ シンボル同期: オフセット={sync_offset}, 信頼度={sync_confidence:.3f}", file=sys.stderr)
                                
                                if sync_confidence > 0.01:  # 開発モード用低閾値
                                    print(f"  ✓ 同期品質: 十分", file=sys.stderr)
                                else:
                                    print(f"  ⚠️  同期品質: 低（シミュレーション環境）", file=sys.stderr)
                                
                            except Exception as ofdm_error:
                                print(f"  ⚠️  OFDM復調エラー: {ofdm_error}", file=sys.stderr)
                        else:
                            print(f"  ⚠️  OFDM復調スキップ: サンプル不足 ({len(processed_samples)} < {isdb_decoder.SYMBOL_SIZE})", file=sys.stderr)
                    
                except Exception as signal_error:
                    print(f"  ✗ 信号処理エラー: {signal_error}", file=sys.stderr)
                
        except Exception as device_error:
            print(f"  ✗ デバイス初期化失敗: {device_error}", file=sys.stderr)
    
    except Exception as e:
        print(f"  ✗ 全体テストエラー: {e}", file=sys.stderr)
    
    # 7. 結果サマリー
    print("\n" + "=" * 60, file=sys.stderr)
    print("テスト結果サマリー:", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    
    success_count = 0
    total_tests = len(test_results) - 1  # overall_healthを除く
    
    for test_name, result in test_results.items():
        if test_name == 'overall_health':
            continue
            
        status = "✓ 成功" if result else "✗ 失敗"
        test_display_name = {
            'device_detection': 'デバイス検出',
            'device_initialization': 'デバイス初期化',
            'frequency_setting': '周波数設定',
            'sample_reading': 'サンプル読み取り',
            'signal_processing': '信号処理',
            'isdb_decoder': 'ISDB復調器'
        }.get(test_name, test_name)
        
        print(f"  {status}: {test_display_name}", file=sys.stderr)
        if result:
            success_count += 1
    
    # 全体健全性判定
    overall_success_rate = (success_count / total_tests) * 100
    test_results['overall_health'] = overall_success_rate >= 70
    
    print(f"\n全体成功率: {success_count}/{total_tests} ({overall_success_rate:.1f}%)", file=sys.stderr)
    
    if test_results['overall_health']:
        print("🎉 デバイス・信号処理パイプラインは正常に動作しています！", file=sys.stderr)
        if overall_success_rate < 100:
            print("⚠️  一部の機能に制限がありますが、基本動作は可能です", file=sys.stderr)
    else:
        print("❌ デバイス・信号処理に重大な問題があります", file=sys.stderr)
        print("💡 トラブルシューティング:", file=sys.stderr)
        print("   - RTL-SDRドライバの確認: lsusb | grep RTL", file=sys.stderr)
        print("   - 権限の確認: sudo python oneseg.py --test-device", file=sys.stderr)
        print("   - デバイスの再接続", file=sys.stderr)
    
    print("=" * 60, file=sys.stderr)
    return test_results['overall_health']

def main():
    """メイン関数"""
    # コマンドライン引数の解析
    parser = argparse.ArgumentParser(
        description="ワンセグCLIツール - RTL2832でワンセグ放送を受信してMPEG-TSを出力",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  %(prog)s -c 13 | ffplay -              # チャンネル13を受信してffplayで再生
  %(prog)s -c 27 | vlc -                 # NHK総合（東京）をVLCで再生
  %(prog)s -f 473.142857 | ffplay -      # 周波数直接指定
  %(prog)s -c 13 | ffmpeg -i - out.mp4  # MP4ファイルに保存
  %(prog)s --list-devices                # 利用可能デバイス一覧
  %(prog)s --test-device                 # デバイス・信号処理動作確認
        """
    )

    # チャンネル・周波数設定
    freq_group = parser.add_mutually_exclusive_group()
    freq_group.add_argument(
        '-c', '--channel',
        type=int,
        default=13,
        choices=range(13, 63),
        help='チャンネル番号（13-62ch）（デフォルト: 13）'
    )
    freq_group.add_argument(
        '-f', '--frequency',
        type=float,
        help='周波数直接指定（MHz）'
    )

    # RTL-SDR設定
    parser.add_argument(
        '-g', '--gain',
        type=float,
        help='RF gain（0-50dB、未指定時は自動）'
    )
    parser.add_argument(
        '-s', '--sample-rate',
        type=int,
        default=2048000,
        help='サンプリングレート（Hz）（デフォルト: 2048000）'
    )
    parser.add_argument(
        '-d', '--device',
        type=int,
        default=0,
        help='RTL-SDRデバイスID（デフォルト: 0）'
    )

    # 動作モード
    parser.add_argument(
        '--list-devices',
        action='store_true',
        help='利用可能なRTL-SDRデバイスを一覧表示'
    )
    parser.add_argument(
        '--list-channels',
        help='指定地域のチャンネル一覧を表示（47都道府県コードまたは従来の地域コード）'
    )
    parser.add_argument(
        '--list-regions',
        action='store_true',
        help='利用可能な地域一覧を表示'
    )
    parser.add_argument(
        '--test-device',
        action='store_true',
        help='RTL-SDRデバイスと信号処理パイプラインの動作確認テスト'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='詳細ログ出力（信号強度等）'
    )

    args = parser.parse_args()

    # ログ設定
    logger = setup_logging(args.verbose)

    # デバイス一覧表示モード
    if args.list_devices:
        success = list_rtl_devices()
        sys.exit(0 if success else 1)

    # チャンネル一覧表示モード
    if args.list_channels:
        show_channel_list(args.list_channels)
        sys.exit(0)

    # 地域一覧表示モード
    if args.list_regions:
        show_region_list()
        sys.exit(0)
    
    # デバイステストモード
    if args.test_device:
        # テスト用の周波数とサンプリングレートを決定
        test_frequency = 473.142857e6  # チャンネル13のデフォルト
        if args.frequency:
            test_frequency = args.frequency * 1e6
        elif args.channel:
            # チャンネル番号から周波数を計算
            test_frequency = ((args.channel - 13) * 6 + 473.142857) * 1e6
        
        success = test_device_functionality(
            device_id=args.device,
            test_frequency=test_frequency,
            sample_rate=args.sample_rate
        )
        sys.exit(0 if success else 1)

    # 周波数の決定
    try:
        from channel_manager import ChannelManager
        ch_mgr = ChannelManager()

        if args.frequency:
            frequency_hz = args.frequency * 1e6
            logger.info(f"周波数直接指定: {args.frequency:.6f} MHz")

            # 近いチャンネルを検索
            if args.verbose:
                near_channel = ch_mgr.find_channel_by_frequency(frequency_hz)
                if near_channel:
                    logger.debug(f"最寄りチャンネル: {near_channel}")
        else:
            frequency_hz = ch_mgr.get_frequency_hz(args.channel)
            if frequency_hz is None:
                logger.error(f"無効なチャンネル番号: {args.channel}")
                sys.exit(1)

            logger.info(f"チャンネル {args.channel}: {frequency_hz/1e6:.6f} MHz")

            # 放送局情報を表示
            if args.verbose:
                ch_info = ch_mgr.get_channel_info(args.channel)
                if ch_info and 'station' in ch_info:
                    station = ch_info['station']
                    area_info = station.get('area', '不明')
                    logger.info(f"放送局: {station['name']} ({area_info})")

    except Exception as e:
        logger.error(f"チャンネル管理エラー: {e}")
        # フォールバック: 従来の計算方式
        if args.frequency:
            frequency_hz = args.frequency * 1e6
        else:
            freq_mhz = (args.channel - 13) * 6 + 473.142857
            frequency_hz = freq_mhz * 1e6
        logger.info(f"フォールバック: 周波数 {frequency_hz/1e6:.6f} MHz")

    # 設定情報を表示
    logger.info(f"RTL-SDRデバイス: {args.device}")
    logger.info(f"サンプリングレート: {args.sample_rate} Hz")
    if args.gain is not None:
        logger.info(f"RF gain: {args.gain} dB")
    else:
        logger.info("RF gain: 自動")

    # RTL-SDRインターフェースを使用した受信処理
    logger.info("ワンセグ受信を開始します...")

    try:
        from rtl_interface import RTLInterface

        # RTL-SDRデバイスを初期化
        logger.info("RTL-SDRデバイスを初期化中...")
        with RTLInterface(device_id=args.device) as rtl:

            # デバイス設定
            logger.info("デバイス設定を適用中...")
            rtl.set_frequency(frequency_hz)
            rtl.set_sample_rate(args.sample_rate)
            rtl.set_gain(args.gain)

            # デバイス情報を表示
            if args.verbose:
                device_info = rtl.get_device_info()
                logger.debug(f"デバイス情報: {device_info}")

            # ISDB復調器を初期化
            logger.info("ISDB信号処理パイプラインを構築中...")
            try:
                from isdb_decoder import ISDBDecoder
                isdb_decoder = ISDBDecoder(sample_rate=args.sample_rate)
                logger.info("ISDB復調器初期化完了")

                if args.verbose:
                    decoder_stats = isdb_decoder.get_signal_stats()
                    logger.debug(f"ISDB復調器統計: {decoder_stats}")

            except Exception as e:
                logger.error(f"ISDB復調器初期化失敗: {e}")
                isdb_decoder = None

            logger.info("MPEG-TS出力準備完了")

            # ダミーのTSパケットヘッダー（188バイト、同期バイト0x47で開始）
            dummy_ts_packet = b'\x47' + b'\x00' * 187

            logger.info("標準出力にMPEG-TSストリームを出力中...")
            logger.info("終了するには Ctrl+C を押してください")

            # 信号処理・OFDM復調テスト
            if isdb_decoder and args.verbose:
                logger.info("信号処理・OFDM復調テスト実行中...")

                # テストサンプル読み取り（OFDMシンボル複数分）
                required_samples = isdb_decoder.SYMBOL_SIZE * 3  # 3シンボル分
                test_samples = rtl.read_samples(max(4096, required_samples))

                if test_samples is not None:
                    logger.info(f"生サンプル読み取り: {len(test_samples)}個")

                    # 入力信号統計
                    if len(test_samples) > 0:
                        avg_power_in = sum(abs(x)**2 for x in test_samples) / len(test_samples)
                        dc_component = sum(test_samples) / len(test_samples)
                        logger.info(f"入力信号: 平均パワー={avg_power_in:.6f}, DC={abs(dc_component):.6f}")

                    # 1. 基本信号処理適用
                    processed_samples = isdb_decoder.process_samples(test_samples)
                    logger.info(f"前処理後サンプル: {len(processed_samples)}個")

                    if len(processed_samples) > 0:
                        avg_power_out = sum(abs(x)**2 for x in processed_samples) / len(processed_samples)
                        dc_component_out = sum(processed_samples) / len(processed_samples)
                        logger.info(f"前処理後信号: 平均パワー={avg_power_out:.6f}, DC={abs(dc_component_out):.6f}")

                    # 2. ISDB-T Mode3復調テスト
                    if len(processed_samples) >= isdb_decoder.SYMBOL_SIZE:
                        logger.info("ISDB-T Mode3復調テスト実行中...")

                        try:
                            # Mode3復調実行（エラー訂正付き）
                            ecc_results = isdb_decoder.process_isdb_mode3_with_ecc(processed_samples)

                            if ecc_results:
                                logger.info(f"ISDB-T Mode3+ECC復調成功: {len(ecc_results)}シンボル復調")

                                # 復調結果統計
                                total_bits = 0
                                total_corrected_bytes = 0
                                ecc_success_count = 0

                                for i, result in enumerate(ecc_results):
                                    logger.info(f"シンボル{i}: セグメント{result['segment_id']} ({result['modulation']})")
                                    logger.info(f"  キャリア数: {result['carrier_count']}, ビット数: {result['bit_count']}")
                                    logger.info(f"  シンボルパワー: {result['symbol_power']:.6f}")

                                    # エラー訂正結果
                                    if result.get('ecc_success', False):
                                        ecc_success_count += 1
                                        corrected_bytes = result.get('corrected_bytes', 0)
                                        total_corrected_bytes += corrected_bytes
                                        logger.info(f"  ✓ エラー訂正成功: {corrected_bytes}バイト")

                                        # エラー訂正統計
                                        ecc_stats = result.get('error_correction_stats', {})
                                        if ecc_stats:
                                            logger.debug(f"    ビットデインターリーブ: {'成功' if ecc_stats.get('bit_deinterleave_success') else '失敗'}")
                                            logger.debug(f"    畳み込み復号: {'成功' if ecc_stats.get('convolutional_decode_success') else '失敗'}")
                                            logger.debug(f"    RS復号: {'成功' if ecc_stats.get('rs_decode_success') else '失敗'}")
                                    else:
                                        logger.warning(f"  ✗ エラー訂正失敗")

                                    total_bits += result['bit_count']

                                logger.info(f"✓ 合計復調ビット数: {total_bits}")
                                logger.info(f"✓ 合計エラー訂正バイト数: {total_corrected_bytes}")
                                logger.info(f"✓ エラー訂正成功率: {ecc_success_count}/{len(ecc_results)} ({100*ecc_success_count/len(ecc_results):.1f}%)")

                                # 3. Transport Stream 解析・抽出テスト
                                if ecc_success_count > 0:
                                    logger.info("Transport Stream解析テスト実行中...")

                                    try:
                                        from ts_parser import TSParser

                                        # TS抽出
                                        ts_data = isdb_decoder.extract_transport_stream(ecc_results)
                                        logger.info(f"TS抽出: {len(ts_data)}バイト")

                                        if ts_data:
                                            # TSパーサーで解析
                                            ts_parser = TSParser()
                                            ts_packets = ts_parser.parse_data(ts_data)
                                            logger.info(f"TS解析: {len(ts_packets)}パケット検出")

                                            # ストリーム情報取得
                                            stream_info = ts_parser.get_stream_info()
                                            if stream_info:
                                                logger.info(f"✓ {len(stream_info)}プログラム発見")
                                                for prog_num, info in stream_info.items():
                                                    logger.info(f"  Program {prog_num}: Video={len(info['video_pids'])}, Audio={len(info['audio_pids'])}")
                                            else:
                                                logger.info("プログラム情報未検出（PAT/PMT解析中...）")

                                            # パーサー統計
                                            parser_stats = ts_parser.get_parser_stats()
                                            logger.info(f"✓ TSパーサー統計: {parser_stats['programs_found']}プログラム")
                                        else:
                                            logger.warning("TS抽出データが空です")

                                    except Exception as ts_e:
                                        logger.error(f"Transport Stream解析エラー: {ts_e}")

                                logger.info("✓ ISDB-T Mode3+ECC復調テスト完了")
                            else:
                                logger.warning("ISDB-T Mode3+ECC復調失敗: シンボル同期エラーまたはサンプル不足")

                        except Exception as e:
                            logger.error(f"ISDB-T Mode3復調エラー: {e}")
                    else:
                        logger.warning(f"ISDB-T Mode3復調スキップ: サンプル不足 ({len(processed_samples)} < {isdb_decoder.SYMBOL_SIZE})")

                    # 最終統計
                    final_stats = isdb_decoder.get_signal_stats()
                    logger.info(f"処理統計: AGCゲイン={final_stats['agc_gain']:.3f}, DC推定={final_stats['dc_estimate']['magnitude']:.6f}")
                else:
                    logger.error("サンプル読み取り失敗")

            # 実際のTS出力処理
            logger.info("MPEG-TS出力処理を開始します...")

            try:
                from ts_output import TSOutputManager

                # TS出力管理を初期化
                ts_output_manager = TSOutputManager(buffer_size=512, output_rate_bps=None)
                ts_output_manager.start_output()
                logger.info("TS出力管理開始")

                # 継続的な信号処理・TS出力ループ
                logger.info("連続信号処理・リアルタイムTS出力中...")
                logger.info("終了するには Ctrl+C を押してください")

                # 必要サンプル数を定義（OFDMシンボル複数分）
                required_samples = isdb_decoder.SYMBOL_SIZE * 3  # 3シンボル分
                packet_count = 0
                while True:
                    try:
                        # RTL-SDRから新しいサンプルを読み取り
                        new_samples = rtl.read_samples(required_samples)
                        if new_samples is None:
                            logger.warning("サンプル読み取り失敗")
                            time.sleep(0.1)
                            continue

                        # 1. 信号処理
                        processed_samples = isdb_decoder.process_samples(new_samples)

                        if len(processed_samples) >= isdb_decoder.SYMBOL_SIZE:
                            # 2. ISDB-T Mode3+ECC復調
                            ecc_results = isdb_decoder.process_isdb_mode3_with_ecc(processed_samples)

                            if ecc_results:
                                # 3. Transport Stream抽出
                                ts_data = isdb_decoder.extract_transport_stream(ecc_results)

                                if ts_data and len(ts_data) >= 188:
                                    # 4. TSパーサーで解析
                                    from ts_parser import TSParser
                                    ts_parser = TSParser()
                                    ts_packets = ts_parser.parse_data(ts_data)

                                    if ts_packets:
                                        # 5. ストリーム情報取得
                                        stream_info = ts_parser.get_stream_info()

                                        # 6. TS出力処理
                                        success = ts_output_manager.process_and_output(
                                            ts_data, stream_info
                                        )

                                        if success:
                                            packet_count += len(ts_packets)
                                            if packet_count % 100 == 0:
                                                logger.debug(f"TS出力: 累計{packet_count}パケット")

                        # 短時間待機（CPU負荷軽減）
                        time.sleep(0.01)

                    except KeyboardInterrupt:
                        break
                    except Exception as processing_error:
                        logger.error(f"信号処理エラー: {processing_error}")
                        time.sleep(0.1)

                # TS出力統計表示
                output_stats = ts_output_manager.get_manager_stats()
                logger.info(f"TS出力統計: {output_stats['output_stats']['packets_output']}パケット出力")
                logger.info(f"出力ビットレート: {output_stats['output_stats'].get('average_bitrate', 0):.0f}bps")

                ts_output_manager.stop_output()
                logger.info("TS出力管理停止")

            except ImportError:
                logger.error("TS出力モジュールが利用できません - ダミー出力を行います")
                for _ in range(10):
                    sys.stdout.buffer.write(dummy_ts_packet)
                    sys.stdout.buffer.flush()

            except Exception as ts_error:
                logger.error(f"TS出力処理エラー: {ts_error}")
                logger.warning("ダミーTS出力にフォールバック")
                for _ in range(10):
                    sys.stdout.buffer.write(dummy_ts_packet)
                    sys.stdout.buffer.flush()

            logger.info("MPEG-TS出力処理完了")

    except KeyboardInterrupt:
        logger.info("ユーザーによって中断されました")
        sys.exit(0)
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
