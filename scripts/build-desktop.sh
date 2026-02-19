#!/usr/bin/env bash
# PaperMind Desktop — 一键构建脚本 (macOS)
# 1. PyInstaller 打包 Python 后端
# 2. 安装 Tauri 前端依赖
# 3. Tauri build 生成 .dmg
# @author Bamzc

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCH="${1:-$(uname -m)}"

echo "========================================"
echo " PaperMind Desktop Build"
echo " Platform: macOS ($ARCH)"
echo " Root: $ROOT"
echo "========================================"

# --- Step 1: PyInstaller 打包后端 ---
echo ""
echo ">>> [1/4] Building Python backend with PyInstaller..."

cd "$ROOT"

if ! command -v pyinstaller &>/dev/null; then
    echo "  Installing PyInstaller..."
    pip install pyinstaller
fi

pyinstaller --clean --noconfirm papermind-server.spec

echo "  Backend binary: dist/papermind-server"
ls -lh dist/papermind-server

# --- Step 2: 放到 Tauri sidecar 目录 ---
echo ""
echo ">>> [2/4] Placing sidecar binary..."

TAURI_BIN="$ROOT/src-tauri/binaries"
mkdir -p "$TAURI_BIN"

# Tauri sidecar 需要带平台后缀
if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
    SUFFIX="aarch64-apple-darwin"
else
    SUFFIX="x86_64-apple-darwin"
fi

cp dist/papermind-server "$TAURI_BIN/papermind-server-$SUFFIX"
chmod +x "$TAURI_BIN/papermind-server-$SUFFIX"
echo "  Sidecar: $TAURI_BIN/papermind-server-$SUFFIX"

# --- Step 3: 前端构建 ---
echo ""
echo ">>> [3/4] Building frontend..."

cd "$ROOT/frontend"

if [ ! -d "node_modules" ]; then
    echo "  Installing frontend dependencies..."
    npm install
fi

# 安装 Tauri JS 依赖
npm install --save @tauri-apps/api @tauri-apps/plugin-dialog @tauri-apps/plugin-fs @tauri-apps/plugin-shell 2>/dev/null || true

npm run build
echo "  Frontend dist: $ROOT/frontend/dist"

# --- Step 4: Tauri build ---
echo ""
echo ">>> [4/4] Building Tauri app..."

cd "$ROOT"

if ! command -v cargo &>/dev/null; then
    echo "ERROR: Rust/Cargo is not installed. Install from https://rustup.rs/"
    exit 1
fi

cd "$ROOT/src-tauri"
cargo tauri build

echo ""
echo "========================================"
echo " BUILD COMPLETE"
echo " Output: src-tauri/target/release/bundle/"
echo "========================================"
ls -la target/release/bundle/dmg/ 2>/dev/null || echo "  (Check target/release/bundle/ for output)"
