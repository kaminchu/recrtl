#!/bin/bash
# ワンセグCLI開発環境設定スクリプト
# 使用方法: source env.sh

# プロジェクトルートディレクトリを取得
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# PYTHONPATHにsrcディレクトリを追加
export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH}"

echo "ワンセグCLI開発環境を設定しました"
echo "PYTHONPATH=${PYTHONPATH}"
echo ""
echo "使用例:"
echo "  python oneseg.py --list-devices"
echo "  python oneseg.py -c 13 | ffplay -"
echo "  python run_tests.py"