#!/usr/bin/env bash
# Chạy script Python nặng dưới TRẦN RAM cứng (cgroup v2 qua systemd-run) + giới hạn CPU (taskset).
#
# Vì sao: server dùng chung (67 GB RAM, KHÔNG có swap). Một job tràn RAM từng làm sập cả máy. Với
# MemoryMax + MemorySwapMax=0, khi vượt trần kernel chỉ giết tiến trình của job này, người khác không bị ảnh hưởng.
# Controller `cpu` không được uỷ quyền cho user session nên không dùng CPUQuota được -> giới hạn CPU bằng taskset
# (+ nice 10 để nhường tải cho người khác). Script Python dùng usable_cpus() nên tự thấy đúng số CPU được cấp.
#
# Dùng:  scripts/run_limited.sh [--mem 8G] [--cpus 0-5] [--log FILE] -- scripts/build_strategy_book.py --n 24 ...
# Biến môi trường (mặc định): NORA_MEM_MAX=8G  NORA_CPUS=0-5  NORA_PYTHON=/home/vmc03/.venvs/nora/bin/python
#                             NORA_MEM_LOG= (đường dẫn file ghi "epoch,current_mb" mỗi giây; rỗng = không ghi)
set -euo pipefail

NORA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEM="${NORA_MEM_MAX:-8G}"
CPUS="${NORA_CPUS:-0-5}"
PY="${NORA_PYTHON:-/home/vmc03/.venvs/nora/bin/python}"
LOG="${NORA_MEM_LOG:-}"

usage() { echo "Dùng: $0 [--mem 8G] [--cpus 0-5] [--log FILE] -- <đối số python...>" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --mem)  [ $# -ge 2 ] || usage; MEM="$2"; shift 2 ;;
    --cpus) [ $# -ge 2 ] || usage; CPUS="$2"; shift 2 ;;
    --log)  [ $# -ge 2 ] || usage; LOG="$2"; shift 2 ;;
    --)     shift; break ;;
    -h|--help) usage ;;
    *)      echo "Đối số lạ: $1 (đặt '--' trước đối số python)" >&2; usage ;;
  esac
done
[ $# -gt 0 ] || usage

command -v systemd-run >/dev/null 2>&1 || { echo "[run_limited] Thiếu systemd-run — không thể đặt trần RAM, từ chối chạy." >&2; exit 1; }
command -v taskset >/dev/null 2>&1 || { echo "[run_limited] Thiếu taskset." >&2; exit 1; }
[ -x "$PY" ] || { echo "[run_limited] Không chạy được python: $PY (đặt NORA_PYTHON)." >&2; exit 1; }

cd "$NORA_DIR"
export PYTHONPATH="$NORA_DIR"
export NORA_MEM_LOG_PATH="$LOG" NORA_MEM_LIMIT_LABEL="$MEM"

# Shell bên trong cgroup: lấy mẫu memory.current mỗi giây (đỉnh), chạy python (không exec), in tóm tắt.
INNER='
py="$1"; shift
cg="/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup | head -1)"
peakf="$(mktemp)"; echo 0 > "$peakf"
(
  peak=0
  while :; do
    cur=$(cat "$cg/memory.current" 2>/dev/null || echo 0)
    [ "$cur" -gt "$peak" ] && { peak=$cur; echo "$peak" > "$peakf"; }
    [ -n "$NORA_MEM_LOG_PATH" ] && echo "$(date +%s),$((cur / 1048576))" >> "$NORA_MEM_LOG_PATH"
    sleep 1
  done
) &
sampler=$!
"$py" "$@"
rc=$?
kill "$sampler" 2>/dev/null; wait "$sampler" 2>/dev/null
peak=$(cat "$peakf" 2>/dev/null || echo 0); rm -f "$peakf"
echo "[run_limited] peak RAM $((peak / 1048576)) MB / limit $NORA_MEM_LIMIT_LABEL | exit $rc" >&2
if [ "$rc" -eq 137 ] || [ "$rc" -eq 9 ]; then
  echo "[run_limited] Job bị kill (SIGKILL) — nhiều khả năng đã chạm trần RAM $NORA_MEM_LIMIT_LABEL (OOM trong cgroup). Giảm --workers / --per-worker-mb hoặc tăng --mem." >&2
fi
exit "$rc"
'

exec systemd-run --user --scope --quiet -p MemoryMax="$MEM" -p MemorySwapMax=0 -- \
  taskset -c "$CPUS" nice -n 10 bash -c "$INNER" _ "$PY" "$@"
