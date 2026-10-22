#!/bin/bash
# Nora Backtest — hệ thống backtest độc lập
#   COIN API + giao diện: http://localhost:18010  (nora-coin.service)
#   EDU  API + giao diện: http://localhost:18020  (nora-edu.service)
#   Legacy API (monolith): http://localhost:18010 (nora-api.service)
#
# Dùng: ./start.sh            — khởi động COIN (mặc định, port 18010)
#       ./start.sh edu        — khởi động EDU (port 18020)
#       ./start.sh coin       — khởi động COIN (port 18010)
#       ./start.sh legacy     — khởi động monolith cũ (nora-api, port 18010)
#       ./start.sh all        — khởi động cả COIN + EDU
set -e
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-coin}"

echo "======================================================="
echo "🔬 NORA BACKTEST — MODE: $MODE"
echo "======================================================="

# ─── Đảm bảo systemd units đã cài ───────────────────────────────────────────
if ! systemctl --user cat nora.slice >/dev/null 2>&1; then
    echo "⚙️  Chưa cài systemd user unit — đang cài..."
    "$BASE/ops/install_user_units.sh"
fi

# ─── Hàm: build frontend nếu cần ─────────────────────────────────────────────
ensure_build() {
    local dist="$1" config="$2" label="$3"
    if [ ! -f "$BASE/frontend/$dist/index.html" ]; then
        echo "📦 Chưa có bản build $label — đang build (giới hạn 4 cores)..."
        cd "$BASE/frontend"
        [ -d node_modules ] || taskset -c 0-3 nice -n 10 npm install --no-audit --no-fund
        if [ -n "$config" ]; then
            taskset -c 0-3 nice -n 10 npx vite build --config "$config"
        else
            taskset -c 0-3 nice -n 10 npm run build
        fi
    fi
}

# ─── Hàm: khởi động một service và chờ health ────────────────────────────────
start_service() {
    local unit="$1" port="$2" label="$3"
    if ! systemctl --user cat "$unit.service" >/dev/null 2>&1; then
        echo "⚠️  Unit $unit chưa cài — chạy install_user_units.sh..." >&2
        "$BASE/ops/install_user_units.sh"
    fi
    echo "▶️  Khởi động $unit (port $port)..."
    systemctl --user restart "$unit"
    for _ in $(seq 1 25); do
        if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$port/api/health" | grep -q 200; then
            echo "✅ $label đang chạy tại http://localhost:$port"
            echo "   Log: journalctl --user -u $unit -f"
            return 0
        fi
        sleep 1
    done
    echo "❌ $label khởi động thất bại — 50 dòng log cuối:"
    journalctl --user -u "$unit" -n 50 --no-pager || true
    return 1
}

# ─── Thực thi theo mode ───────────────────────────────────────────────────────
case "$MODE" in
    coin)
        ensure_build "dist-coin" "vite.coin.config.js" "COIN"
        start_service "nora-coin" 18010 "COIN API"
        ;;
    edu)
        ensure_build "dist-edu" "vite.edu.config.js" "EDU"
        start_service "nora-edu" 18020 "EDU API"
        ;;
    all)
        ensure_build "dist-coin" "vite.coin.config.js" "COIN"
        ensure_build "dist-edu" "vite.edu.config.js" "EDU"
        start_service "nora-coin" 18010 "COIN API"
        start_service "nora-edu" 18020 "EDU API"
        ;;
    legacy)
        ensure_build "dist" "" "legacy monolith"
        if ! systemctl --user cat nora-api.service >/dev/null 2>&1; then
            "$BASE/ops/install_user_units.sh"
        fi
        echo "▶️  Khởi động nora-api (legacy, port 18010)..."
        systemctl --user restart nora-api
        for _ in $(seq 1 20); do
            curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18010/api/health | grep -q 200 && {
                echo "✅ Legacy API đang chạy tại http://localhost:18010"
                echo "   Log: journalctl --user -u nora-api -f"
                echo "======================================================="
                exit 0
            }
            sleep 1
        done
        echo "❌ Khởi động thất bại — 50 dòng log cuối:"
        journalctl --user -u nora-api -n 50 --no-pager || true
        exit 1
        ;;
    *)
        echo "❌ Mode không hợp lệ: $MODE. Dùng: coin | edu | all | legacy" >&2
        exit 1
        ;;
esac

echo "======================================================="
