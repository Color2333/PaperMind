#!/usr/bin/env bash
# 本地构建 pm CLI 单文件可执行（各平台在自己机器上跑即可）
# 依赖: pip install pyinstaller  （输出 dist/pm，Windows 为 dist/pm.exe）
set -euo pipefail
cd "$(dirname "$0")/.."

pyinstaller --onefile --clean --noconfirm --name pm \
  --paths . \
  --hidden-import "apps.cli.main" \
  --hidden-import "apps.cli.client" \
  --hidden-import "apps.cli.config" \
  --collect-data certifi \
  apps/cli/__main__.py

echo
echo "构建完成: dist/pm"
