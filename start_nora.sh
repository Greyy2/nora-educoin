#!/bin/bash
# Nora Backtest — hệ thống backtest độc lập
#   API + giao diện: http://localhost:18010
#   Mọi việc nặng (backtest, WFA, phễu...) chạy thành job nền qua API (backend/api/jobs/runner.py)
#   API chạy như systemd user service (nora-api) trong nora.slice — ngân sách RAM chung của Nora.
set -e
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "======================================================="
echo "🔬 NORA BACKTEST"
echo "======================================================="

if [ ! -f "$BASE/nora/frontend/dist/index.html" ]; then
    echo "📦 Chưa có bản build giao diện — đang build (giới hạn 4 cores)..."
    cd "$BASE/nora/frontend"
    [ -d node_modules ] || taskset -c 0-3 nice -n 10 npm install --no-audit --no-fund
    taskset -c 0-3 nice -n 10 npm run build
fi

if ! systemctl --user cat nora-api.service >/dev/null 2>&1 || ! systemctl --user cat nora.slice >/dev/null 2>&1; then
    echo "⚙️  Chưa cài systemd user unit — đang cài..."
    "$BASE/nora/backend/utils/ops/install_user_units.sh"
fi

systemctl --user restart nora-api

for _ in $(seq 1 20); do
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18010/api/health | grep -q 200; then
        echo "✅ Đang chạy tại http://localhost:18010"
        echo "   Log: journalctl --user -u nora-api -f"
        echo "======================================================="
        exit 0
    fi
    sleep 1
done

echo "❌ Khởi động thất bại — 50 dòng log cuối:"
journalctl --user -u nora-api -n 50 --no-pager || true
exit 1
