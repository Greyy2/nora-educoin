#!/usr/bin/env bash
# Đưa Nora ra public qua nginx host: build frontend -> đảm bảo API chạy -> cài vhost -> reload nginx.
# Chạy lại được nhiều lần (idempotent). Cần sudo cho bước nginx.
#   SKIP_BUILD=1    bỏ qua build frontend
#   PRODUCT=coin    chỉ deploy coin (mặc định: cả 3 — legacy + coin + edu)
#   PRODUCT=edu     chỉ deploy edu
#   PRODUCT=legacy  chỉ deploy nora.expsolution.io (monolith cũ)
set -euo pipefail

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORA_DIR="$(cd "$OPS_DIR/.." && pwd)"
PRODUCT="${PRODUCT:-all}"

log() { echo "[deploy_nginx] $*"; }

# ─── 1. Build frontend ────────────────────────────────────────────────────────
if [ "${SKIP_BUILD:-0}" != 1 ]; then
    if [ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "coin" ]; then
        log "Build frontend COIN ($NORA_DIR/coin/frontend)..."
        cd "$NORA_DIR/coin/frontend"
        [ -d node_modules ] || taskset -c 0-3 nice -n 10 npm install --no-audit --no-fund
        taskset -c 0-3 nice -n 10 npm run build
    fi
    if [ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "edu" ]; then
        log "Build frontend EDU ($NORA_DIR/edu/frontend)..."
        cd "$NORA_DIR/edu/frontend"
        [ -d node_modules ] || taskset -c 0-3 nice -n 10 npm install --no-audit --no-fund
        taskset -c 0-3 nice -n 10 npm run build
    fi
fi

# ─── 2. Kiểm tra backend APIs ─────────────────────────────────────────────────
# COIN API (port 18012)
if [ "$PRODUCT" = "coin" ]; then
    HEALTH_RESP=$(curl -s --max-time 3 http://127.0.0.1:18012/api/health || true)
    if ! echo "$HEALTH_RESP" | grep -q '"product"[[:space:]]*:[[:space:]]*"coin"'; then
        log "Port 18012 hiện chưa chạy COIN API chuẩn (product: coin). Phản hồi: $HEALTH_RESP" >&2
        log "Từ chối trỏ coin.nora.expsolution.io vào service không phải COIN!" >&2
        exit 1
    fi
    log "Xác nhận COIN API hợp lệ trên port 18012 (product: coin)."
elif [ "$PRODUCT" = "legacy" ]; then
    if ! curl -sf -o /dev/null http://127.0.0.1:18010/api/health; then
        log "Legacy API chưa chạy trên port 18010." >&2
        exit 1
    fi
    log "Xác nhận legacy API đang chạy trên port 18010."
elif [ "$PRODUCT" = "all" ]; then
    HEALTH_RESP=$(curl -s --max-time 3 http://127.0.0.1:18010/api/health || true)
    if [ -z "$HEALTH_RESP" ]; then
        log "Port 18010 chưa chạy." >&2
        exit 1
    fi
    log "Port 18010 phản hồi: $HEALTH_RESP"
fi

# EDU API (port 18022)
if [ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "edu" ]; then
    HEALTH_RESP=$(curl -s --max-time 3 http://127.0.0.1:18022/api/health || true)
    if ! echo "$HEALTH_RESP" | grep -q '"product"[[:space:]]*:[[:space:]]*"edu"'; then
        log "Port 18022 không trả về product: edu (phản hồi: $HEALTH_RESP) — kiểm tra nora-edu.service!" >&2
        exit 1
    fi
    log "Xác nhận EDU API hợp lệ trên port 18022 (product: edu)."
fi

# ─── 3. Nginx — quyền truy cập thư mục (www-data cần o+x) ───────────────────
for d in "$HOME" "$NORA_DIR/.." "$NORA_DIR" "$NORA_DIR/coin/frontend" "$NORA_DIR/edu/frontend"; do
    [ "$(( 0$(stat -c %a "$d") & 1 ))" = 1 ] || { log "Thiếu quyền o+x: $d (chmod o+x)" >&2; exit 1; }
done

# Hàm cài một symlink nginx (idempotent, không đè vhost khác)
install_nginx_vhost() {
    local domain="$1"
    local conf="$OPS_DIR/nginx/$domain.conf"
    local link="/etc/nginx/sites-enabled/$domain.conf"
    [ -f "$conf" ] || { log "Không thấy $conf — bỏ qua $domain." >&2; return 0; }
    if [ -e "$link" ] && [ "$(readlink -f "$link")" != "$(readlink -f "$conf")" ]; then
        log "$link đã tồn tại và trỏ chỗ khác ($(readlink -f "$link")) — dừng để không đè." >&2; exit 1
    fi
    if grep -RqsE "server_name[^;]*\b$domain\b" --exclude="$domain.conf" /etc/nginx/sites-enabled/; then
        log "Vhost khác đã khai báo $domain — dừng." >&2; exit 1
    fi
    log "Link $link -> $conf"
    sudo ln -sfn "$conf" "$link"
}

if [ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "legacy" ]; then
    install_nginx_vhost "nora.expsolution.io"
fi
if [ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "coin" ]; then
    install_nginx_vhost "coin.nora.expsolution.io"
fi
if [ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "edu" ]; then
    install_nginx_vhost "edu.nora.expsolution.io"
fi

sudo nginx -t
sudo systemctl reload nginx

log "Xong. Kiểm tra:"
[ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "legacy" ] && log "  curl -s -H 'Host: nora.expsolution.io'      http://127.0.0.1/api/health"
[ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "coin" ]   && log "  curl -s -H 'Host: coin.expsolution.io' http://127.0.0.1/api/health"
[ "$PRODUCT" = "all" ] || [ "$PRODUCT" = "edu" ]    && log "  curl -s -H 'Host: edu.expsolution.io'  http://127.0.0.1/api/health"
log "DNS: Cloudflare zone expsolution.io, records coin and edu point to 203.113.135.195 (Proxied)."
