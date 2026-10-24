#!/usr/bin/env bash
# nora/edu/ops/run_limited.sh — Chạy script Python nặng cho NORA EDU trong ngân sách slice + cách ly.
set -euo pipefail

NORA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEM="${NORA_MEM_MAX:-2G}"
CPUS="${NORA_CPUS:-0-13}"
PY="${NORA_PYTHON:-/home/vmc03/.venvs/nora312/bin/python}"
LOG="${NORA_MEM_LOG:-}"
LOCK_MODE=wait   # wait | nowait | none
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/nora-edu-heavy.lock"
NO_MEM_LOG=0

usage() { echo "Dùng: $0 [--mem 2G] [--cpus 0-13] [--log FILE] [--no-wait | --no-lock] [--no-mem-log] -- <đối số python...>" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --mem)  [ $# -ge 2 ] || usage; MEM="$2"; shift 2 ;;
    --cpus) [ $# -ge 2 ] || usage; CPUS="$2"; shift 2 ;;
    --log)  [ $# -ge 2 ] || usage; LOG="$2"; shift 2 ;;
    --no-wait) LOCK_MODE=nowait; shift ;;
    --no-lock) LOCK_MODE=none; shift ;;
    --no-mem-log) NO_MEM_LOG=1; shift ;;
    --)     shift; break ;;
    -h|--help) usage ;;
    *)      echo "Đối số lạ: $1 (đặt '--' trước đối số python)" >&2; usage ;;
  esac
done
[ $# -gt 0 ] || usage

command -v systemd-run >/dev/null 2>&1 || { echo "[run_limited] Thiếu systemd-run — không thể đặt trần RAM, từ chối chạy." >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "[run_limited] Thiếu systemctl." >&2; exit 1; }
command -v taskset >/dev/null 2>&1 || { echo "[run_limited] Thiếu taskset." >&2; exit 1; }
command -v flock >/dev/null 2>&1 || { echo "[run_limited] Thiếu flock." >&2; exit 1; }
[ -x "$PY" ] || { echo "[run_limited] Không chạy được python: $PY (đặt NORA_PYTHON)." >&2; exit 1; }
systemctl --user cat nora.slice >/dev/null 2>&1 || {
  echo "[run_limited] Chưa có nora.slice — chạy ops/install_user_units.sh trước." >&2; exit 1; }

if [ "$LOCK_MODE" != none ]; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    if [ "$LOCK_MODE" = nowait ]; then
      echo "[run_limited] Có job khác của Nora EDU đang chạy (--no-wait) — thoát." >&2
      exit 75
    fi
    echo "[run_limited] đang chờ job khác của Nora EDU chạy xong..." >&2
    flock 9
  fi
fi

NORA_MEM_LOG_TEMP=0
if [ -z "$LOG" ]; then
  mkdir -p "$NORA_DIR/data/cache/process/_mem"
  LOG="$NORA_DIR/data/cache/process/_mem/$(date +%Y%m%d_%H%M%S)_mem.csv"
  NORA_MEM_LOG_TEMP=1
fi
mkdir -p "$(dirname "$LOG")"

cd "$NORA_DIR"
export PYTHONPATH="$NORA_DIR"
export NORA_DATA_ROOT="$NORA_DIR/data"
export NORA_MEM_LOG_PATH="$LOG" NORA_MEM_LIMIT_LABEL="${MEM:-nora.slice}" NORA_MEM_LOG_TEMP
export NORA_SLICE_CG="/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/nora.slice"

INNER='
py="$1"; shift
cg="/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup | head -1)"
peakf="$(mktemp)"; echo 0 > "$peakf"
(
  peak=0
  while :; do
    cur=$(cat "$cg/memory.current" 2>/dev/null || echo 0)
    [ "$cur" -gt "$peak" ] && { peak=$cur; echo "$peak" > "$peakf"; }
    echo "$(date +%s),$((cur / 1048576))" >> "$NORA_MEM_LOG_PATH"
    sleep 1
  done
) &
sampler=$!
trap "kill -9 \${sampler:-} 2>/dev/null || true" EXIT INT TERM
rc=0
"$py" "$@" || rc=$?
kill -9 "${sampler:-}" 2>/dev/null || true
peak=$(cat "$peakf" 2>/dev/null || echo 0); rm -f "$peakf"
echo "[run_limited] peak RAM $((peak / 1048576)) MB / limit $NORA_MEM_LIMIT_LABEL | exit $rc" >&2
if [ -r "$NORA_SLICE_CG/memory.current" ]; then
  echo "[run_limited] nora.slice đang dùng $(( $(cat "$NORA_SLICE_CG/memory.current") / 1048576 )) MB (tổng cả slice)" >&2
fi
if [ "$NORA_MEM_LOG_TEMP" = 1 ]; then
  rm -f "$NORA_MEM_LOG_PATH"
fi
exit "$rc"
'

SD=(systemd-run --user --scope --quiet --slice=nora.slice)
[ -n "$MEM" ] && SD+=(-p "MemoryMax=$MEM" -p MemorySwapMax=0)

rc=0
if [ "$NO_MEM_LOG" = 1 ]; then
  "${SD[@]}" -- taskset -c "$CPUS" nice -n 10 "$PY" "$@" || rc=$?
else
  "${SD[@]}" -- taskset -c "$CPUS" nice -n 10 bash -c "$INNER" _ "$PY" "$@" || rc=$?
fi
exit "$rc"
