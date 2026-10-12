"""Chiến lược hệ thống (nạp từ file DSL), kiểm tham số/khung, presets (bộ tham số tốt nhất cho chế độ Cơ bản), alpha người dùng (lưu/phiên bản/checklist),
tài liệu thư viện chiến lược (catalog) và top agents.

Nguồn gộp: docs/bmad/p9_review_log.md (mục P9.6, P9.8, P9.9). Chiến lược hệ thống nạp từ file DSL (strategy_loader cũ) nằm ở đây.
"""
import functools
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Dict, Iterator, List, Optional, Tuple


from backend.signal.indicator import REGISTRY
from backend.metrics.charts import BETA_DRIVEN_ID
from backend.models.models import NORA_DIR
from backend.models.params import REGIME_MAP, materialize, regime_for, schema_defaults
from backend.alpha.compile import load_system_strategies
from backend.models.storage import alpha_dir as alphas_dir, alpha_dir as _alpha_dir, write_json_atomic
from backend.models.storage import options, read_json, write_job_result


# ══════════════════════════════════════════════════════════════════════════
# Chế độ chạy: Cơ bản (basic = preset khoá sẵn) / Nâng cao (advanced = mọi tham số chỉnh được, kiểm theo params_schema).
#
# Module thuần (không FastAPI): kiểm tham số theo params_schema của chiến lược, điền khoá thiếu từ preset, rút tham số tối thiểu cho job,
# và phân loại "custom_gates" (kết quả dùng ngưỡng gate khác chuẩn -> không được xuất bản/promote). Lớp API: backend/routes/modes.py.
# Mọi thông báo lỗi bằng tiếng Việt, gắn theo TRƯỜNG: [{"field": "strategies[0].params.sig.ema_fast", "message": "..."}].
# ══════════════════════════════════════════════════════════════════════════

# 6 kịch bản luôn có + 3 kịch bản trend thẳng đứng (chỉ có khi nguồn biết vị thế, vd. WFA — carlo.vertical_exposure)

FieldError = Tuple[str, str]       # (trường, thông báo)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _unit(spec: Dict[str, Any]) -> str:
    return f" {spec['unit']}" if spec.get("unit") else ""


def check_value(key: str, spec: Dict[str, Any], value: Any) -> Tuple[Any, Optional[str]]:
    """-> (giá trị đã chuẩn hoá, lỗi|None) cho một tham số theo spec của params_schema."""
    label = f"{spec['label_vi']} ({key})"
    if spec["type"] == "choice":
        if value not in spec["choices"] or not isinstance(value, str):
            return None, f"{label} phải là một trong {spec['choices']}, nhận {value!r}"
        return value, None
    if not _num(value):
        return None, f"{label} phải là số, nhận {value!r}"
    lo, hi = spec["min"], spec["max"]
    if spec["type"] == "int":
        if not float(value).is_integer():
            return None, f"{label} phải là số nguyên từ {lo} đến {hi}{_unit(spec)}, nhận {value!r}"
        value = int(value)
    else:
        value = float(value)
    if not lo <= value <= hi:
        return None, f"{label} phải nằm trong khoảng {lo} đến {hi}{_unit(spec)}, nhận {value!r}"
    return value, None


def validate_params(candidate: Dict[str, Any], params: Any, base: Dict[str, Any], prefix: str = "params") -> Tuple[Dict[str, Any], List[FieldError]]:
    """Kiểm `params` của một chiến lược theo params_schema (khoá lạ, kiểu, khoảng, khung thời gian, EMA nhanh < chậm, cột kernel, ngân sách DCA).
    Khoá thiếu lấy từ `base` (preset). -> (tham số ĐẦY ĐỦ đã chuẩn hoá, danh sách lỗi theo trường). Có lỗi thì tham số đầy đủ chưa đáng tin."""
    schema = candidate["params_schema"]
    cid = candidate["id"]
    errors: List[FieldError] = []
    if not isinstance(params, dict):
        return dict(base), [(prefix, f"{cid}: params phải là đối tượng {{khoá: giá trị}}, nhận {type(params).__name__}")]
    full = dict(base)
    for key, value in params.items():
        spec = schema.get(key)
        if spec is None:
            hint = f" (ý bạn là '{'sig.' + key}'?)" if "sig." + key in schema else ""
            errors.append((f"{prefix}.{key}", f"{cid}: tham số '{key}' không có trong chiến lược này{hint}; khoá hợp lệ: {list(schema)}"))
            continue
        norm, err = check_value(key, spec, value)
        if err:
            errors.append((f"{prefix}.{key}", f"{cid}: {err}"))
        else:
            full[key] = norm
    if errors:
        return full, errors
    fast, slow = full.get("sig.ema_fast"), full.get("sig.ema_slow")
    if fast is not None and slow is not None and fast >= slow:
        errors.append((f"{prefix}.sig.ema_fast", f"{cid}: EMA nhanh ({fast}) phải nhỏ hơn EMA chậm ({slow})"))
    if errors:
        return full, errors
    # Thay thử vào cây: bắt cột kernel/khung không hợp lệ (cùng kiểm tra lúc chạy thật) + ngân sách DCA của vị thế
    try:
        st = materialize(candidate, full)
        from backend.models.params import VENUE_COSTS, dca_budget_check
        budget = dca_budget_check(st["position"], VENUE_COSTS[("cex", "perp")])
        if not budget["ok"]:
            errors.append((prefix, f"{cid}: ngân sách DCA không đủ — cần {budget['need_pct']:.1f}% vốn, trần {budget['cap_pct']:.1f}%"))
    except ValueError as exc:
        errors.append((prefix, f"{cid}: {exc}"))
    return full, errors


# ─── Khung chạy (nến mô phỏng) ───────────────────────────────────────────────
def frame_keys(candidate: Dict[str, Any]) -> List[str]:
    """Khoá chọn KHUNG nến của chiến lược (sig.*_tf, atr_frame...): kiểu choice, mọi lựa chọn là khung."""
    from backend.models.params import FRAME_MS
    return [k for k, v in (candidate.get("params_schema") or {}).items()
            if v.get("type") == "choice" and set(v.get("choices") or []) <= set(FRAME_MS)]


def lift_frame(frame: str, base_frame: str, choices: List[str]) -> Optional[str]:
    """Khung >= khung chạy giữ nguyên; nhỏ hơn -> khung chạy nếu là lựa chọn hợp lệ, không thì None (không chạy được)."""
    from backend.models.params import FRAME_MS
    if FRAME_MS[frame] >= FRAME_MS[base_frame]:
        return frame
    return base_frame if base_frame in choices else None


def lift_frames(candidate: Dict[str, Any], params: Dict[str, Any], base_frame: str) -> Dict[str, Any]:
    """Tham số với mọi khung (kể cả mặc định schema) nâng lên >= khung chạy. ValueError nếu một khung không thể nâng."""
    if base_frame == "1m":
        return dict(params)
    out = dict(params)
    defaults = schema_defaults(candidate)
    for k in frame_keys(candidate):
        cur = out.get(k, defaults[k])
        new = lift_frame(cur, base_frame, list(candidate["params_schema"][k]["choices"]))
        if new is None:
            raise ValueError(f"{candidate['id']}: {k}={cur} nhỏ hơn khung chạy {base_frame} và không có lựa chọn >= {base_frame}")
        if new != cur or k in out:
            out[k] = new
    return out


# ══════════════════════════════════════════════════════════════════════════
# Dữ liệu sổ chiến lược (phần tham số vị thế đã ở models/params.py — RISK cũng ở đó vì signal/compute.py.build_plan cần)
#
# Sổ chiến lược (strategy book): tham số theo CHIẾN LƯỢC, không theo tài sản; vốn phân bổ theo RỦI RO.
#
# Nguyên tắc:
# - Một chiến lược = tín hiệu (AST trên kernel) + quản lý vị thế. Một bộ tham số dùng chung cho cả vũ trụ tài sản.
# - Thoát lệnh theo bội số ATR% (exit_unit="atr") để cùng tham số tự co giãn theo biến động từng tài sản:
#   stop_loss_rate=2 nghĩa là SL cách giá vào 2 × ATR%(khung atr_frame) đo ở nến đã đóng lúc có tín hiệu.
# - Khối lượng theo rủi ro (sizing="risk"): chạm SL mất ~risk_per_trade_pct% vốn; đòn bẩy tự hạ để thanh lý
#   cách giá vào >= 1,5 × khoảng SL; trần đòn bẩy 10x (mức rủi ro đã chốt).
# - Rủi ro danh mục (RiskConfig): số vị thế đồng thời, mỗi tài sản tối đa 1 vị thế, trần tổng danh nghĩa, kill switch 30%.
#
# Chọn chiến lược (run_book_build bên dưới) chạy trên CẢ vũ trụ cùng lúc (backtest danh mục), nên một
# cấu hình chỉ thắng nhờ một tài sản sẽ bị loại bởi điều kiện độ phủ (đa số tài sản phải có lãi).
#
# Chiến lược hệ thống = file Python DSL (P9.9): KEMA / Sideway / DCA (mỗi chiến lược một chân LONG và một chân SHORT; mỗi bộ tham số của một chân = một alpha;
# "Cả hai" = chạy cả hai chân) được VIẾT trong data/alpha/strategies/*.py (SimpleAlgorithm + p('tên', mặc_định, lo=, hi=, step=, grid=) cho tham số; nhãn/trợ giúp
# tiếng Việt nằm trong file). CANDIDATES / STRATEGIES / BY_ID bên dưới chỉ là góc nhìn trên kết quả biên dịch của load_system_strategies (cây khuôn, params_schema,
# space) — core không đọc file.
# ══════════════════════════════════════════════════════════════════════════

UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]


_LOADED = load_system_strategies()
CANDIDATES: List[Dict[str, Any]] = list(_LOADED["candidates"])
# Định nghĩa đăng ký thêm ngoài danh mục (test: chiến lược cũ của golden / kiểm parity). Không hiện ở API danh mục, không sinh alpha.
EXTRA_CANDIDATES: List[Dict[str, Any]] = []


def all_candidates() -> List[Dict[str, Any]]:
    """Danh mục + định nghĩa đăng ký thêm (đọc tại lúc gọi: test thay CANDIDATES / EXTRA_CANDIDATES vẫn có hiệu lực)."""
    return CANDIDATES + EXTRA_CANDIDATES


class _ById(Mapping):
    """{id: định nghĩa} của all_candidates(), tính tại lúc tra."""
    def _m(self) -> Dict[str, Dict[str, Any]]:
        return {c["id"]: c for c in all_candidates()}

    def __getitem__(self, key: str) -> Dict[str, Any]:
        return self._m()[key]

    def __iter__(self):
        return iter(self._m())

    def __len__(self) -> int:
        return len(self._m())


BY_ID: Mapping = _ById()

STRATEGIES: List[Dict[str, Any]] = list(_LOADED["strategies"])
SOURCES: Dict[str, Dict[str, str]] = dict(_LOADED["sources"])   # {id chân: {file, sha256, code_hash}} — nguồn gốc file của từng chiến lược

REGIME_MAP.update({c["id"]: regime_for(c["side"]) for c in CANDIDATES})   # REGIME_MAP (dict) do models/params.py giữ; điền ở đây


def reload_system_strategies() -> Dict[str, Any]:
    """Nạp lại data/alpha/strategies/*.py (cache mtime+size tự vô hiệu) và làm mới CANDIDATES / STRATEGIES / SOURCES / REGIME_MAP TẠI CHỖ
    (các nơi đã giữ tham chiếu tới danh sách vẫn thấy mã mới). Lượt backtest / sổ / phễu chạy SAU ĐÓ dùng mã mới. Lỗi biên dịch -> DslError, trạng thái cũ giữ nguyên."""
    loaded = load_system_strategies()
    old_ids = {c["id"] for c in CANDIDATES}
    CANDIDATES[:] = list(loaded["candidates"])
    STRATEGIES[:] = list(loaded["strategies"])
    SOURCES.clear()
    SOURCES.update(loaded["sources"])
    for gone in old_ids - {c["id"] for c in CANDIDATES}:
        REGIME_MAP.pop(gone, None)
    REGIME_MAP.update({c["id"]: regime_for(c["side"]) for c in CANDIDATES})
    return loaded


def perp_symbols(universe: List[str] = None) -> List[str]:
    return [f"{s}@perp" for s in (universe or UNIVERSE)]


def configs(candidate, n, seed, lazy=False):
    """Danh sách cấu hình (như cũ). lazy=True -> trả generator (không dựng lưới/danh sách) cho không gian rất lớn."""
    gen = iter_params(candidate["space"], n, seed)
    return gen if lazy else list(gen)


def strip_metrics(m, also=()):
    """Bỏ khoá nội bộ/nặng (chuỗi ngày, RSS) khỏi số đo trước khi ghi ra file; `also` = khoá bỏ thêm. MỘT định nghĩa cho build + tasks."""
    drop = ("daily", "_peak_rss_mb", "_rss_anon_mb") + tuple(also)
    return {k: v for k, v in m.items() if k not in drop}


# ══════════════════════════════════════════════════════════════════════════
# Bộ tham số tốt nhất ("preset") của từng chiến lược ứng viên — dùng cho chế độ Cơ bản của UI/API.
#
# Nguồn:
#   book    sổ đã chốt data/alpha/book.json (biến NORA_BOOK_PATH): tham số + bằng chứng dev1/dev2 của chiến lược trong sổ.
#   default giá trị mặc định của params_schema ("mặc định — chưa tối ưu"), không có bằng chứng, timeframe=None.
# Mỗi preset ghi `timeframe` = khung chạy lúc tối ưu (dữ liệu cũ không ghi -> "1m").
# `params` của preset luôn ĐẦY ĐỦ mọi khoá của params_schema (khoá thiếu lấy mặc định) để UI hiển thị/sửa; khi chạy job chỉ cần phần khác mặc định
# (routes/modes.job_params). File xuất ra: data/alpha/presets.json (job presets_build = run_job cuối file này).
# ══════════════════════════════════════════════════════════════════════════

PRESETS_VERSION = 1
SOURCE_DEFAULT = "mặc định — chưa tối ưu"
METRIC_KEYS = ("ret_pct", "mdd_pct", "sharpe", "trades", "win_pct", "symbols_positive", "halted_at")


def book_path() -> str:
    return os.environ.get("NORA_BOOK_PATH") or os.path.join(alphas_dir(), "book.json")


def presets_path() -> str:
    return os.environ.get("NORA_PRESETS_PATH") or os.path.join(alphas_dir(), "presets.json")


def book_timeframe() -> str:
    book = read_json(book_path())
    return (book or {}).get("timeframe", "1m") if isinstance(book, dict) else "1m"


def metrics_row(m: Any) -> Optional[Dict[str, Any]]:
    return {k: m[k] for k in METRIC_KEYS if k in m} if isinstance(m, dict) else None


def _clean_params(candidate: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """Mặc định schema, ghi đè bằng khoá của `raw` thuộc schema (khoá lạ bị bỏ)."""
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


def _date_vi(ms: Any) -> Optional[str]:
    try:
        return time.strftime("%d/%m", time.gmtime(float(ms) / 1000.0))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


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
                         "dev1_tried": ev.get("dev1_tried"), "dev1": metrics_row(top.get("dev1")),
                         "dev2_level": metrics_row(top.get("dev2_level")), "dev2_extreme": metrics_row(top.get("dev2_extreme")),
                         "holdout_pass": book.get("holdout_pass"), "book_status": book.get("status")},
        }
    return out


# ─── Dựng + đọc ─────────────────────────────────────────────────────────────
def build_presets(book: Optional[Dict[str, Any]] = None, use_book_file: bool = True) -> Dict[str, Any]:
    """Dựng bảng preset cho mọi chiến lược lõi: tham số trong sổ (book.json) nếu có, không thì mặc định của params_schema.
    book=None -> đọc book.json hiện hành."""
    if book is None and use_book_file:
        book = read_json(book_path())
    book_items = from_book(book, CANDIDATES)
    presets: Dict[str, Any] = {}
    for c in CANDIDATES:
        presets[c["id"]] = book_items.get(c["id"]) or {"params": dict(schema_defaults(c)), "timeframe": None,
                                                        "source": SOURCE_DEFAULT, "source_kind": "default", "evidence": None}
    return {"version": PRESETS_VERSION, "generated_at": int(time.time() * 1000), "presets": presets}


def write_presets(doc: Dict[str, Any], path: Optional[str] = None) -> str:
    path = path or presets_path()
    write_json_atomic(path, doc, indent=1)
    return path


def load_presets(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """{id: {params, timeframe, source, source_kind, evidence}} cho MỌI chiến lược lõi. Đọc presets.json; chiến lược thiếu/hỏng -> mặc định schema
    (không ghi file). File được kiểm lại theo schema hiện hành (khoá lạ bỏ, thiếu thì điền mặc định)."""
    doc = read_json(path or presets_path())
    stored = (doc or {}).get("presets") if isinstance(doc, dict) else None
    stored = stored if isinstance(stored, dict) else {}
    out: Dict[str, Dict[str, Any]] = {}
    for c in all_candidates():      # cả chiến lược cũ: sổ / lượt phễu đã có vẫn đọc được
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


def run_presets_build(params=None) -> Dict[str, Any]:
    """Dựng presets.json từ file có sẵn (không chạy backtest). params: out, book, dry_run."""
    a = options({"out": "", "book": "", "dry_run": False}, params)
    doc = build_presets(book=read_json(a.book or book_path()), use_book_file=False)
    print(format_table(doc))
    if not a.dry_run:
        print("ghi:", write_presets(doc, a.out or None))
    write_job_result(doc)
    return doc


# ─── Lấy mẫu cấu hình tham số ──────────────────────────────────────────────

def grid_size(space: Dict[str, List[Any]]) -> int:
    total = 1
    for k in space:
        total *= len(space[k])
    return total


def iter_params(space: Dict[str, List[Any]], n: Optional[int], seed: int, full_grid: bool = False) -> Iterator[Dict[str, Any]]:
    """Sinh lười từng bộ tham số: full_grid hoặc n >= kích thước lưới -> toàn lưới (thứ tự product theo khoá sắp xếp); ngược lại n vị trí ngẫu nhiên không lặp."""
    keys = sorted(space)
    sizes = [len(space[k]) for k in keys]
    total = grid_size(space)
    if full_grid or n is None or total <= n:
        positions = range(total)
    elif total <= sys.maxsize:
        positions = random.Random(seed).sample(range(total), int(n))
    else:   # không gian khổng lồ (> 2^63): rút ngẫu nhiên không lặp
        rng = random.Random(seed)

        def _draw():
            seen = set()
            while len(seen) < n:
                x = rng.randrange(total)
                if x not in seen:
                    seen.add(x)
                    yield x
        positions = _draw()
    for pos in positions:
        vals, r = [], pos
        for k, sz in zip(reversed(keys), reversed(sizes)):
            r, m = divmod(r, sz)
            vals.append(space[k][m])
        vals.reverse()
        yield dict(zip(keys, vals))


# ═══ Alpha người dùng, tài liệu thư viện chiến lược, top agents, phiên bản engine của sổ ═══


# ══════════════════════════════════════════════════════════════════════════
# Phiên bản ENGINE (một nguồn duy nhất) cho sổ chiến lược: sổ nào dựng bằng engine khác engine hiện hành thì kết quả (lãi/MDD/bằng chứng) trong sổ
# có thể không còn tái lập được -> giao diện cảnh báo "cần dựng lại".
#
# engine_version() = {"hash": sha256 của ĐẦU VÀO KẾT QUẢ, "commit": git HEAD ngắn, "dirty": có thay đổi chưa commit trong các đầu vào đó, "files": số đầu vào}.
# Đầu vào kết quả (engine_inputs) = (a) file tính toán của engine: backend/signal/*.py + backend/models/*.py + jobs/evaluate.py (băm byte file), (b) MỖI chiến lược hệ thống: băm IR đã biên dịch
# (cây tín hiệu/stop/position/space của từng chân qua alpha loader) — KHÔNG băm byte file .py nên sửa chú thích/docstring/khoảng trắng không đổi; sửa logic thì đổi.
# Đánh đổi: alpha/compile.py vẫn là trình biên dịch nhưng không băm file; ta băm KẾT QUẢ biên dịch (IR) nên refactor compiler không đổi IR thì không bật cờ, còn sửa compiler làm IR đổi
# thì bật cờ. alpha/contract.py (trợ giúp/gợi ý/sổ tay) không ảnh hưởng kết quả nên không nằm trong. So sánh chỉ dùng `hash`; `commit` để người đọc biết sổ dựng ở đâu.
# Cùng hàm cho mọi nơi ghi (strategies.py.build_book) và đọc (API). Nhớ theo (đường dẫn, mtime_ns, size) của file engine + file chiến lược -> không đọc lại mỗi request.
# ══════════════════════════════════════════════════════════════════════════

ENGINE_COMPUTE_FILES = ("backend/jobs/evaluate.py", "backend/alpha/plan.py")    # ngoài backend/{nautilus,models,signal}/*.py (compile/contract không ảnh hưởng kết quả)
REASON_NO_VERSION = "sổ dựng trước khi có phiên bản engine"

GIT_TTL_S = 60.0   # commit / dirty đổi mà không đổi file (git commit) -> làm tươi sau tối đa ngần này giây; hash không phụ thuộc git
_cache: Dict[str, Any] = {"sig": None, "value": None, "at": 0.0}


def _engine_files() -> List[Tuple[str, str]]:
    rels = []
    for d in ["backend/nautilus", "backend/models", "backend/signal"]:
        dp = os.path.join(NORA_DIR, d)
        if os.path.isdir(dp):
            rels.extend([f"{d}/{n}" for n in sorted(os.listdir(dp)) if n.endswith(".py") and n != "__init__.py"])
    rels += list(ENGINE_COMPUTE_FILES)
    return [(rel, os.path.join(NORA_DIR, rel)) for rel in rels if os.path.isfile(os.path.join(NORA_DIR, rel))]


def _strategy_ir_hashes() -> List[Tuple[str, str]]:
    """[(chân chiến lược, sha256 của IR biên dịch)] — chỉ phần ảnh hưởng kết quả (bỏ mô tả/nhãn/lược đồ tham số)."""
    from backend.alpha.compile import load_system_strategies
    out = []
    for c in load_system_strategies()["candidates"]:
        ir = {k: c.get(k) for k in ("id", "side", "tree", "stop", "position", "space")}
        out.append((f"strategy:{c['id']}", hashlib.sha256(json.dumps(ir, sort_keys=True, default=repr).encode("utf-8")).hexdigest()))
    return out


def engine_inputs() -> List[str]:
    """Danh sách tên đầu vào được băm (dùng cho lời giải thích)."""
    return [rel for rel, _ in _engine_files()] + [n for n, _ in _strategy_ir_hashes()]


def _git(*args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", NORA_DIR, *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:   # noqa: BLE001  (git thiếu / bị monkeypatch trong test / không phải repo: commit chỉ để tham khảo, hash mới là so sánh)
        return None


def engine_version() -> Dict[str, Any]:
    from backend.alpha.compile import strategy_files
    files = _engine_files()
    sfiles = strategy_files()
    sig = tuple((p, os.stat(p).st_mtime_ns, os.stat(p).st_size) for p in [p for _, p in files] + sfiles)
    if _cache["sig"] == sig and time.time() - _cache["at"] < GIT_TTL_S:
        return dict(_cache["value"])
    from backend.nautilus.version import NAUTILUS_VERSION
    h = hashlib.sha256(f"nautilus {NAUTILUS_VERSION}\0".encode("utf-8"))   # nâng Nautilus -> sổ dựng bằng bản cũ cần dựng lại
    for rel, p in files:
        with open(p, "rb") as fh:
            h.update(rel.encode("utf-8") + b"\0" + fh.read() + b"\0")
    irs = _strategy_ir_hashes()
    for name, d in irs:
        h.update(name.encode("utf-8") + b"\0" + d.encode("ascii") + b"\0")
    status = _git("status", "--porcelain", "--", *[rel for rel, _ in files], *[os.path.relpath(p, NORA_DIR) for p in sfiles])
    value = {"hash": h.hexdigest(), "commit": _git("rev-parse", "--short", "HEAD"), "dirty": (bool(status) if status is not None else None),
             "files": len(files) + len(irs)}
    _cache.update(sig=sig, value=value, at=time.time())
    return dict(value)


def _rebuild_reason(stored: Dict[str, Any], cur: Dict[str, Any]) -> str:
    inputs = engine_inputs()
    core = [i for i in inputs if not i.startswith("strategy:")]
    strat = [i[len("strategy:"):] for i in inputs if i.startswith("strategy:")]
    return (f"đầu vào kết quả của engine ({', '.join(core)}; IR chiến lược: {', '.join(strat)}) đã đổi từ khi dựng sổ: dựng ở commit {stored.get('commit') or '?'} "
            f"(hash {stored['hash'][:8]}), hiện là commit {cur.get('commit') or '?'} (hash {cur['hash'][:8]})")


def book_engine_status(book: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{"stored": engine_version lúc dựng | None, "current", "needs_rebuild", "reason"}. Sổ chưa có engine_version -> needs_rebuild True + REASON_NO_VERSION.
    book=None (chưa có sổ) -> needs_rebuild None (không có gì để dựng lại)."""
    cur = engine_version()
    if book is None:
        return {"stored": None, "current": cur, "needs_rebuild": None, "reason": "chưa có sổ"}
    stored = book.get("engine_version")
    if not isinstance(stored, dict) or not stored.get("hash"):
        return {"stored": None, "current": cur, "needs_rebuild": True, "reason": REASON_NO_VERSION}
    if stored["hash"] != cur["hash"]:
        return {"stored": stored, "current": cur, "needs_rebuild": True, "reason": _rebuild_reason(stored, cur)}
    return {"stored": stored, "current": cur, "needs_rebuild": False, "reason": None}


# ══════════════════════════════════════════════════════════════════════════
# Kho alpha (C3) + xuất cấu hình cho Binance Futures testnet (D).
#
# Kho alpha = các bộ (chiến lược × tài sản × tham số) đã qua ĐỦ gate của (phễu đã gỡ):
# WFA (OOS) + Monte Carlo (cháy <= 5%) + holdout 20% cuối có lãi và MDD <= 30%, đòn bẩy <= 10x.
# Mỗi mục ghi đủ để tái lập: template, tham số, AST đã thay tham số, số liệu từng giai đoạn,
# sha256 dữ liệu 1m, commit code tại thời điểm tối ưu.
#
# Cấu hình testnet mô tả ĐÚNG những gì engine đã mô phỏng (không thêm hành vi mới):
# - Tín hiệu đánh giá trên nến ĐÃ ĐÓNG; vào lệnh MARKET ở đầu phút kế tiếp (taker).
# - Tầng DCA: lệnh LIMIT post-only (GTX, maker) cách giá khớp tầng trước dca_step_pct.
# - Chốt lời: LIMIT reduce-only (maker) tại giá TB × (1 ± tp%). Cắt lỗ: STOP_MARKET reduce-only từ giá TB.
# - Trailing / timeout / tín hiệu thoát: đóng MARKET (taker). Ký quỹ ISOLATED.
# Tick size / step size / min notional phải lấy từ /fapi/v1/exchangeInfo lúc chạy bot.
#
# Sổ chiến lược: ghi book.json / testnet, xuất bản (book_export):
# Xuất sổ chiến lược đã chốt: data/alpha/book.json (tái lập backtest) + data/alpha/testnet/book.json (bot Binance Futures testnet).
#
# Cấu hình testnet mô tả ĐÚNG hành vi đã mô phỏng trong PortfolioEngine:
# - Tín hiệu trên nến đã đóng -> vào MARKET đầu phút kế tiếp; ATR% = natr(atr_period) của nến atr_frame đã đóng.
# - Khoảng SL = stop_loss_rate × ATR%; danh nghĩa = vốn × risk_per_trade% / (SL% + 2 × (taker + trượt)),
#   chặn bởi max_notional_pct% vốn và phần còn lại của trần tổng danh nghĩa (max_gross_exposure × vốn).
# - Đòn bẩy = min(max_leverage, floor(1 / (1,5 × SL + mmr))) — giá thanh lý luôn cách xa hơn SL; ký quỹ ISOLATED.
# - SL STOP_MARKET reduce-only; trailing (bội số ATR) đóng MARKET; TP LIMIT reduce-only (nếu có); timeout đóng MARKET.
# - Giới hạn danh mục: max_positions, max_per_symbol, kill switch khi vốn MTM sụt kill_switch_dd_pct% từ đỉnh.
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# Xuất bản & Thăng hạng Alpha từ phễu (promote_alpha, build_report, book_source)
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# Kiểm lại một alpha trong kho (data/alpha/registry.json) bằng ENGINE HIỆN HÀNH theo đúng các cổng của phễu (job API `alpha_revalidate`).
#
# Alpha cũ (vd. trend_long_perp__SOL) được dựng bằng đường tối ưu đơn tài sản đã xoá (P0.11a) và engine trước P1, nên bằng chứng trong kho
# không còn tái lập được. Job này chạy lại đúng cây tín hiệu + tham số vị thế đã lưu (flows[0].ast + position) trên tài sản của alpha:
#   S3  WFA tham số cố định trên dev2 (fold train/test của phễu; IS = level, kill tắt; OOS = extreme, kill bật) -> gates.evaluate_s3
#   S5  hệ số khối lượng s lớn nhất trong [S5_S_MIN, 1] mà MC (>= 10.000 kịch bản + kịch bản cực xấu + trend thẳng đứng) qua -> sizing.search_scale
#   S6  holdout một lần ở hệ số s (level + extreme, kill bật) -> gates.evaluate_s6
# Kết luận: "validated" (kèm final_scale) hoặc "retired" (kèm mã + lý do). apply=True: ghi status/revalidation vào registry; alpha bị loại thì
# cấu hình testnet của nó chuyển sang data/alpha/testnet/_retired/ (giữ lại để tra cứu, bot không còn đọc).
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# Quản lý Alpha người dùng (C1 — lưu trữ, xác minh, checklist, catalog).
#
# Kho lưu trữ: models/storage.alpha_user_dir()/<alpha_id>.json (đường dẫn đặt MỘT chỗ: get_user_alphas_dir; thư mục job: batch.jobs_root())
# alpha_id = sha1(program_hash + cấu hình chạy)[:12]
# Bản ghi = code + program_hash + config + ảnh chụp đầy đủ kết quả (`result`) + `evidence`, đã xác minh trực tiếp từ job_id (chống giả mạo từ client).
# Chạy ở /alpha/create và /education chỉ là TẠM THỜI (job_ttl dọn sau 24 h nếu không được lưu); chỉ lệnh Lưu mới ghi vào đây.
# Vòng đời: SAVED -> CANDIDATE -> ARCHIVED
# ══════════════════════════════════════════════════════════════════════════

def get_user_alphas_dir(base_dir: Optional[str] = None) -> str:
    if base_dir:
        return os.path.join(base_dir, "user")
    from backend.models.storage import alpha_user_dir
    return alpha_user_dir()


def generate_alpha_id(program_hash: str, config: Dict[str, Any]) -> str:
    """Tạo mã alpha_id bất biến: sha1(program_hash + canonical config)[:12]."""
    canon = {
        "symbols": sorted(config.get("symbols") or []),
        "start": config.get("start"),
        "end": config.get("end"),
        "train_ratio": config.get("train_ratio"),
        "initial_capital": config.get("initial_capital"),
        "timeframe": config.get("timeframe"),
        "position": config.get("position"),
    }
    raw = f"{program_hash}:{json.dumps(canon, sort_keys=True)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _num_or_none(v: Any) -> Optional[float]:
    """Số hữu hạn (kể cả 0) hoặc None — không bao giờ thay thiếu bằng 0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _first_num(block: Any, *keys: str) -> Optional[float]:
    for k in keys:
        n = _num_or_none((block or {}).get(k)) if isinstance(block, dict) else None
        if n is not None:
            return n
    return None


def _item(item_id: str, label: str, state: str, value: str, required: str) -> Dict[str, Any]:
    """state: pass | fail | missing. `passed` = True | False | None (thiếu dữ liệu: không đạt cũng không trượt)."""
    return {"id": item_id, "label": label, "state": state, "passed": {"pass": True, "fail": False}.get(state), "value": value, "required": required}


MISSING_VI = "không có dữ liệu"


def evaluate_checklist(result: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra 5 tiêu chí trước khi lưu (chỉ cảnh báo, không chặn). Nguồn DUY NHẤT của checklist: giao diện chỉ hiển thị.
    - >= 20 lệnh đóng
    - có giai đoạn test
    - Sharpe test > 0 (metrics.test.sharpe, năm = 365 ngày)
    - MDD < 50% (metrics.simulate.mdd_pct, đã là %)
    - không phải thuần beta (insight beta_driven)
    Đầu vào thiếu -> state "missing" (không đạt cũng không trượt), không bao giờ ngầm coi là 0."""
    metrics = result.get("metrics") or {}
    trades = result.get("trades")
    n_trades = len(trades) if isinstance(trades, list) else None

    has_test = bool(metrics.get("test"))
    test_sharpe = _first_num(metrics.get("test"), "sharpe")
    mdd_pct = _first_num(metrics.get("simulate"), "mdd_pct")
    if mdd_pct is not None:
        mdd_pct = abs(mdd_pct)

    insights = result.get("insights")
    has_beta_driven = any(isinstance(i, dict) and i.get("id") == BETA_DRIVEN_ID for i in insights) if isinstance(insights, list) else None

    items = [
        _item("trades_ge_20", "Tối thiểu 20 lệnh giao dịch",
              "missing" if n_trades is None else ("pass" if n_trades >= 20 else "fail"),
              MISSING_VI if n_trades is None else f"{n_trades} lệnh", "≥ 20 lệnh"),
        _item("has_test_stage", "Có kiểm định ngoài mẫu (Out-Of-Sample)", "pass" if has_test else "fail", "Đã chạy" if has_test else "Chưa có", "Có giai đoạn test"),
        _item("test_sharpe_positive", "Sharpe ngoài mẫu dương (Sharpe Test > 0)",
              "missing" if test_sharpe is None else ("pass" if test_sharpe > 0.0 else "fail"),
              MISSING_VI if test_sharpe is None else f"{test_sharpe:.2f}", "> 0.0"),
        _item("mdd_under_50", "Mức sụt giảm tối đa dưới 50% (MDD < 50%)",
              "missing" if mdd_pct is None else ("pass" if mdd_pct < 50.0 else "fail"),
              MISSING_VI if mdd_pct is None else f"{mdd_pct:.1f}%", "< 50%"),
        _item("not_pure_beta", "Không phụ thuộc thuần túy vào thị trường (Beta-driven)",
              "missing" if has_beta_driven is None else ("fail" if has_beta_driven else "pass"),
              MISSING_VI if has_beta_driven is None else ("Cảnh báo beta" if has_beta_driven else "Độc lập"), f"Không kích hoạt {BETA_DRIVEN_ID}"),
    ]
    return {"all_passed": all(it["state"] == "pass" for it in items), "n_missing": sum(1 for it in items if it["state"] == "missing"), "items": items}


# ─── Lưu / đọc ──────────────────────────────────────────────────────────────

SNAPSHOT_REQUIRED = ("config", "metrics", "program_hash")


def git_commit() -> Optional[str]:
    """Commit git ngắn của HEAD (None nếu không đọc được) — bằng chứng/nguồn gốc kết quả; MỘT định nghĩa cho job + bản ghi alpha."""
    return _git("rev-parse", "--short", "HEAD")


def build_evidence(result: Dict[str, Any], job_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    data = result.get("data") or {}
    return {"job_id": job_id, "program_hash": result.get("program_hash"), "data_source": data.get("source"), "data_sha256_1m": data.get("sha256_1m"),
            "git_commit": git_commit(), "job_created": job.get("created"), "job_finished": job.get("finished"), "engine": "custom_run (PortfolioEngine)"}


def save_user_alpha(job_id: str, code: str, name: str, note: str = "", source: str = "alpha-create",
                    base_dir: Optional[str] = None, alpha_id: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """Xác thực và lưu trữ bản ghi Alpha người dùng (lần lưu DUY NHẤT; chạy ở /alpha/create và /education chỉ là tạm thời):
    - Đọc kết quả job thật từ máy chủ (job.status == 'done'), KHÔNG nhận kết quả từ client
    - Kiểm tra mã băm chương trình khớp với code gửi lên (chống giả mạo)
    - Ghi ảnh chụp ĐẦY ĐỦ kết quả (`result`) + `explain` + `evidence` nên bản ghi không còn phụ thuộc thư mục job
    - Trả về (record, action: 'created' | 'updated' | 'versioned'); chương trình (program_hash) đã được lưu -> ValueError (API 409), không nhân bản
    - `alpha_id` (P10): lưu PHIÊN BẢN MỚI của alpha đã có (sửa code trong trình soạn tạm -> chạy lại -> Lưu): giữ id, bản ghi cũ nguyên vẹn được
      chuyển vào user/_versions/<id>.v<n>.json, bản ghi chính nhận code + kết quả + bằng chứng mới với version = n + 1
    """
    from backend.jobs import runner as batch

    job = batch.status(job_id)
    if not job:
        if batch.ephemeral_gone(job_id):
            raise batch.EphemeralGone(job_id)
        raise ValueError(f"Không tìm thấy job_id {job_id}")
    if job.get("status") != "done":
        raise ValueError(f"Job {job_id} chưa hoàn tất (trạng thái: {job.get('status')})")

    result = job.get("result")
    if not result:
        raise ValueError(f"Job {job_id} không có dữ liệu result.json")
    lacking = [k for k in SNAPSHOT_REQUIRED if not result.get(k)]
    if lacking or not (result.get("metrics") or {}).get("simulate"):
        raise ValueError(f"Kết quả job {job_id} thiếu {lacking or ['metrics.simulate']}: không đủ để lưu")

    # Kiểm tra program_hash
    from backend.alpha.compile import compile_code
    prog = compile_code(code, register=False)
    if result.get("program_hash") != prog.code_hash:
        raise ValueError(f"Mã băm chương trình không khớp (kết quả job: {result.get('program_hash')}, code hiện tại: {prog.code_hash})")

    config = result.get("config", {})
    user_dir = get_user_alphas_dir(base_dir)
    os.makedirs(user_dir, exist_ok=True)
    versioned = alpha_id is not None
    if versioned:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alpha_id) or not os.path.isfile(os.path.join(user_dir, f"{alpha_id}.json")):
            raise LookupError(f"Không tìm thấy alpha {alpha_id} để lưu phiên bản mới")
    else:
        alpha_id = generate_alpha_id(prog.code_hash, config)
    for ex in list_user_alphas(base_dir=base_dir):      # chương trình này (program_hash) đã được lưu rồi -> không lưu trùng (API trả 409)
        if ex.get("program_hash") == prog.code_hash:
            raise ValueError(f"Chiến lược này đã được lưu (alpha {ex.get('id')}: “{ex.get('name') or ex.get('id')}”). Hãy sửa code hoặc tham số rồi chạy lại để lưu bản khác.")
    checklist = evaluate_checklist(result)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")

    action = "versioned" if versioned else ("updated" if os.path.isfile(file_path) else "created")
    now_iso = datetime.now(timezone.utc).isoformat()

    old_record = {}
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                old_record = json.load(fh)
        except Exception:
            pass

    explain = None
    try:
        from backend.alpha.compile import explain_program
        explain = explain_program(prog, position=config.get("position"))
    except Exception:      # noqa: BLE001 — giải thích là phần phụ; thiếu thì null
        explain = None

    snapshot = {k: v for k, v in result.items() if k not in ("checklist",)}
    snapshot["checklist"] = checklist
    record: Dict[str, Any] = {
        "id": alpha_id,
        "name": name.strip(),
        "note": (note or "").strip(),
        "source": source,
        "status": old_record.get("status", "SAVED"),
        "created_at": old_record.get("created_at", now_iso),
        "updated_at": now_iso,
        "code": code,
        "program_hash": prog.code_hash,
        "config": config,
        "metrics": result.get("metrics", {}),
        "checklist": checklist,
        "data_sha": (result.get("data") or {}).get("sha256_1m"),
        "job_id": job_id,
        "final_equity": result.get("final_equity"),
        "evidence": build_evidence(result, job_id, job),
        "explain": explain,
        "result": snapshot,       # ảnh chụp đầy đủ: metrics, yearly, series (stages + benchmark), trades, diagnostics, insights, by_symbol, warnings...
    }
    if versioned:
        prev_v = int(old_record.get("version") or 1)
        history = list(old_record.get("versions") or [_version_row(old_record, prev_v)])
        vdir = os.path.join(user_dir, "_versions")
        os.makedirs(vdir, exist_ok=True)
        write_json_atomic(os.path.join(vdir, f"{alpha_id}.v{prev_v}.json"), old_record, indent=1, clean=True, allow_nan=False)     # bản cũ nguyên vẹn (kể cả kết quả) để so sánh
        record["version"] = prev_v + 1
        record["versions"] = history + [_version_row(record, prev_v + 1)]
    else:
        record["version"] = int(old_record.get("version") or 1)
        if old_record.get("versions"):
            record["versions"] = old_record["versions"]
    write_json_atomic(file_path, record, indent=1, clean=True, allow_nan=False)
    return record, action


def _version_row(rec: Dict[str, Any], version: int) -> Dict[str, Any]:
    return {"version": version, "saved_at": rec.get("updated_at"), "program_hash": rec.get("program_hash"), "job_id": rec.get("job_id"), "name": rec.get("name")}


def list_user_alpha_versions(alpha_id: str, base_dir: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """[{version, saved_at, program_hash, job_id, name}] gồm bản hiện tại; None nếu không có alpha."""
    rec = get_user_alpha(alpha_id, base_dir)
    if not rec:
        return None
    return list(rec.get("versions") or [_version_row(rec, int(rec.get("version") or 1))])


def get_user_alpha_version(alpha_id: str, version: int, base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Bản ghi đầy đủ của phiên bản `version` (bản hiện tại hoặc user/_versions/<id>.v<n>.json)."""
    rec = get_user_alpha(alpha_id, base_dir)
    if not rec:
        return None
    if int(rec.get("version") or 1) == version:
        return rec
    path = os.path.join(get_user_alphas_dir(base_dir), "_versions", f"{alpha_id}.v{int(version)}.json")
    return read_json(path) if os.path.isfile(path) else None


_HEAVY = ("result", "explain")


def _summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Bản ghi gọn cho danh sách: bỏ ảnh chụp kết quả + giải thích (lấy bằng GET /user/{id})."""
    out = {k: v for k, v in rec.items() if k not in _HEAVY}
    out["has_result"] = isinstance(rec.get("result"), dict)
    return out


def _sort_value(rec: Dict[str, Any], key: str) -> Optional[float]:
    m = rec.get("metrics") or {}
    if key == "sharpe":      # Sharpe giai đoạn test
        return _first_num(m.get("test"), "sharpe")
    if key == "cagr":        # CAGR toàn kỳ — không phải ret_pct
        return _first_num(m.get("simulate"), "cagr_pct")
    return None


def list_user_alphas(sort: Optional[str] = None, status: Optional[str] = None,
                     base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Liệt kê danh sách alpha người dùng (bản ghi gọn, không kèm ảnh chụp kết quả)."""
    user_dir = get_user_alphas_dir(base_dir)
    if not os.path.isdir(user_dir):
        return []

    items: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(user_dir)):
        if fname.endswith(".json") and not fname.endswith(".tmp"):
            path = os.path.join(user_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    rec = json.load(fh)
                    if isinstance(rec, dict) and rec.get("id"):
                        if status and rec.get("status") != status:
                            continue
                        items.append(_summary(rec))
            except Exception:
                continue

    # Sắp xếp (giá trị thiếu xếp cuối)
    if sort in ("sharpe", "cagr"):
        have = sorted((x for x in items if _sort_value(x, sort) is not None), key=lambda x: _sort_value(x, sort), reverse=True)
        items = have + [x for x in items if _sort_value(x, sort) is None]
    elif sort == "date":
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    else:
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    return items


def get_user_alpha(alpha_id: str, base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lấy chi tiết một alpha người dùng theo id."""
    user_dir = get_user_alphas_dir(base_dir)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def update_user_alpha_status(alpha_id: str, new_status: str, base_dir: Optional[str] = None) -> bool:
    """Cập nhật trạng thái alpha: SAVED -> CANDIDATE -> ARCHIVED."""
    rec = get_user_alpha(alpha_id, base_dir)
    if not rec:
        return False
    rec["status"] = new_status
    rec["updated_at"] = datetime.now(timezone.utc).isoformat()
    user_dir = get_user_alphas_dir(base_dir)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")
    write_json_atomic(file_path, rec, indent=1, clean=True, allow_nan=False)
    return True


# ══════════════════════════════════════════════════════════════════════════
# Thư viện chiến lược: mỗi CHIẾN LƯỢC (không phải mỗi alpha / khung giờ) = Ý tưởng -> Công thức bằng lời -> Công thức toán học -> Thống kê.
#
# Công thức dựng từ CÂY KHUÔN của chiến lược (strategies.py CANDIDATES: "ema_{ema_n}", {"param": "k_up"}, khung "{signal_tf}") nên là dạng KÝ HIỆU,
# đúng cấu trúc engine đang chạy; nhãn tham số lấy từ params_schema. Thống kê = các alpha đã qua kiểm định của chiến lược đó trong sổ chính + sổ thử nghiệm
# (mọi khung giờ gộp chung). Danh mục: STRATEGIES; chiến lược có "doc": "combined" (Sideway) là MỘT mục gồm cả hai chiều.
#
#     catalog() -> {"sources": [{"key": "nora", "label": "Nora", "strategies": [{key, name, kind, side, idea, plain, math, summary, stats}, ...]}]}
#     plain: câu tiếng Việt, ký hiệu toán nằm trong $…$ (UI hiện bằng KaTeX nội dòng).
# ══════════════════════════════════════════════════════════════════════════

CMP_LATEX = {"<": "<", ">": ">", "<=": r"\le", ">=": r"\ge"}
CMP_VI = {"<": "<", ">": ">", "<=": "≤", ">=": "≥"}
PRICE = {"close": ("C", "giá đóng cửa"), "open": ("O", "giá mở cửa"), "high": ("H", "giá cao"), "low": ("L", "giá thấp")}
BAND = {"bbl": ("BB", "lo", "dải dưới Bollinger"), "bbu": ("BB", "up", "dải trên Bollinger"), "bbm": ("BB", "mid", "đường giữa Bollinger"),
        "kcl": ("KC", "lo", "dải dưới Keltner"), "kcu": ("KC", "up", "dải trên Keltner"), "kcm": ("KC", "mid", "đường giữa Keltner")}
STAT_KEYS = ("ret_pct", "extreme_ret_pct", "mdd_pct", "extreme_mdd_pct", "sharpe", "sortino", "profit_factor", "win_rate", "trades", "symbols_positive")
# Tổng hợp cấp chiến lược trên các alpha đã đạt: lợi nhuận / tỷ số = trung bình; MDD = xấu nhất; số lệnh = tổng
SUMMARY = {"ret_pct": "mean", "extreme_ret_pct": "mean", "mdd_pct": "max", "extreme_mdd_pct": "max", "sharpe": "mean", "sortino": "mean",
           "profit_factor": "mean", "win_rate": "mean", "trades": "sum"}
STAGES = ("FINAL", "S6_holdout", "S5_sizing", "S4_montecarlo", "S3_wfa", "S2_antiluck", "S1_backtest")
_PH = re.compile(r"\{(\w+)\}")


def vn(x: Any) -> str:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return str(x)
    return f"{float(x):.4f}".rstrip("0").rstrip(".").replace(".", ",")


# ─── Ký hiệu tham số ────────────────────────────────────────────────────────
def psym(name: str) -> str:
    """Tên tham số khuôn -> ký hiệu: rsi_lo -> θ^{RSI}_{lo}; gate_er_max -> θ^{ER}_{gate}; k_up -> k_{up}; ema_n -> n."""
    t = name.split("_")
    rest = r"\_".join(t[1:])
    if t[0] == "gate" and len(t) > 1 and t[1] in REGISTRY:
        return rf"\theta^{{\mathrm{{{t[1].upper()}}}}}_{{\mathrm{{gate}}}}"
    if t[0] in REGISTRY and len(t) > 1 and t[-1] not in ("n", "k", "m"):
        return rf"\theta^{{\mathrm{{{t[0].upper()}}}}}_{{\mathrm{{{rest}}}}}"
    if len(t) > 1 and t[-1] in ("n", "k", "m"):
        return t[-1]
    return rf"{t[0]}_{{\mathrm{{{rest}}}}}" if len(t) > 1 else t[0]


def fsym(frame: str) -> str:
    m = _PH.fullmatch(frame)
    return rf"\tau_{{\mathrm{{{m.group(1).replace('_tf', '')}}}}}" if m else rf"\mathrm{{{frame}}}"


def _label(schema: Dict[str, Any], name: str) -> str:
    return str((schema.get(f"sig.{name}") or schema.get(name) or {}).get("label_vi") or name)


def pword(name: str, schema: Dict[str, Any]) -> str:
    """Tên tham số bằng lời: ngưỡng (…_lo/_hi/_max/gate_…) gọi là "ngưỡng …"; còn lại dùng nhãn schema (vd "hệ số dải trên")."""
    t = name.split("_")
    if t[0] == "gate":
        return "ngưỡng dồn"
    if t[0] in REGISTRY and t[-1] in ("lo", "hi", "max", "min"):
        return {"lo": "ngưỡng thấp", "hi": "ngưỡng cao", "max": "ngưỡng", "min": "ngưỡng"}[t[-1]]
    return _label(schema, name).lower()


# ─── Toán hạng / điều kiện: (LaTeX, lời) ──────────────────────────────────────
def operand(item: Any, schema: Dict[str, Any], t: str = "t") -> Tuple[str, str]:
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        return vn(item).replace(",", "."), vn(item)
    if not isinstance(item, dict):
        return r"\varnothing", "—"
    if "param" in item:
        return psym(item["param"]), pword(item["param"], schema)
    if item.get("type") == "calculate":
        a, b = operand(item.get("number_1"), schema, t), operand(item.get("number_2"), schema, t)
        if item.get("logic") == "*":
            return rf"{b[0]}\cdot {a[0]}", f"{b[1]} × {a[1]}"
        op = {"+": "+", "-": "-", "/": "/"}.get(item.get("logic"), "?")
        return rf"{a[0]}{op}{b[0]}", f"{a[1]} {op} {b[1]}"
    if "column" in item:
        lag = int(item.get("index", 0) or 0)
        tt = t if not lag else f"{t}-{lag}"
        frame = str(item.get("frame", ""))
        fl = fsym(frame)
        col = str(item["column"])
        kernel = col.split("_", 1)[0]
        subs = [psym(p) for p in _PH.findall(col)]
        if col in PRICE:
            out = (rf"{PRICE[col][0]}^{{{fl}}}_{{{tt}}}", PRICE[col][1])
        elif kernel in BAND:
            sym, band, words = BAND[kernel]
            out = (rf"\mathrm{{{sym}}}^{{\mathrm{{{band}}},{fl}}}_{{{','.join(subs)}}}({tt})", words)
        elif kernel in REGISTRY:
            fw = _label(schema, frame.strip("{}")).lower() if _PH.fullmatch(frame) else frame
            note = f" ({fw})" if frame != schema.get("_main_frame") else ""
            out = (rf"\mathrm{{{kernel.upper()}}}^{{{fl}}}_{{{','.join(subs)}}}({tt})", kernel.upper() + note)
        else:
            out = (rf"\mathrm{{{col}}}({tt})", col)
        if "add" in item:
            m = operand(item["add"], schema, tt)
            out = (rf"{out[0]}+{m[0]}", f"{out[1]} + {m[1]}")
        if "subtract" in item:
            m = operand(item["subtract"], schema, tt)
            out = (rf"{out[0]}-{m[0]}", f"{out[1]} − {m[1]}")
        return out
    return r"\varnothing", "—"


def _shift(item: Any) -> Any:
    if isinstance(item, list):
        return [_shift(x) for x in item]
    if not isinstance(item, dict):
        return item
    return {k: (int(v or 0) + 1 if k == "index" and "column" in item else _shift(v)) for k, v in item.items()}


def _off_by_default(c: List[Any]) -> bool:
    """Ngưỡng mặc định nằm ngoài miền chỉ báo (vd gate_rsi = 101) = điều kiện TUỲ CHỌN, mặc định tắt."""
    left, op, right = c
    if not (isinstance(right, dict) and "default" in right and isinstance(left, dict) and "column" in left):
        return False
    spec = REGISTRY.get(str(left["column"]).split("_", 1)[0])
    if spec is None or ".." not in spec.unit:
        return False
    lo, hi = (float(x) for x in spec.unit.split(".."))
    v = float(right["default"])
    return (op in ("<", "<=") and v > hi) or (op in (">", ">=") and v < lo)


def conditions(tree: Any, schema: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Cây khuôn (OR các khối, AND trong khối) -> (dòng LaTeX, câu). Cặp (x > y tại t, x ≤ y tại t−1) gộp thành "cắt lên"."""
    tex, words = [], []
    blocks = [b for b in (tree or []) if isinstance(b, list) and b]
    for bi, block in enumerate(blocks):
        used = set()
        bt, bw = [], []
        for i, a in enumerate(block):
            if i in used:
                continue
            pair = next((j for j, b in enumerate(block) if j != i and j not in used and (a[1], b[1]) in ((">", "<="), ("<", ">="))
                         and b[0] == _shift(a[0]) and b[2] == _shift(a[2])), None)
            l, r = operand(a[0], schema), operand(a[2], schema)
            opt = " (tuỳ chọn, mặc định tắt)" if _off_by_default(a) else ""
            if pair is not None:
                used.update((i, pair))
                l1, r1 = operand(a[0], schema, "t-1"), operand(a[2], schema, "t-1")
                rev = {">": r"\le", "<": r"\ge"}[a[1]]
                bt.append(rf"{l[0]}{CMP_LATEX[a[1]]}{r[0]}\ \land\ {l1[0]}{rev}{r1[0]}")
                bw.append(f"{l[1]} cắt {'lên trên' if a[1] == '>' else 'xuống dưới'} {r[1]}")
            else:
                bt.append(rf"{l[0]}{CMP_LATEX.get(a[1], a[1])}{r[0]}")
                bw.append(f"{l[1]} {CMP_VI.get(a[1], a[1])} {r[1]}{opt}")
        tex.append(r"\ \land\ ".join(bt))
        words.append(" và ".join(bw))
    if len(tex) > 1:
        tex = [r"\ \lor\ ".join(rf"({x})" for x in tex)]
        words = [" HOẶC ".join(f"({w})" for w in words)]
    return tex, words


# ─── Một mục chiến lược ─────────────────────────────────────────────────────
def _exits(cand: Dict[str, Any], side: str) -> Tuple[List[str], List[str]]:
    sch = cand.get("params_schema") or {}
    adv, fav = {"LONG": ("-", "+"), "SHORT": ("+", "-")}.get(side, (r"\mp ", r"\pm "))   # hai chiều: dấu trên = Long, dấu dưới = Short
    tex = [r"\nu=\mathrm{ATR\%}(t_0)"]
    words = []
    if "dca_step_pct" in sch:
        tex.append(rf"P_k=P_{{k-1}}(1{adv}s\,\nu),\quad q_k=q_0\,m^{{k}},\quad k\le K,\quad \mathrm{{Gate}}_t=1")
        words.append("Giá đi ngược thì dồn tầng $k$ cách tầng trước $s\\nu$ ($\\nu$ = ATR%), khối lượng ×$m$ mỗi tầng, tối đa $K$ tầng — chỉ khi điều kiện dồn còn đúng.")
    pbar = r"\bar P" if "dca_step_pct" in sch else r"P_0"
    ref = "giá trung bình" if "dca_step_pct" in sch else "giá vào"
    tex.append(rf"\mathrm{{SL}}={pbar}(1{adv}s_L\nu),\quad \mathrm{{TP}}={pbar}(1{fav}s_T\nu)")
    words.append(f"Cắt lỗ $s_L\\nu$, chốt lời $s_T\\nu$ tính từ {ref}.")
    if "trailing_stop" in sch:
        ext = {"LONG": r"\max H", "SHORT": r"\min L"}.get(side, r"\max H\ /\ \min L")
        tex.append(rf"\mathrm{{Trail}}=P^*(1{adv}s_R\nu),\quad P^*={ext},\quad \frac{{|P^*-{pbar}|}}{{{pbar}}}\ge a\,\nu")
        words.append("Trailing: lãi đạt $a\\nu$ thì bật, dừng cách đỉnh lãi $s_R\\nu$.")
    return tex, words


def _sizing() -> Tuple[str, str]:
    return (r"N=\min\!\left(\frac{E\,r}{s_L\nu+2(f+\epsilon)},\ E\,c\right),\quad \lambda\le\left\lfloor\frac{1}{1.5\,s_L\nu+\mathrm{mmr}}\right\rfloor",
            "Khối lượng tính ngược từ rủi ro: chạm cắt lỗ (gồm mọi tầng, phí, trượt) chỉ mất $r$% vốn; đòn bẩy tự hạ để luôn cắt lỗ trước khi thanh lý.")


def _main_frame(tree: Any) -> Optional[str]:
    """Khung của toán hạng giá đầu tiên trong cây (khung vào lệnh) — chỉ báo ở khung khác được ghi chú khung."""
    for block in tree or []:
        for c in block:
            for x in (c[0], c[2]):
                if isinstance(x, dict) and x.get("column") in PRICE:
                    return str(x.get("frame"))
    return None


def leg_doc(cand: Dict[str, Any], label: str = "") -> Dict[str, Any]:
    sch = {**(cand.get("params_schema") or {}), "_main_frame": _main_frame(cand.get("tree"))}
    side = cand["side"]
    sv = "Long" if side == "LONG" else "Short"
    plain, math = [], []
    e_tex, e_w = conditions(cand.get("tree"), sch)
    pre = f"{label} " if label else ""
    math.append({"title": f"{pre}Vào lệnh", "latex": rf"\mathrm{{Entry}}^{{\mathrm{{{sv.lower()}}}}}_t=\mathbb{{1}}\left[{e_tex[0]}\right]"})
    plain.append(f"{pre}vào lệnh khi {e_w[0]}." if label else f"Vào {sv} khi {e_w[0]}.")
    if cand.get("stop"):
        x_tex, x_w = conditions(cand.get("stop"), sch)
        math.append({"title": f"{pre}Thoát (đảo chiều)", "latex": rf"\mathrm{{Exit}}_t=\mathbb{{1}}\left[{x_tex[0]}\right]"})
        plain.append(f"{pre}Thoát khi {x_w[0]}.")
    if cand.get("dca_gate"):
        g_tex, g_w = conditions(cand.get("dca_gate"), sch)
        math.append({"title": f"{pre}Được phép dồn", "latex": rf"\mathrm{{Gate}}_t=\mathbb{{1}}\left[{g_tex[0]}\right]"})
        plain.append(f"{pre}Chỉ dồn khi {g_w[0]}.")
    return {"plain": plain, "math": math, "side": side}


def _alphas_of(leg_ids: List[str], books: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out = []
    for kind, book in books:
        for it in book.get("strategies") or []:
            if it.get("id") not in leg_ids:
                continue
            sm = ((it.get("evidence") or {}).get("stage_metrics") or {})
            stage = next((s for s in STAGES if sm.get(s)), None)
            m = sm.get(stage) or {}
            out.append({"leg": it["id"], "side": it.get("side"), "timeframe": book.get("timeframe"), "book": kind,
                        "alpha_id": (it.get("evidence") or {}).get("funnel_alpha_id"), "stage": stage,
                        "universe": len(book.get("universe") or []),
                        **{k: m.get(k) for k in STAT_KEYS}})
    return out


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Chỉ số tổng hợp của chiến lược trên các alpha đã đạt (quy tắc SUMMARY); không có alpha -> {"n": 0}."""
    out: Dict[str, Any] = {"n": len(rows)}
    for key, how in SUMMARY.items():
        v = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
        if v:
            out[key] = round(sum(v) / len(v), 4) if how == "mean" else (max(v) if how == "max" else int(sum(v)))
    return out


def _user_card_metrics(sim: Any) -> Dict[str, Any]:
    """Số đo thẻ alpha người dùng từ metrics.simulate của kết quả đã lưu (bộ chỉ số phẳng: ret_pct, mdd_pct, sharpe, sortino, win_rate_trades %, profit_factor_trades, trades).
    Thiếu -> None (giao diện hiện "—"), không bao giờ 0 giả; số 0 thật được giữ."""
    sim = sim or {}
    mdd = _first_num(sim, "mdd_pct")
    trades = _first_num(sim, "trades")
    return {
        "ret_pct": _first_num(sim, "ret_pct"),
        "mdd_pct": abs(mdd) if mdd is not None else None,
        "sharpe": _first_num(sim, "sharpe"),
        "sortino": _first_num(sim, "sortino"),
        "profit_factor": _first_num(sim, "profit_factor_trades"),
        "win_rate": _first_num(sim, "win_rate_trades"),
        "trades": int(trades) if trades is not None else None,
    }


def catalog(alphas_dir: Optional[str] = None) -> Dict[str, Any]:
    if alphas_dir is None:
        alphas_dir = _alpha_dir()
    books = [(k, b) for k, b in (("main", read_json(os.path.join(alphas_dir, "book.json"))),
                                 ("explore", read_json(os.path.join(alphas_dir, "explore", "book.json")))) if b]
    sizing_tex, sizing_w = _sizing()
    items = []
    for st in STRATEGIES:
        legs = st["legs"]
        groups = [list(legs.items())] if st.get("doc") == "combined" else [[x] for x in legs.items()]
        for group in groups:
            cands = [BY_ID[cid] for _, cid in group]
            label = len(group) > 1
            docs = [leg_doc(c, ("Long:" if c["side"] == "LONG" else "Short:") if label else "") for c in cands]
            ex_tex, ex_w = _exits(cands[0], "BOTH" if label else cands[0]["side"])
            if label:
                ex_w.append("Hai chiều đối xứng: dấu trên cho Long, dấu dưới cho Short.")
            items.append({
                "key": "_".join([st["id"]] + ([] if label else [group[0][0].lower()])),
                "strategy": st["id"], "name": st["name"], "kind": st["kind"],
                "side": "Long + Short" if label else ("Long" if group[0][0] == "LONG" else "Short"),
                "idea": st["idea"],
                "plain": [p for d in docs for p in d["plain"]] + ex_w + [sizing_w],
                "math": [m for d in docs for m in d["math"]] + [{"title": "Dồn lệnh & thoát lệnh" if "dca_step_pct" in (cands[0].get("params_schema") or {})
                                                                        else "Thoát lệnh", "latex": r" \\ ".join(ex_tex)},
                                                               {"title": "Khối lượng", "latex": sizing_tex}],
            })
            items[-1]["stats"] = _alphas_of([cid for _, cid in group], books)
            items[-1]["summary"] = summarize(items[-1]["stats"])

    # Nhóm Alpha người dùng (C1)
    uas = list_user_alphas(base_dir=alphas_dir)
    for ua in uas:
        if ua.get("status") == "ARCHIVED":
            continue
        code = ua.get("code", "")
        plain_lines = []
        try:
            from backend.alpha.compile import compile_code
            from backend.alpha.compile import explain_program
            prog = compile_code(code, register=False)
            exp = explain_program(prog, position=(ua.get("config") or {}).get("position"))
            plain_lines = [r["action_vi"] for r in exp.get("rules", [])] + [e["desc"] for e in exp.get("execution", [])[:2]]
        except Exception:
            plain_lines = [ua.get("note") or "Chiến lược người dùng đã xác minh"]

        stat_item = {
            "leg": ua["id"],
            "side": "LONG" if (ua.get("config", {}).get("program", {}) or {}).get("legs") == ["LONG"] else "BOTH",
            "timeframe": (ua.get("config", {}) or {}).get("timeframe", "24h"),
            "book": "user",
            "alpha_id": ua["id"],
            "stage": ua.get("status", "SAVED"),
            "universe": len((ua.get("config", {}) or {}).get("symbols") or []),
            **_user_card_metrics((ua.get("metrics") or {}).get("simulate")),
        }
        items.append({
            "key": f"user_{ua['id']}",
            "strategy": ua["id"],
            "name": ua["name"],
            "kind": "Alpha người dùng",
            "side": "Long" if (ua.get("config", {}).get("program", {}) or {}).get("legs") == ["LONG"] else "Long + Short",
            "idea": ua.get("note") or f"Alpha người dùng từ nguồn {ua.get('source', 'alpha-create')}",
            "plain": plain_lines,
            "math": [],
            "stats": [stat_item],
            "summary": {
                "n": 1,
                "ret_pct": stat_item["ret_pct"],
                "mdd_pct": stat_item["mdd_pct"],
                "sharpe": stat_item["sharpe"],
                "sortino": stat_item["sortino"],
                "profit_factor": stat_item["profit_factor"],
                "win_rate": stat_item["win_rate"],
                "trades": stat_item["trades"],
            },
            "is_user_alpha": True,
            "alpha_id": ua["id"],
        })

    return {"sources": [{"key": "nora", "label": "Nora", "strategies": items}]}


# ══════════════════════════════════════════════════════════════════════════
# Top agent trade: doc ket qua da dong bang (implied exit fit + OOS) cua 10 bot copy-trade top OKX.
#
# Nguon duy nhat: models/storage.alpha_dir('research', 'okx_top10_agents.json') (git-tracked, co provenance).
# Khong doc scripts nghien cuu; ket qua nghien cuu da duoc dong bang mot lan.
#
# GET /api/studio/alphas/top_agents
# {
#   "bots": [ { "slug", "name", "bot_type", "n_baskets", "in_sample", "caveat",
#               "exit_structure", "formula_summary", "class_mix_pct",
#               "in_sample_metrics", "criteria_is", "report_stats", "oos",
#               "mixed_runs", "mixed_runs_note" }, ... ],
#   "n_bots": 10,
#   "generated_at": "<frozen_at>",
#   "provenance": { "frozen_at", "git_commit", "source", "per_bot_sources", ... }
# }
# Neu file khong co: {"bots": [], "n_bots": 0, "reason": "..."}.
# ══════════════════════════════════════════════════════════════════════════

def _frozen_path() -> str:
    from backend.models.storage import alpha_dir
    return alpha_dir("research", "okx_top10_agents.json")


def _empty(reason: str) -> Dict[str, Any]:
    return {"bots": [], "n_bots": 0, "reason": reason}


def top_agents() -> Dict[str, Any]:
    try:
        with open(_frozen_path(), encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return _empty("Chua co file dong bang data/alpha/research/okx_top10_agents.json")
    except (OSError, ValueError) as exc:
        return _empty(f"Khong doc duoc file dong bang okx_top10_agents.json: {exc}")
    if not isinstance(d, dict) or not isinstance(d.get("bots"), list):
        return _empty("File dong bang okx_top10_agents.json sai dinh dang (thieu 'bots')")

    prov = d.get("provenance") or {}
    bots = d["bots"]
    for b in bots:
        b.setdefault("mixed_runs", False)
        b.setdefault("mixed_runs_note", None)
    return {
        "bots": bots,
        "n_bots": len(bots),
        "generated_at": prov.get("frozen_at"),
        "provenance": prov,
    }


# ═══ Cache kết quả mẫu giáo dục ═══

_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
SAMPLE_SPEC_FIELDS = ("symbols", "start", "end", "train_ratio", "initial_capital", "run_frame")


def _sample_dir() -> str:
    from backend.models.storage import alpha_dir
    return alpha_dir("education", "results")


@functools.lru_cache(maxsize=256)
def _program_info(code: str) -> tuple:
    """(program_hash, timeframe) của mã — hash do compile_code tính; DslError nếu mã không biên dịch."""
    from backend.alpha.compile import compile_code
    prog = compile_code(code)
    h = getattr(prog, "code_hash", None) or hashlib.sha256(code.encode("utf-8")).hexdigest()
    return h, getattr(prog, "timeframe", None)


def sample_cache_key(code: str, run_spec: dict) -> str:
    """sha256 của {program_hash, run_spec, phiên bản Nautilus, dấu vân tay catalog, base_frame}."""
    from backend.nautilus.version import NAUTILUS_VERSION
    phash, tf = _program_info(code)
    base_frame = run_spec.get("run_frame") or tf or "1h"
    try:
        from backend.data.data import resolve_symbols
        from backend.data.data import catalog_digest
        digest = catalog_digest(resolve_symbols(run_spec.get("symbols")))
    except Exception:   # noqa: BLE001 — chưa có catalog/dữ liệu: khoá vẫn xác định, chạy sẽ báo lỗi dữ liệu rõ ràng
        digest = ""
    payload = {"program_hash": phash, "run_spec": run_spec, "nautilus": NAUTILUS_VERSION, "catalog": digest, "base_frame": base_frame}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _sample_path(key: str) -> str:
    if not _KEY_RE.match(key):
        raise ValueError("khoá cache không hợp lệ")
    return os.path.join(_sample_dir(), f"{key}.json")


def sample_get(key: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_sample_path(key), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return None


def sample_put(key: str, result: Dict[str, Any]) -> None:
    from backend.models.storage import write_json_atomic
    os.makedirs(_sample_dir(), exist_ok=True)
    write_json_atomic(_sample_path(key), result)


def sample_run_spec(sample: dict, defaults: Optional[dict] = None) -> dict:
    """Thiết lập chạy của mẫu = mặc định của Studio (data.run_defaults, chế độ 'Nhanh': run_frame rỗng = khung tín hiệu) + trường riêng của mẫu."""
    if defaults is None:
        from backend.data.data import run_defaults
        defaults = run_defaults()
    spec = dict(defaults)
    for f in SAMPLE_SPEC_FIELDS:
        if sample.get(f) not in (None, ""):
            spec[f] = sample[f]
    if sample.get("timeframe"):
        spec["run_frame"] = sample["timeframe"]
    spec.setdefault("run_frame", "")
    return spec


def sample_lookup(sample: dict, spec: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    """Kết quả thật đã cache cho mẫu (khoá hiện hành) hoặc None (chưa chạy / mã không biên dịch / thiếu dữ liệu)."""
    try:
        spec = spec if spec is not None else sample_run_spec(sample)
        return sample_get(sample_cache_key(sample.get("code", ""), spec))
    except Exception:   # noqa: BLE001 — không tính được khoá = chưa có kết quả thật
        return None
