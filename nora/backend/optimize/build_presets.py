"""Dựng data/alphas/presets.json — "bộ tham số tốt nhất" của từng chiến lược lõi (chế độ Cơ bản).

Ưu tiên nguồn: sổ đã chốt book.json -> lần build_strategy_book mới nhất có cấu hình qua cổng dev1 (stage A top-1 theo điểm) -> mặc định schema.
Chỉ đọc file có sẵn (không chạy backtest) nên nhẹ; vẫn nên chạy qua run_limited.sh cho đồng nhất.
Dùng (từ nora/):  backend/utils/ops/run_limited.sh --no-lock -- -m backend.optimize.build_presets [--out data/alphas/presets.json] [--dry-run]
"""
import argparse
import os
import sys

NORA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if NORA_ROOT not in sys.path:
    sys.path.insert(0, NORA_ROOT)

from backend.core.strategy import presets as pr  # noqa: E402


def _key_params(params, schema):
    """Chỉ các tham số khác mặc định (để bảng gọn)."""
    return {k: v for k, v in params.items() if v != schema[k]["default"]}


def format_table(doc):
    from backend.core.strategy.strategy_book import CANDIDATES
    lines = []
    for c in CANDIDATES:
        p = doc["presets"][c["id"]]
        ev = (p.get("evidence") or {}).get("dev1") or {}
        ev_txt = (f" | dev1 lãi {ev.get('ret_pct')}% MDD {ev.get('mdd_pct')}% sharpe {ev.get('sharpe')} lệnh {ev.get('trades')} "
                  f"+{ev.get('symbols_positive')}") if ev else ""
        full = p.get("evidence") or {}
        d2 = full.get("dev2_extreme") or {}
        ev_txt += (f" | dev2(extreme) lãi {d2.get('ret_pct')}% MDD {d2.get('mdd_pct')}% — "
                   f"{'ĐẠT' if str(full.get('dev2_pass', full.get('accepted'))) == 'True' else 'LOẠI'} dev2") if d2 else ""
        lines.append(f"{c['id']:18s} {p['source']}{ev_txt}")
        lines.append(f"{'':18s} khác mặc định: {_key_params(p['params'], c['params_schema']) or '(không — toàn bộ là mặc định)'}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="đường dẫn presets.json (mặc định data/alphas/presets.json hoặc NORA_PRESETS_PATH)")
    ap.add_argument("--book", default="", help="book.json (mặc định data/alphas/book.json)")
    ap.add_argument("--runs-dir", default="", help="thư mục các lần build (mặc định <data>/_cache/book)")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in bảng, không ghi file")
    a = ap.parse_args(argv)
    book = pr._read_json(a.book or pr.book_path())
    doc = pr.build_presets(book=book, runs_dir=a.runs_dir or None, use_book_file=False)
    print(format_table(doc))
    if not a.dry_run:
        print("ghi:", pr.write_presets(doc, a.out or None))
    return doc


if __name__ == "__main__":
    main()
