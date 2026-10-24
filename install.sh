#!/usr/bin/env bash
set -e

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it with: sudo apt install python3 python3-venv python3-pip"
  exit 1
fi

INSTALL_DIR="${HOME}/.local/share/ubuntu-sysperf-cli"
VENV_DIR="${INSTALL_DIR}/venv"
BIN_DIR="${HOME}/.local/bin"

mkdir -p "$INSTALL_DIR" "$BIN_DIR"
cp -R sysperf setup.py requirements.txt "$INSTALL_DIR"/
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install --upgrade --force-reinstall "$INSTALL_DIR" >/dev/null
ln -sf "$VENV_DIR/bin/sysperf" "$BIN_DIR/sysperf"

echo
echo "Installed successfully."
echo "Run: sysperf"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "Add this to your shell profile if needed: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
