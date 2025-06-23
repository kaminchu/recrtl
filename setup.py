#!/usr/bin/env python3
"""
ワンセグCLIツール セットアップスクリプト
"""

from setuptools import setup, find_packages
import os

# README.mdの内容を読み込み
def read_readme():
    with open("README.md", "r", encoding="utf-8") as f:
        return f.read()

# requirements.txtから依存関係を読み込み
def read_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="oneseg-cli",
    version="0.1.0",
    description="RTL2832ベースUSBチューナーを使用した日本のワンセグ放送受信CLIツール",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    author="ワンセグCLI開発チーム",
    author_email="",
    url="https://github.com/example/oneseg-cli",
    license="GPL-3.0",
    
    packages=find_packages() + ['src'],
    package_dir={'src': 'src'},
    python_requires=">=3.7",
    install_requires=read_requirements(),
    
    entry_points={
        "console_scripts": [
            "oneseg=oneseg:main",
        ],
    },
    
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Multimedia :: Video :: Capture",
        "Topic :: Communications :: Ham Radio",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    
    keywords="rtl-sdr isdb-t oneseg dtv japan digital-tv",
    
    project_urls={
        "Bug Reports": "https://github.com/example/oneseg-cli/issues",
        "Source": "https://github.com/example/oneseg-cli",
        "Documentation": "https://github.com/example/oneseg-cli/blob/master/README.md",
    },
)