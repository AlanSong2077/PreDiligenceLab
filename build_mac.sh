#!/bin/bash
# ============================================================
# build_mac.sh  —  macOS 打包脚本
# 生成 dist/PreDiligenceLab.app（可直接双击运行）
# ============================================================
set -e

echo "📦 安装 PyInstaller..."
pip3 install pyinstaller --break-system-packages -q

echo "🔨 打包中（.app 模式）..."
pyinstaller \
  --name "PreDiligenceLab" \
  --windowed \
  --onedir \
  --add-data "fetcher.py:." \
  --add-data "analytics.py:." \
  --hidden-import "yfinance" \
  --hidden-import "akshare" \
  --hidden-import "requests" \
  --hidden-import "pandas" \
  --hidden-import "matplotlib" \
  --hidden-import "matplotlib.backends.backend_qtagg" \
  --hidden-import "matplotlib.backends.backend_agg" \
  --hidden-import "PyQt6.QtWidgets" \
  --hidden-import "PyQt6.QtCore" \
  --hidden-import "PyQt6.QtGui" \
  --noconfirm \
  main.py

echo ""
echo "✅ 打包完成！"
echo "   应用位置：dist/PreDiligenceLab.app"
echo "   可直接双击运行，或拖入 /Applications 安装"
