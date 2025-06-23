#!/usr/bin/env python3
"""
ワンセグCLIツール実行スクリプト

環境設定を含む実行ラッパー
"""

import os
import sys

# プロジェクトルートを取得
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')

# PYTHONPATHにsrcディレクトリを追加
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# 環境変数も設定
os.environ['PYTHONPATH'] = src_path + ':' + os.environ.get('PYTHONPATH', '')

# メインモジュールをインポートして実行
if __name__ == "__main__":
    # oneseg.pyのメイン関数を呼び出し
    import importlib.util
    spec = importlib.util.spec_from_file_location("oneseg", os.path.join(project_root, "oneseg.py"))
    oneseg_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oneseg_module)
    oneseg_module.main()