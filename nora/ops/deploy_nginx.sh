#!/usr/bin/env bash
# Đưa Nora ra public qua nginx host: build frontend -> đảm bảo nora-api chạy -> cài vhost -> reload nginx.
# Chạy lại được nhiều lần (idempotent). Cần sudo cho bước nginx.
#   SKIP_BUILD=1  bỏ qua build frontend
set -euo pipefail

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORA_DIR="$(cd "$OPS_DIR/.." && pwd)"
DOMAIN=nora.expsolution.io
CONF="$OPS_DIR/nginx/$DOMAIN.conf"
LINK=/etc/nginx/sites-enabled/$DOMAIN.conf

log() { echo "[deploy_nginx] $*"; }

# 1. frontend
if [ "${SKIP_BUILD:-0}" != 1 ]; then
    log "Build frontend (giới hạn 4 cores)..."
    cd "$NORA_DIR/frontend"
    [ -d node_modules ] || taskset -c 0-3 nice -n 10 npm install --no-audit --no-fund
    taskset -c 0-3 nice -n 10 npm run build
fi
[ -f "$NORA_DIR/frontend/dist/index.html" ] || { log "Thiếu frontend/dist/index.html" >&2; exit 1; }

# 2. backend (systemd user unit trong nora.slice) — chỉ khởi động nếu chưa chạy, không restart job đang chạy
if ! curl -sf -o /dev/null http://127.0.0.1:18010/api/health; then
    log "nora-api chưa chạy — khởi động..."
    systemctl --user cat nora-api.service >/dev/null 2>&1 || "$OPS_DIR/install_user_units.sh"
    systemctl --user start nora-api
    for _ in $(seq 1 20); do curl -sf -o /dev/null http://127.0.0.1:18010/api/health && break; sleep 1; done
fi
curl -sf -o /dev/null http://127.0.0.1:18010/api/health || { log "nora-api không lên — journalctl --user -u nora-api" >&2; exit 1; }

# 3. nginx (www-data cần quyền đi qua thư mục tới dist: o+x)
for d in "$HOME" "$NORA_DIR/.." "$NORA_DIR" "$NORA_DIR/frontend"; do
    [ "$(( 0$(stat -c %a "$d") & 1 ))" = 1 ] || { log "Thiếu quyền o+x: $d (chmod o+x)" >&2; exit 1; }
done

# Theo quy ước các site khác trên máy: sites-enabled symlink thẳng vào file trong repo.
# Không ghi đè vhost của ai: chỉ tạo/đổi đúng link của mình.
if [ -e "$LINK" ] && [ "$(readlink -f "$LINK")" != "$(readlink -f "$CONF")" ]; then
    log "$LINK đã tồn tại và trỏ chỗ khác ($(readlink -f "$LINK")) — dừng để không đè." >&2; exit 1
fi
if grep -RqsE "server_name[^;]*\b$DOMAIN\b" --exclude="$DOMAIN.conf" /etc/nginx/sites-enabled/; then
    log "Vhost khác đã khai báo $DOMAIN — dừng." >&2; exit 1
fi
log "Link $LINK -> $CONF"
sudo ln -sfn "$CONF" "$LINK"

sudo nginx -t
sudo systemctl reload nginx
log "Xong. Kiểm tra: curl -s -H 'Host: $DOMAIN' http://127.0.0.1/api/health"
log "DNS: Cloudflare zone expsolution.io, A 'nora' -> 203.113.135.195, Proxied."
