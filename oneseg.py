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

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

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
            
            logger.info("信号処理パイプラインを構築中...")
            logger.info("MPEG-TS出力準備完了")
            
            # ダミーのTSパケットヘッダー（188バイト、同期バイト0x47で開始）
            dummy_ts_packet = b'\x47' + b'\x00' * 187
            
            logger.info("標準出力にMPEG-TSストリームを出力中...")
            logger.info("終了するには Ctrl+C を押してください")
            
            # 実際の実装では無限ループでリアルタイム処理
            # 現在はダミーパケットを少数出力して終了
            logger.warning("注意: 信号処理は未実装のため、ダミーTS出力を行います")
            
            # サンプル読み取りテスト
            if args.verbose:
                logger.info("I/Qサンプル読み取りテスト...")
                samples = rtl.read_samples(1024)
                if samples is not None:
                    if NUMPY_AVAILABLE:
                        avg_power = np.mean(np.abs(samples)**2)
                        logger.info(f"サンプル読み取り成功: {len(samples)}個 (平均パワー: {avg_power:.6f})")
                    else:
                        logger.info(f"サンプル読み取り成功: {len(samples)}個")
                else:
                    logger.error("サンプル読み取り失敗")
            
            for _ in range(10):
                sys.stdout.buffer.write(dummy_ts_packet)
                sys.stdout.buffer.flush()
            
            logger.info("ダミー出力完了（実装完了後は連続出力になります）")
        
    except KeyboardInterrupt:
        logger.info("ユーザーによって中断されました")
        sys.exit(0)
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()