"""Bộ tham số tốt nhất ("preset") của từng chiến lược ứng viên — dùng cho chế độ Cơ bản của UI/API.

Nguồn:
  book    sổ đã chốt data/alphas/book.json (biến NORA_BOOK_PATH): tham số + bằng chứng dev1/dev2 của chiến lược trong sổ.
  stage_a lần chạy backend.optimize.book MỚI NHẤT trong data/_cache/book/ có cấu hình QUA CỔNG dev1 cho chiến lược đó:
          cấu hình có điểm BỀN cao nhất trên dev1 (điểm = lãi / MDD, trung bình cùng lân cận lưới; xem robust_scores).
  default giá trị mặc định của params_schema ("mặc định — chưa tối ưu"), không có bằng chứng, timeframe=None.
Có cả book lẫn stage_a: nguồn đã qua dev2 thắng; cùng mức thì bằng chứng mới hơn thắng (book: generated_at, stage_a: tên run).
Mỗi preset ghi `timeframe` = khung chạy lúc tối ưu (dữ liệu cũ không ghi -> "1m").
`params` của preset luôn ĐẦY ĐỦ mọi khoá của params_schema (khoá thiếu lấy mặc định) để UI hiển thị/sửa; khi chạy job chỉ cần phần khác mặc định
(api/modes.job_params). File xuất ra: data/alphas/presets.json (job presets_build = run_job cuối file này).
"""
import calendar
import json
import math
import os
import time
from typing import Any, Dict, List, Optional

from backend.utils.jsonsafe import json_default

PRESETS_VERSION = 1
SOURCE_DEFAULT = "mặc định — chưa tối ưu"
METRIC_KEYS = ("ret_pct", "mdd_pct", "sharpe", "trades", "win_pct", "symbols_positive", "halted_at")
NORA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def alphas_dir() -> str:
    return os.environ.get("NORA_ALPHAS_DIR") or os.path.join(NORA_DIR, "data", "alphas")


def book_path() -> str:
    return os.environ.get("NORA_BOOK_PATH") or os.path.join(alphas_dir(), "book.json")


def presets_path() -> str:
    return os.environ.get("NORA_PRESETS_PATH") or os.path.join(alphas_dir(), "presets.json")


def book_timeframe() -> str:
    book = _read_json(book_path())
    return (book or {}).get("timeframe", "1m") if isinstance(book, dict) else "1m"


def _metrics(m: Any) -> Optional[Dict[str, Any]]:
    return {k: m[k] for k in METRIC_KEYS if k in m} if isinstance(m, dict) else None


def _clean_params(candidate: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """Mặc định schema, ghi đè bằng khoá của `raw` thuộc schema (khoá lạ bị bỏ)."""
    from backend.core.strategy.book import schema_defaults
    schema = candidate["params_schema"]
    params = dict(schema_defaults(candidate))
    for key, value in (raw or {}).items():
        spec = schema.get(key)
        if spec is None or isinstance(value, bool):
            continue
        if spec["type"] == "choice":
            if value in spec["choices"]:
                params[key] = value
        elif isinstance(value, (int, float)) and math.isfinite(value):
            params[key] = int(value) if spec["type"] == "int" and float(value).is_integer() else value
    return params


def _read_json(path: str) -> Optional[Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _date_vi(ms: Any) -> Optional[str]:
    try:
        return time.strftime("%d/%m", time.gmtime(float(ms) / 1000.0))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _parse_book_time(book: Optional[Dict[str, Any]]) -> float:
    ts = book.get("generated_at") if isinstance(book, dict) else None
    return float(ts) / 1000.0 if isinstance(ts, (int, float)) else 0.0


def _parse_run_time(name: Optional[str]) -> float:
    """Tên thư mục run: YYYYMMDD_HHMMSS (UTC) -> giây epoch; tên khác -> 0."""
    try:
        return float(calendar.timegm(time.strptime((name or "")[:15], "%Y%m%d_%H%M%S")))
    except ValueError:
        return 0.0


def _evidence_time(preset: Dict[str, Any], book_ts: float) -> float:
    return book_ts if preset["source_kind"] == "book" else _parse_run_time(preset["evidence"].get("run"))


def _verified(preset: Dict[str, Any]) -> bool:
    """Sổ chỉ chứa chiến lược đã qua dev2; stage A thì xem dev2_verified (chỉ khi cấu hình bền nằm trong top-K đã kiểm dev2)."""
    return preset["source_kind"] == "book" or preset["evidence"].get("dev2_verified") is True


# ─── Nguồn 1: book.json ─────────────────────────────────────────────────────
def from_book(book: Optional[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(book, dict):
        return out
    by_id = {c["id"]: c for c in candidates}
    when = _date_vi(book.get("generated_at"))
    label = f"book.json (sổ đã build {when})" if when else "book.json"
    tf = book.get("timeframe", "1m")
    for s in book.get("strategies") or []:
        cand = by_id.get(s.get("id"))
        if cand is None:
            continue
        raw = {**(s.get("params") or {})}
        if book.get("risk_per_trade_pct") is not None:
            raw.setdefault("risk_per_trade_pct", book["risk_per_trade_pct"])
        ev = s.get("evidence") or {}
        top = (ev.get("dev1_top") or [{}])[0]
        out[cand["id"]] = {
            "params": _clean_params(cand, raw), "timeframe": tf, "source": label, "source_kind": "book",
            "evidence": {"stage": "book", "timeframe": tf, "accepted": ev.get("accepted"), "stability": ev.get("stability"),
                         "dev1_tried": ev.get("dev1_tried"), "dev1": _metrics(top.get("dev1")),
                         "dev2_level": _metrics(top.get("dev2_level")), "dev2_extreme": _metrics(top.get("dev2_extreme")),
                         "holdout_pass": book.get("holdout_pass"), "book_status": book.get("status")},
        }
    return out


# ─── Nguồn 2: lần build gần nhất có cấu hình qua cổng dev1 ───────────────────
def _passing_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows or []:
        sc = r.get("score")
        if isinstance(sc, (int, float)) and sc > float("-inf") and math.isfinite(sc):
            out.append(r)
    return out


def _bool(v: Any) -> Optional[bool]:
    """Báo cáo cũ lưu bool numpy thành chuỗi "True"/"False" (json default=str) -> bool thật; None giữ None."""
    if v is None or isinstance(v, bool):
        return v
    if v in ("True", "False"):
        return v == "True"
    return bool(v)


def _all_rows(run: str, cid: str, stage_a: Dict[str, Any]) -> List[Dict[str, Any]]:
    """MỌI cấu hình đã thử ở stage A của chiến lược (kho results.sqlite của lần dựng sổ; thiếu kho -> top-K trong stage_a.json).
    -> [{"params", "score" (None/-inf = trượt cổng dev1), "dev1"}]."""
    if os.path.isfile(os.path.join(run, "results.sqlite")):
        from backend.optimize.store import ResultsStore
        st = ResultsStore(run, read_only=True)
        try:
            rows = [{"params": r["params"], "score": r["score"], "dev1": r["metrics"]} for r in st.iter_rows("A", cid)]
        finally:
            st.close()
        if rows:
            return rows
    return list(stage_a.get(cid) or [])


def robust_scores(rows: List[Dict[str, Any]]) -> List[float]:
    """Điểm BỀN của từng cấu hình (chỉ dùng dev1): trung bình điểm của chính nó và mọi lân cận lưới (±1 bước trên đúng một khoá, lưới dựng
    từ các giá trị đã thử). Cấu hình trượt cổng / lân cận không có trong danh sách tính 0 — đỉnh nhọn giữa vùng trượt bị hạ điểm."""
    from backend.optimize.funnel.antiluck import neighbours
    def key(p):
        return json.dumps(p, sort_keys=True)
    space: Dict[str, List[Any]] = {}
    for r in rows:
        for k, v in (r.get("params") or {}).items():
            space.setdefault(k, [])
            if v not in space[k]:
                space[k].append(v)
    space = {k: sorted(v, key=lambda x: (isinstance(x, str), x)) for k, v in space.items() if len(v) > 1}
    sc = {}
    for r in rows:
        v = r.get("score")
        sc[key(r.get("params") or {})] = float(v) if isinstance(v, (int, float)) and math.isfinite(v) and v > 0 else 0.0
    out = []
    for r in rows:
        pts = [r.get("params") or {}] + neighbours(space, r.get("params") or {})
        out.append(sum(sc.get(key(p), 0.0) for p in pts) / len(pts))
    return out


def from_build_runs(runs_dir: str, candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Duyệt các lần chạy từ MỚI tới CŨ; mỗi chiến lược lấy lần chạy mới nhất có cấu hình qua cổng dev1. Chọn cấu hình qua cổng có ĐIỂM BỀN
    (robust_scores: trung bình cùng lân cận lưới) cao nhất — CHỈ dùng dev1. Không dùng dev2 để chọn: WFA kiểm trên dev2, chọn theo dev2 là rò rỉ.
    Kết quả dev2 của top-K (nếu cấu hình nằm trong đó) chỉ để hiển thị: dev2_verified True/False, hoặc None khi chưa có."""
    out: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(runs_dir):
        return out
    by_id = {c["id"]: c for c in candidates}
    todo = list(by_id)
    for name in sorted(os.listdir(runs_dir), reverse=True):
        if not todo:
            break
        run = os.path.join(runs_dir, name)
        stage_a = _read_json(os.path.join(run, "stage_a.json"))
        report = _read_json(os.path.join(run, "report.json"))
        if not isinstance(stage_a, dict) or not isinstance(report, dict):
            continue
        tf = report.get("timeframe", "1m")
        for cid in list(todo):
            rows = _all_rows(run, cid, stage_a)
            ok = [i for i, r in enumerate(rows) if _passing_rows([r])]
            if not ok:
                continue
            rob = robust_scores(rows)
            pick = max(ok, key=lambda i: rob[i])   # max ổn định: hoà -> cấu hình đứng trước
            best = rows[pick]
            entry = (report.get("candidates") or {}).get(cid) or {}
            top = next((t for t in entry.get("dev1_top") or [] if t.get("params") == best.get("params")), None)
            evidence = {"stage": "dev1", "run": name, "timeframe": tf, "dev1_tried": entry.get("dev1_tried"),
                        "score": round(float(best["score"]), 4), "robust_score": round(rob[pick], 4), "dev1": _metrics(best.get("dev1")),
                        "dev2_verified": _bool(top.get("dev2_pass")) if top is not None else None}
            if top is not None:   # có trong top-K: kèm kết quả dev2 (chỉ hiển thị)
                evidence.update(accepted=_bool(entry.get("accepted")), stability=entry.get("stability"),
                                dev2_pass=_bool(top.get("dev2_pass")), dev2_level=_metrics(top.get("dev2_level")),
                                dev2_extreme=_metrics(top.get("dev2_extreme")))
            out[cid] = {
                "params": _clean_params(by_id[cid], best.get("params") or {}), "timeframe": tf,
                "source": f"build {name} stage A bền vững dev1 (điểm cùng lân cận)", "source_kind": "stage_a", "evidence": evidence,
            }
            todo.remove(cid)
    return out


# ─── Dựng + đọc ─────────────────────────────────────────────────────────────
def build_presets(book: Optional[Dict[str, Any]] = None, runs_dir: Optional[str] = None,
                  use_book_file: bool = True) -> Dict[str, Any]:
    """Dựng bảng preset cho mọi chiến lược lõi (luật chọn nguồn: đầu file).
    book=None -> đọc book.json hiện hành; runs_dir=None -> data/_cache/book/."""
    from backend.core.strategy.book import CANDIDATES, schema_defaults
    if book is None and use_book_file:
        book = _read_json(book_path())
    if runs_dir is None:
        from backend.db.data_layout import cache_dir
        runs_dir = cache_dir(None, "book")
    book_items = from_book(book, CANDIDATES)
    stage_a_items = from_build_runs(runs_dir, CANDIDATES)
    book_ts = _parse_book_time(book)
    presets: Dict[str, Any] = {}
    for c in CANDIDATES:
        found = [p for p in (book_items.get(c["id"]), stage_a_items.get(c["id"])) if p]
        if found:   # qua dev2 trước; cùng mức thì bằng chứng mới hơn thắng (hoà -> book)
            presets[c["id"]] = max(found, key=lambda p: (_verified(p), _evidence_time(p, book_ts)))
        else:
            presets[c["id"]] = {"params": dict(schema_defaults(c)), "timeframe": None,
                                "source": SOURCE_DEFAULT, "source_kind": "default", "evidence": None}
    return {"version": PRESETS_VERSION, "generated_at": int(time.time() * 1000), "presets": presets}


def write_presets(doc: Dict[str, Any], path: Optional[str] = None) -> str:
    path = path or presets_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, default=json_default)
    os.replace(tmp, path)
    return path


def load_presets(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """{id: {params, timeframe, source, source_kind, evidence}} cho MỌI chiến lược lõi. Đọc presets.json; chiến lược thiếu/hỏng -> mặc định schema
    (không ghi file). File được kiểm lại theo schema hiện hành (khoá lạ bỏ, thiếu thì điền mặc định)."""
    from backend.core.strategy.book import CANDIDATES, schema_defaults
    doc = _read_json(path or presets_path())
    stored = (doc or {}).get("presets") if isinstance(doc, dict) else None
    stored = stored if isinstance(stored, dict) else {}
    out: Dict[str, Dict[str, Any]] = {}
    for c in CANDIDATES:
        p = stored.get(c["id"])
        if isinstance(p, dict) and isinstance(p.get("params"), dict):
            out[c["id"]] = {"params": _clean_params(c, p["params"]), "timeframe": p.get("timeframe"),
                            "source": p.get("source") or SOURCE_DEFAULT,
                            "source_kind": p.get("source_kind") or "default", "evidence": p.get("evidence")}
        else:
            out[c["id"]] = {"params": dict(schema_defaults(c)), "timeframe": None,
                            "source": SOURCE_DEFAULT, "source_kind": "default", "evidence": None}
    return out


# ─── Job dựng presets.json (POST /api/studio/strategies/presets) ────────────
def _key_params(params, schema):
    """Chỉ các tham số khác mặc định (để bảng gọn)."""
    return {k: v for k, v in params.items() if v != schema[k]["default"]}


def format_table(doc):
    from backend.core.strategy.book import CANDIDATES
    lines = []
    for c in CANDIDATES:
        p = doc["presets"][c["id"]]
        tf = p.get("timeframe")
        tf_label = f"[{tf}]" if tf else "[—]"
        ev = (p.get("evidence") or {}).get("dev1") or {}
        ev_txt = (f" | dev1 lãi {ev.get('ret_pct')}% MDD {ev.get('mdd_pct')}% sharpe {ev.get('sharpe')} lệnh {ev.get('trades')} "
                  f"+{ev.get('symbols_positive')}") if ev else ""
        full = p.get("evidence") or {}
        d2 = full.get("dev2_extreme") or {}
        ev_txt += (f" | dev2(extreme) lãi {d2.get('ret_pct')}% MDD {d2.get('mdd_pct')}% — "
                   f"{'ĐẠT' if full.get('dev2_pass', full.get('accepted')) is True else 'LOẠI'} dev2") if d2 else ""
        lines.append(f"{c['id']:18s} {tf_label} {p['source']}{ev_txt}")
        lines.append(f"{'':18s} khác mặc định: {_key_params(p['params'], c['params_schema']) or '(không — toàn bộ là mặc định)'}")
    return "\n".join(lines)


def run_job(params=None) -> Dict[str, Any]:
    """Dựng presets.json từ file có sẵn (không chạy backtest). params: out, book, runs_dir, dry_run."""
    from backend.utils.jobs import options, write_job_result
    a = options({"out": "", "book": "", "runs_dir": "", "dry_run": False}, params)
    doc = build_presets(book=_read_json(a.book or book_path()), runs_dir=a.runs_dir or None, use_book_file=False)
    print(format_table(doc))
    if not a.dry_run:
        print("ghi:", write_presets(doc, a.out or None))
    write_job_result(doc)
    return doc
