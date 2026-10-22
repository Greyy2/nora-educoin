#!/bin/bash
# Nora Backtest — Dừng API services
# Dùng: ./stop.sh          — dừng tất cả (coin + edu + legacy)
#       ./stop.sh coin      — chỉ dừng COIN API
#       ./stop.sh edu       — chỉ dừng EDU API
#       ./stop.sh legacy    — chỉ dừng legacy monolith (nora-api)
MODE="${1:-all}"

stop_if_running() {
    local unit="$1" port="$2"
    if systemctl --user is-active --quiet "$unit" 2>/dev/null; then
        systemctl --user stop "$unit"
        echo "✅ Đã dừng $unit (port $port)."
    else
        echo "ℹ️  $unit không đang chạy."
    fi
}

case "$MODE" in
    coin)   stop_if_running nora-coin 18010 ;;
    edu)    stop_if_running nora-edu  18020 ;;
    legacy) stop_if_running nora-api  18010 ;;
    all)
        stop_if_running nora-coin 18010
        stop_if_running nora-edu  18020
        stop_if_running nora-api  18010
        ;;
    *)
        echo "❌ Mode không hợp lệ: $MODE. Dùng: coin | edu | legacy | all" >&2
        exit 1
        ;;
esac
