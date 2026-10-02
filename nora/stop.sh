#!/bin/bash
# Nora Backtest — Dừng API (systemd user service nora-api)
systemctl --user stop nora-api
echo "✅ Đã dừng Nora Backtest (port 18010)."
