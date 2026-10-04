"""Chuyển tài sản đã crawl từ data_staging/ sang data/<sàn>/<venue>/<SYM> — chỉ khi qua quality gate.

sàn (okx | binance) và venue ("cex" | "dex") lấy từ manifest.json; xem backend/db/data_layout.py.

Job API `data_promote` (POST /api/data/promote -> api/jobs/runner.py -> run_job). Mặc định chỉ lập kế hoạch (dry-run); apply=True để thực hiện.

- Tài sản trong staging qua gate (không BLOCKED / NEEDS_MORE_DATA) -> chuyển vào data/<sàn>/<venue>/<SYM>
  (thư mục cùng tên ở data/ được cất vào _archive_invalid trước).
- archive_legacy=True: cất mọi thư mục tài sản trong data/<sàn>/ KHÔNG có manifest.json
  vào data/_archive_invalid/legacy_<ngày>/ (không xoá).
"""
import os
import shutil
from datetime import datetime, timezone

from backend.core.data.quality_gate import DataQualityStatus, evaluate_data_quality
from backend.db.data_layout import DATA_HOME, EXCHANGES, VENUES, exchange_of, list_assets
from backend.db.local_pkl import read_manifest
from backend.utils.jobs import options, write_job_result

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULTS = {"staging": os.path.join(NORA_ROOT, "data_staging"), "data": DATA_HOME, "apply": False, "archive_legacy": False}

BLOCKING = (DataQualityStatus.BLOCKED, DataQualityStatus.NEEDS_MORE_DATA)


def run_job(params=None):
    """Lập kế hoạch (và nếu apply=True thì thực hiện) chuyển tài sản đã qua gate từ staging sang data -> {"actions", "applied"}."""
    args = options(DEFAULTS, params)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_root = os.path.join(args.data, "_archive_invalid", f"legacy_{stamp}")
    actions = []

    for item in list_assets(args.staging):
        sym = item["qualified"]
        dq = evaluate_data_quality(sym, timeframe="1m", data_root=args.staging)
        m = read_manifest(sym, data_root=args.staging) or {}
        venue = str(m.get("venue") or "").lower()
        if venue not in VENUES:
            print(f"[skip]    {sym:6s} manifest thiếu venue hợp lệ ('{venue}')")
            continue
        info = (f"venue={m.get('venue')} days={m.get('coverage_days')} filled={m.get('filled_ratio_1m')} "
                f"crawl_ok={m.get('crawl_ok')} gate={dq['status']}")
        if dq["status"] in BLOCKING:
            print(f"[skip]    {sym:6s} {info} issues={dq['issues']}")
            continue
        ex = exchange_of(m)
        print(f"[promote] {sym:6s} {ex} {info}")
        rel = os.path.join(*item["symbol"].split("@", 1))          # BTC@perp -> BTC/perp
        dst = os.path.join(args.data, ex, venue, rel)
        if os.path.exists(dst):
            actions.append(("archive", dst, os.path.join(archive_root, ex, venue, rel)))
        actions.append(("move", item["path"], dst))

    if args.archive_legacy:
        promoted = {a[2] for a in actions if a[0] == "move"}
        for ex in EXCHANGES:
            for item in list_assets(os.path.join(args.data, ex)):
                sym, path = item["symbol"], item["path"]
                if item["venue"] == "legacy" or not os.path.isfile(os.path.join(path, "manifest.json")):
                    if path in promoted:
                        continue
                    if not any(a[0] == "archive" and a[1] == path for a in actions):
                        actions.append(("archive", path, os.path.join(archive_root, ex, item["venue"], sym)))

    for kind, src, dst in actions:
        print(f"  {kind:7s} {src} -> {dst}")
        if args.apply:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
    if not args.apply:
        print("\n(dry-run) Đặt apply=True để thực hiện.")
    out = {"actions": [{"kind": k, "src": a, "dst": b} for k, a, b in actions], "applied": bool(args.apply)}
    write_job_result(out)
    return out
