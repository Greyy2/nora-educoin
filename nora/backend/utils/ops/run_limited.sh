#!/usr/bin/env bash
# Chạy script Python nặng TRONG ngân sách RAM chung của Nora (nora.slice, cgroup v2) + giới hạn CPU (taskset).
#
# Vì sao: server dùng chung (67 GB RAM, KHÔNG có swap). Một job tràn RAM từng làm sập cả máy. Cả dự án Nora dùng
# MỘT ngân sách: nora.slice (MemoryMax=12G, MemorySwapMax=0) — API, script nặng và test đều nằm trong đó. Vượt trần
# thì kernel chỉ giết tiến trình trong slice, người khác không bị ảnh hưởng (cài slice: backend/utils/ops/install_user_units.sh).
# Các giai đoạn pipeline chạy TUẦN TỰ (backtest -> WFA -> Monte Carlo -> holdout) nên job nặng xếp hàng từng cái một
# (flock trên ${XDG_RUNTIME_DIR:-/tmp}/nora-heavy.lock) và mỗi job tự chia số worker theo phần ngân sách còn trống.
# Mặc định KHÔNG đặt trần riêng cho job (trần slice 12G áp dụng); --mem X (hoặc NORA_MEM_MAX) đặt thêm trần riêng.
# Controller `cpu` không được uỷ quyền cho user session nên không dùng CPUQuota được -> giới hạn CPU bằng taskset
# (+ nice 10 để nhường tải cho người khác). Script Python dùng usable_cpus() nên tự thấy đúng số CPU được cấp.
#
# Dùng (từ thư mục nora/):  backend/utils/ops/run_limited.sh [--mem 8G] [--cpus 0-13] [--log FILE] [--no-wait | --no-lock] -- -m backend.optimize.book --n 24 ...
#   --no-wait  job khác đang chạy thì thoát ngay với mã 75 (mặc định: chờ trong hàng đợi)
#   --no-lock  bỏ qua hàng đợi (cho lệnh nhẹ); vẫn nằm trong nora.slice
# Biến môi trường (mặc định): NORA_MEM_MAX= (rỗng = chỉ dùng trần slice)  NORA_CPUS=0-13
#                             NORA_PYTHON=/home/vmc03/.venvs/nora/bin/python
#                             NORA_MEM_LOG= (file ghi "epoch,current_mb" mỗi giây; rỗng = data/_cache/runs/<ts>_mem.csv)
set -euo pipefail

NORA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
MEM="${NORA_MEM_MAX:-}"
CPUS="${NORA_CPUS:-0-13}"
PY="${NORA_PYTHON:-/home/vmc03/.venvs/nora/bin/python}"
LOG="${NORA_MEM_LOG:-}"
LOCK_MODE=wait   # wait | nowait | none
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/nora-heavy.lock"

usage() { echo "Dùng: $0 [--mem 8G] [--cpus 0-13] [--log FILE] [--no-wait | --no-lock] -- <đối số python...>" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --mem)  [ $# -ge 2 ] || usage; MEM="$2"; shift 2 ;;
    --cpus) [ $# -ge 2 ] || usage; CPUS="$2"; shift 2 ;;
    --log)  [ $# -ge 2 ] || usage; LOG="$2"; shift 2 ;;
    --no-wait) LOCK_MODE=nowait; shift ;;
    --no-lock) LOCK_MODE=none; shift ;;
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
  echo "[run_limited] Chưa có nora.slice — chạy $NORA_DIR/backend/utils/ops/install_user_units.sh trước." >&2; exit 1; }

# Hàng đợi job nặng: giữ khoá (fd 9) suốt thời gian job chạy — KHÔNG exec, để khoá không bị mất khi script kết thúc.
if [ "$LOCK_MODE" != none ]; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    if [ "$LOCK_MODE" = nowait ]; then
      echo "[run_limited] Có job khác của Nora đang chạy (--no-wait) — thoát." >&2
      exit 75
    fi
    echo "[run_limited] đang chờ job khác của Nora chạy xong..." >&2
    flock 9
  fi
fi

# Log RAM mỗi giây: mặc định data/_cache/runs/<ts>_mem.csv (đặt sau khi qua hàng đợi để mốc thời gian đúng lúc chạy)
if [ -z "$LOG" ]; then
  mkdir -p "$NORA_DIR/data/_cache/runs"
  LOG="$NORA_DIR/data/_cache/runs/$(date +%Y%m%d_%H%M%S)_mem.csv"
fi
mkdir -p "$(dirname "$LOG")"

cd "$NORA_DIR"
export PYTHONPATH="$NORA_DIR"
export NORA_MEM_LOG_PATH="$LOG" NORA_MEM_LIMIT_LABEL="${MEM:-nora.slice}"
export NORA_SLICE_CG="/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/nora.slice"

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
    echo "$(date +%s),$((cur / 1048576))" >> "$NORA_MEM_LOG_PATH"
    sleep 1
  done
) &
sampler=$!
rc=0
"$py" "$@" || rc=$?
kill "$sampler" 2>/dev/null; wait "$sampler" 2>/dev/null
peak=$(cat "$peakf" 2>/dev/null || echo 0); rm -f "$peakf"
echo "[run_limited] peak RAM $((peak / 1048576)) MB / limit $NORA_MEM_LIMIT_LABEL | exit $rc" >&2
if [ -r "$NORA_SLICE_CG/memory.current" ]; then
  echo "[run_limited] nora.slice đang dùng $(( $(cat "$NORA_SLICE_CG/memory.current") / 1048576 )) MB (tổng cả slice)" >&2
fi
echo "[run_limited] log RAM: $NORA_MEM_LOG_PATH" >&2
if [ "$rc" -eq 137 ] || [ "$rc" -eq 9 ]; then
  echo "[run_limited] Job bị kill (SIGKILL) — nhiều khả năng đã chạm trần RAM ($NORA_MEM_LIMIT_LABEL, OOM trong cgroup). Giảm --workers / --per-worker-mb, hoặc tăng --mem nếu có đặt." >&2
fi
exit "$rc"
'

SD=(systemd-run --user --scope --quiet --slice=nora.slice)
[ -n "$MEM" ] && SD+=(-p "MemoryMax=$MEM" -p MemorySwapMax=0)

rc=0
"${SD[@]}" -- taskset -c "$CPUS" nice -n 10 bash -c "$INNER" _ "$PY" "$@" || rc=$?
exit "$rc"
