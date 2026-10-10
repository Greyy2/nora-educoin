#!/usr/bin/env bash
# Cài systemd user units của Nora: nora.slice (ngân sách RAM chung) + nora-api.service (KHÔNG enable/start).
# Chạy lại được nhiều lần (idempotent). Biến: NORA_PYTHON (mặc định /home/vmc03/.venvs/nora312/bin/python).
set -euo pipefail

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORA_DIR="$(cd "$OPS_DIR/.." && pwd)"
NORA_PYTHON="${NORA_PYTHON:-/home/vmc03/.venvs/nora312/bin/python}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

[ -x "$NORA_PYTHON" ] || { echo "[install_user_units] Không thấy python: $NORA_PYTHON (đặt NORA_PYTHON)." >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "[install_user_units] Thiếu systemctl." >&2; exit 1; }

mkdir -p "$UNIT_DIR"
cp "$OPS_DIR/systemd/nora.slice" "$UNIT_DIR/nora.slice"
sed -e "s|@NORA_DIR@|$NORA_DIR|g" -e "s|@NORA_PYTHON@|$NORA_PYTHON|g" \
    "$OPS_DIR/systemd/nora-api.service.in" > "$UNIT_DIR/nora-api.service"
echo "[install_user_units] Đã cài vào $UNIT_DIR: nora.slice, nora-api.service"

systemctl --user daemon-reload
systemctl --user show nora.slice -p MemoryMax -p MemoryHigh -p TasksMax
echo "[install_user_units] Khởi động API: systemctl --user restart nora-api (hoặc nora/start.sh)"
