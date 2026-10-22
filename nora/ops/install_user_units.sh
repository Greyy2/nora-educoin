#!/usr/bin/env bash
# Cài systemd user units của Nora: nora.slice + các API service (KHÔNG enable/start).
# Chạy lại được nhiều lần (idempotent). Biến: NORA_PYTHON (mặc định /home/vmc03/.venvs/nora312/bin/python).
#
# Units được cài:
#   nora.slice          — ngân sách RAM chung
#   nora-api.service    — API monolith legacy (backend.main:app, port 18010) — giữ để tương thích
#   nora-coin.service   — COIN API (backend.apps.coin:app, port 18010) — thay thế nora-api dần
#   nora-edu.service    — EDU API  (backend.apps.edu:app,  port 18020) — mới
set -euo pipefail

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORA_DIR="$(cd "$OPS_DIR/.." && pwd)"
NORA_PYTHON="${NORA_PYTHON:-/home/vmc03/.venvs/nora312/bin/python}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

[ -x "$NORA_PYTHON" ] || { echo "[install_user_units] Không thấy python: $NORA_PYTHON (đặt NORA_PYTHON)." >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "[install_user_units] Thiếu systemctl." >&2; exit 1; }

mkdir -p "$UNIT_DIR"

# nora.slice — ngân sách RAM chung
cp "$OPS_DIR/systemd/nora.slice" "$UNIT_DIR/nora.slice"

# nora-api.service — legacy monolith (giữ để không phá vỡ setup hiện tại)
sed -e "s|@NORA_DIR@|$NORA_DIR|g" -e "s|@NORA_PYTHON@|$NORA_PYTHON|g" \
    "$OPS_DIR/systemd/nora-api.service.in" > "$UNIT_DIR/nora-api.service"

# nora-coin.service — COIN product API (port 18010, thay thế nora-api dần)
sed -e "s|@NORA_DIR@|$NORA_DIR|g" -e "s|@NORA_PYTHON@|$NORA_PYTHON|g" \
    "$OPS_DIR/systemd/nora-coin.service.in" > "$UNIT_DIR/nora-coin.service"

# nora-edu.service — EDU product API (port 18020)
sed -e "s|@NORA_DIR@|$NORA_DIR|g" -e "s|@NORA_PYTHON@|$NORA_PYTHON|g" \
    "$OPS_DIR/systemd/nora-edu.service.in" > "$UNIT_DIR/nora-edu.service"

echo "[install_user_units] Đã cài vào $UNIT_DIR: nora.slice, nora-api.service, nora-coin.service, nora-edu.service"

systemctl --user daemon-reload
systemctl --user show nora.slice -p MemoryMax -p MemoryHigh -p TasksMax
echo ""
echo "[install_user_units] Khởi động:"
echo "  COIN API: systemctl --user restart nora-coin  (hoặc giữ nora-api trong thời gian migration)"
echo "  EDU API:  systemctl --user start nora-edu"

