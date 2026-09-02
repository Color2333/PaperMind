#!/usr/bin/env bash
# pm CLI 一键安装（macOS / Linux）
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/Color2333/PaperMind/main/scripts/install-pm.sh | bash
#
# 从 GitHub Releases 下载对应平台二进制到 ~/.local/bin/pm
set -euo pipefail

REPO="Color2333/PaperMind"
INSTALL_DIR="${PM_INSTALL_DIR:-$HOME/.local/bin}"

platform() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os" in
    Darwin) os="darwin" ;;
    Linux) os="linux" ;;
    *) echo "不支持的系统: $os（Windows 请用 install-pm.ps1）" >&2; exit 1 ;;
  esac
  case "$arch" in
    arm64 | aarch64) arch="arm64" ;;
    x86_64 | amd64) arch="x86_64" ;;
    *) echo "不支持的架构: $arch" >&2; exit 1 ;;
  esac
  echo "${os}-${arch}"
}

TARGET="$(platform)"
ASSET="pm-${TARGET}"
URL="https://github.com/${REPO}/releases/latest/download/${ASSET}"

echo "下载 ${URL}"
mkdir -p "$INSTALL_DIR"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$URL" -o "$INSTALL_DIR/pm"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$INSTALL_DIR/pm" "$URL"
else
  echo "需要 curl 或 wget" >&2
  exit 1
fi
chmod +x "$INSTALL_DIR/pm"

# macOS：去除隔离属性，避免 Gatekeeper 拦截未公证二进制
if [ "$(uname -s)" = "Darwin" ] && command -v xattr >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "$INSTALL_DIR/pm" 2>/dev/null || true
fi

echo
if echo "$PATH" | tr ':' '\n' | grep -qx "$INSTALL_DIR"; then
  echo "✓ 安装完成: $(command -v pm)"
else
  echo "✓ 安装到 $INSTALL_DIR/pm"
  echo "  请把它加入 PATH（加到 ~/.zshrc 或 ~/.bashrc）："
  echo "    export PATH=\"$INSTALL_DIR:\$PATH\""
fi
"$INSTALL_DIR/pm" --version
echo
echo "接下来: pm login --server https://你的-papermind-地址"
