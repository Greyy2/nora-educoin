"""Chạy Phase 4 (implied exit fitting) cho 1 hoặc nhiều bot. Ví dụ:
  NORA_PYTHON=~/.venvs/okxr/bin/python OMP_NUM_THREADS=6 /home/vmc03/norabt/nora/backend/utils/ops/run_limited.sh --mem 4G --no-lock -- \
      /home/vmc03/norabt/nora/test/scripts/okx_top10/run_implied.py --bot Auroraxwt
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import load
import implied

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", nargs="*", help="tên bot (mặc định: tất cả)")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    a = ap.parse_args()
    names = a.bot or [b["name"] for b in load.load_bots()]
    for n in names:
        implied.fit_bot(n, a.out)
