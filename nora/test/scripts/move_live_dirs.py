"""Một lần: chuyển thư mục trạng thái bot data/live/<tên cũ> -> data/live/<paper|testnet|live>/<sàn>_<sổ>[_engine] (crawl/store.live_state_key).

    okx_paper          -> paper/okx_main
    okx_paper_explore  -> paper/okx_explore
    okx_demo_unified   -> testnet/okx_main          (bot demo đang chạy engine unified = mặc định của demo)
    okx_demo           -> testnet/okx_main_legacy   (trạng thái legacy cũ, giữ lại)

Mặc định DRY-RUN (chỉ in kế hoạch + kiểm đọc được trạng thái ở chỗ CŨ); --apply mới đổi tên (os.rename, không chép / xoá).
Từ chối nếu còn job live_bot đang chạy/chờ (dừng bot trước). Sau khi đổi tên nạp lại pickle / json bằng chính loader của live.live.
Trạng thái (state.json, paper.json, paper_state.npz, unified.pkl, paper.pkl) không chứa đường dẫn thư mục bot; chỉ events.jsonl có thể nhắc đường
lưu trữ cũ trong một dòng log lịch sử (không ảnh hưởng chạy).

    cd nora && ~/.venvs/nora/bin/python test/scripts/move_live_dirs.py [--apply]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.crawl.store import live_dir  # noqa: E402

MOVES = [("okx_paper", ("okx", "paper", "main", None)),
         ("okx_paper_explore", ("okx", "paper", "explore", None)),
         ("okx_demo_unified", ("okx", "demo", "main", "unified")),
         ("okx_demo", ("okx", "demo", "main", "legacy"))]


def running_bots():
    from backend.optimize.process import process as batch
    return [j.get("id") for j in batch.list_jobs(limit=100, kind="live_bot") if j.get("status") in ("running", "queued")]


def verify(d: str) -> list:
    """Nạp mọi tệp trạng thái có trong thư mục bằng loader của live.live. Trả danh sách mô tả đã nạp; lỗi -> ném."""
    from backend.live import live as lv
    out = []
    if os.path.isfile(os.path.join(d, "state.json")):
        with open(os.path.join(d, "state.json"), encoding="utf-8") as fh:
            json.load(fh)
        out.append("state.json")
    if any(os.path.isfile(os.path.join(d, n)) for n in ("paper.json", "paper.pkl")):
        pb = lv.load_paper_state(d)
        out.append(f"paper({type(pb).__name__}, {len(list(pb.trades))} lệnh)")
    if os.path.isfile(os.path.join(d, "unified.pkl")):
        lv.load_state(os.path.join(d, "unified.pkl"))
        out.append("unified.pkl")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="đổi tên thật (mặc định: dry-run)")
    a = ap.parse_args()
    run = running_bots()
    if run and a.apply:
        print(f"TỪ CHỐI: còn job live_bot đang chạy {run} — dừng bot trước khi chuyển thư mục.")
        return 2
    if run:
        print(f"CẢNH BÁO: job live_bot đang chạy {run} (--apply sẽ từ chối)")
    root = os.path.dirname(live_dir("okx", "paper"))     # data/live/paper -> lấy data/live
    live_root = os.path.dirname(root)
    plan, bad = [], 0
    for old, args in MOVES:
        src, dst = os.path.join(live_root, old), live_dir(*args)
        if not os.path.isdir(src):
            print(f"bỏ qua  {old}: không có")
            continue
        if os.path.exists(dst):
            print(f"LỖI     {old}: đích đã tồn tại {dst}")
            bad += 1
            continue
        try:
            what = verify(src)
        except Exception as e:  # noqa: BLE001
            print(f"LỖI     {old}: không nạp được trạng thái ({type(e).__name__}: {e})")
            bad += 1
            continue
        print(f"{'đổi tên' if a.apply else 'sẽ đổi'}  {os.path.relpath(src, live_root)} -> {os.path.relpath(dst, live_root)}   [nạp được: {', '.join(what) or 'trống'}]")
        plan.append((src, dst))
    if bad:
        print("Dừng: có lỗi ở trên, chưa đổi gì.")
        return 1
    if not a.apply:
        print("DRY-RUN (thêm --apply để đổi tên).")
        return 0
    for src, dst in plan:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)
    for src, dst in plan:
        print(f"kiểm sau chuyển {os.path.relpath(dst, live_root)}: {', '.join(verify(dst)) or 'trống'}")
    print("Xong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
