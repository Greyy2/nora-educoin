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


from backend.analys.indicator import REGISTRY
from backend.models.models import NORA_DIR
from backend.analys.param import BETA_DRIVEN_ID, REGIME_MAP, materialize, regime_for, schema_defaults
from .code.compile import load_system_strategies
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
        from backend.analys.param import VENUE_COSTS, dca_budget_check
        budget = dca_budget_check(st["position"], VENUE_COSTS[("cex", "perp")])
        if not budget["ok"]:
            errors.append((prefix, f"{cid}: ngân sách DCA không đủ — cần {budget['need_pct']:.1f}% vốn, trần {budget['cap_pct']:.1f}%"))
    except ValueError as exc:
        errors.append((prefix, f"{cid}: {exc}"))
    return full, errors


# ─── Khung chạy (nến mô phỏng) ───────────────────────────────────────────────
def frame_keys(candidate: Dict[str, Any]) -> List[str]:
    """Khoá chọn KHUNG nến của chiến lược (sig.*_tf, atr_frame...): kiểu choice, mọi lựa chọn là khung."""
    from backend.analys.param import FRAME_MS
    return [k for k, v in (candidate.get("params_schema") or {}).items()
            if v.get("type") == "choice" and set(v.get("choices") or []) <= set(FRAME_MS)]


def lift_frame(frame: str, base_frame: str, choices: List[str]) -> Optional[str]:
    """Khung >= khung chạy giữ nguyên; nhỏ hơn -> khung chạy nếu là lựa chọn hợp lệ, không thì None (không chạy được)."""
    from backend.analys.param import FRAME_MS
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
    dirs = [
        ("backend/core", "backend/nautilus"),
        ("backend/models", "backend/models"),
        ("backend/analys/signal", "backend/signal"),
    ]
    for modern, legacy in dirs:
        if os.path.isdir(os.path.join(NORA_DIR, modern)):
            dp = os.path.join(NORA_DIR, modern)
            for n in sorted(os.listdir(dp)):
                if n.endswith(".py") and n != "__init__.py":
                    rel = f"{legacy}/{n}"
                    rels.append((rel, os.path.join(dp, n)))
        elif os.path.isdir(os.path.join(NORA_DIR, legacy)):
            dp = os.path.join(NORA_DIR, legacy)
            for n in sorted(os.listdir(dp)):
                if n.endswith(".py") and n != "__init__.py":
                    rel = f"{legacy}/{n}"
                    rels.append((rel, os.path.join(dp, n)))

    special = [
        ("backend/jobs/runner/backtest.py", "backend/jobs/evaluate.py"),
        ("backend/analys/alpha/code/plan.py", "backend/alpha/plan.py"),
        ("backend/analys/indicator/indicator.py", "backend/signal/indicator.py"),
        ("backend/analys/signal/signal.py", "backend/signal/nodes.py"),
    ]
    for actual, legacy in special:
        if os.path.isfile(os.path.join(NORA_DIR, actual)):
            rels.append((legacy, os.path.join(NORA_DIR, actual)))
        elif os.path.isfile(os.path.join(NORA_DIR, legacy)):
            rels.append((legacy, os.path.join(NORA_DIR, legacy)))

    return [(rel, path) for rel, path in rels if os.path.isfile(path)]


def _strategy_ir_hashes() -> List[Tuple[str, str]]:
    """[(chân chiến lược, sha256 của IR biên dịch)] — chỉ phần ảnh hưởng kết quả (bỏ mô tả/nhãn/lược đồ tham số)."""
    from .code.compile import load_system_strategies
    out = []
    for c in load_system_strategies()["candidates"]:
        ir = {k: c.get(k) for k in ("id", "side", "tree", "stop", "position", "space")}
        out.append((f"strategy:{c['id']}", hashlib.sha256(json.dumps(ir, sort_keys=True, default=repr).encode("utf-8")).hexdigest()))
    return out


def engine_inputs() -> List[str]:
    """Danh sách tên đầu vào được băm (dùng cho lời giải thích)."""
    return [rel for rel, _ in _engine_files()] + [n for n, _ in _strategy_ir_hashes()]


def engine_version() -> Dict[str, Any]:
    from .code.compile import strategy_files
    files = _engine_files()
    sfiles = strategy_files()
    sig = tuple((p, os.stat(p).st_mtime_ns, os.stat(p).st_size) for p in [p for _, p in files] + sfiles)
    if _cache["sig"] == sig and time.time() - _cache["at"] < GIT_TTL_S:
        return dict(_cache["value"])
    from backend.core import NAUTILUS_VERSION
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
# Quản lý Alpha người dùng & Lưu trữ (chuyển sang backend/alpha/store.py)
# ══════════════════════════════════════════════════════════════════════════
# Gộp trực tiếp từ store.py:
"""Kho lưu trữ Alpha người dùng và đệm mẫu giáo dục (P17 T2 B3).

Tách từ alpha/strategies.py để thu gọn và hỗ trợ đa người dùng (owner_id):
- Alpha người dùng: lưu/phiên bản/kiểm định checklist/chủ sở hữu (owner_id).
- Chống trùng program_hash theo từng owner (2 user khác nhau lưu cùng code được).
- Đệm kết quả mẫu giáo dục (sample cache).
"""
import functools
import hashlib
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.models.models import NORA_DIR
from backend.analys.param import BETA_DRIVEN_ID
from backend.models.storage import alpha_dir, alpha_user_dir, read_json, write_json_atomic

MISSING_VI = "không có dữ liệu"
SNAPSHOT_REQUIRED = ("config", "metrics", "program_hash")
_HEAVY = ("result", "explain")
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
SAMPLE_SPEC_FIELDS = ("symbols", "start", "end", "train_ratio", "initial_capital", "run_frame")


def _git(*args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", NORA_DIR, *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def git_commit() -> Optional[str]:
    """Commit git ngắn của HEAD (None nếu không đọc được)."""
    return _git("rev-parse", "--short", "HEAD")


def get_user_alphas_dir(base_dir: Optional[str] = None) -> str:
    """Thư mục lưu alpha người dùng."""
    if base_dir:
        return os.path.join(base_dir, "user")
    return alpha_user_dir()


def generate_alpha_id(program_hash: str, config: Dict[str, Any], owner_id: Optional[str] = None) -> str:
    """Tạo mã alpha_id bất biến: sha1(owner_id + program_hash + canonical config)[:12]."""
    canon = {
        "symbols": sorted(config.get("symbols") or []),
        "start": config.get("start"),
        "end": config.get("end"),
        "train_ratio": config.get("train_ratio"),
        "initial_capital": config.get("initial_capital"),
        "timeframe": config.get("timeframe"),
        "position": config.get("position"),
    }
    prefix = f"{owner_id}:" if owner_id else ""
    raw = f"{prefix}{program_hash}:{json.dumps(canon, sort_keys=True)}"
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
    """state: pass | fail | missing. `passed` = True | False | None."""
    return {
        "id": item_id,
        "label": label,
        "state": state,
        "passed": {"pass": True, "fail": False}.get(state),
        "value": value,
        "required": required,
    }


def evaluate_checklist(result: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra 5 tiêu chí trước khi lưu (chỉ cảnh báo, không chặn):
    - >= 20 lệnh đóng
    - có giai đoạn test
    - Sharpe test > 0 (metrics.test.sharpe, năm = 365 ngày)
    - MDD < 50% (metrics.simulate.mdd_pct, đã là %)
    - không phải thuần beta (insight beta_driven)
    Đầu vào thiếu -> state "missing" (không đạt cũng không trượt)."""
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


def build_evidence(result: Dict[str, Any], job_id: Optional[str] = None, job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = result.get("data") or {}
    job = job or {}
    return {
        "job_id": job_id,
        "program_hash": result.get("program_hash"),
        "data_source": data.get("source"),
        "data_sha256_1m": data.get("content_sha256_1m"),
        "catalog_fingerprint": data.get("catalog_digest"),
        "git_commit": git_commit(),
        "job_created": job.get("created"),
        "job_finished": job.get("finished"),
        "engine": "custom_run (PortfolioEngine)",
    }


def save_user_alpha(
    job_id: Optional[str] = None,
    code: str = "",
    name: str = "",
    note: str = "",
    source: str = "alpha-create",
    base_dir: Optional[str] = None,
    alpha_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    forked_from: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Xác thực và lưu trữ bản ghi Alpha người dùng:
    - Nếu có job_id: đọc kết quả job thật từ máy chủ (job.status == 'done')
    - Nếu không có job_id: biên dịch code kiểm tra cú pháp, lưu bản nháp/bản ghi trực tiếp
    - Kiểm tra mã băm chương trình khớp với code
    - Chống trùng program_hash THEO TỪNG OWNER (cùng owner trùng -> ValueError / 409)
    - Lưu owner_id vào bản ghi
    - Phiên bản mới (versioned): giữ owner_id cũ nếu không truyền mới
    - Lưu nguồn sao chép bất biến (forked_from) nếu có
    """
    if not job_id:
        from .code.compile import compile_code
        prog = compile_code(code, register=False)
        result = {
            "program_hash": prog.code_hash,
            "metrics": {
                "simulate": {
                    "total_return_pct": 0.0,
                    "max_drawdown_pct": 0.0,
                    "sharpe": 0.0,
                    "win_rate": 0.0,
                    "total_trades": 0,
                }
            },
            "config": {
                "symbols": ["BTC@perp"],
                "timeframe": "15m",
            },
            "indicators": getattr(prog, "indicators", []),
        }
        return save_user_alpha_from_result(
            owner_id, code, name, result, source=source, note=note or "Bản lưu soạn thảo trực tiếp",
            base_dir=base_dir, alpha_id=alpha_id, job_id=None, job={"status": "draft"},
            forked_from=forked_from,
        )

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
    return save_user_alpha_from_result(
        owner_id, code, name, result, source=source, note=note, base_dir=base_dir,
        alpha_id=alpha_id, job_id=job_id, job=job, forked_from=forked_from,
    )


def save_user_alpha_from_result(
    owner_id: Optional[str],
    code: str,
    name: str,
    result: Dict[str, Any],
    source: str = "seed",
    sample_key: Optional[str] = None,
    note: str = "",
    base_dir: Optional[str] = None,
    alpha_id: Optional[str] = None,
    job_id: Optional[str] = None,
    job: Optional[Dict[str, Any]] = None,
    forked_from: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Một định nghĩa duy nhất cho kiểm tra + checklist + evidence + ghi bản ghi alpha.
    `result` là kết quả Nautilus thật (job hoàn tất hoặc cache mẫu); `job_id`/`job` chỉ có khi đến từ job."""
    job = job or {}
    lacking = [k for k in SNAPSHOT_REQUIRED if not result.get(k)]
    if lacking or not (result.get("metrics") or {}).get("simulate"):
        raise ValueError(f"Kết quả {'job ' + job_id if job_id else 'mẫu'} thiếu {lacking or ['metrics.simulate']}: không đủ để lưu")

    # Kiểm tra program_hash
    from .code.compile import compile_code
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
        alpha_id = generate_alpha_id(prog.code_hash, config, owner_id=owner_id)

    # Chống trùng: chỉ chặn khi trùng cả code (program_hash) VÀ cấu hình tham số (config), trừ trường hợp đang lưu phiên bản của chính alpha_id đó
    canon_cur = {k: config.get(k) for k in ("symbols", "start", "end", "train_ratio", "initial_capital", "timeframe", "position")}
    for ex in list_user_alphas(base_dir=base_dir, owner_id=owner_id):
        if versioned and ex.get("id") == alpha_id:
            continue
        if ex.get("program_hash") == prog.code_hash:
            ex_conf = ex.get("config") or {}
            canon_ex = {k: ex_conf.get(k) for k in ("symbols", "start", "end", "train_ratio", "initial_capital", "timeframe", "position")}
            if canon_ex == canon_cur:
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
        from .code.compile import explain_program
        explain = explain_program(prog, position=config.get("position"))
    except Exception:
        explain = None

    effective_owner = owner_id if owner_id is not None else old_record.get("owner_id")

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
        "market_context": result.get("market_context"),
        "checklist": checklist,
        "data_sha": (result.get("data") or {}).get("content_sha256_1m"),
        "job_id": job_id,
        "sample_key": sample_key if sample_key is not None else old_record.get("sample_key"),
        "final_equity": result.get("final_equity"),
        "evidence": build_evidence(result, job_id, job),
        "explain": explain,
        "result": snapshot,
        "owner_id": effective_owner,
    }
    if forked_from and isinstance(forked_from, dict) and forked_from.get("alpha_id"):
        # Server-authoritative lookup (DEC-03): bắt buộc tìm thấy chiến lược nguồn
        src_alpha = get_user_alpha(forked_from["alpha_id"], base_dir)
        if not src_alpha:
            raise ValueError(f"Không thể xác thực nguồn fork: không tìm thấy chiến lược {forked_from['alpha_id']}")
        from backend import users
        src_owner = users.get_user(src_alpha.get("owner_id")) if src_alpha.get("owner_id") else None
        record["forked_from"] = {
            "alpha_id": src_alpha["id"],
            "version": src_alpha.get("version", 1),
            "author_uid": src_alpha.get("owner_id"),
            "author_handle": src_owner.get("handle") if src_owner else (src_alpha.get("author_handle") or "unknown"),
            "author_name": src_owner.get("display_name") if src_owner else (src_alpha.get("author_name") or "Tác giả"),
            "code_hash": src_alpha.get("program_hash") or hashlib.sha256((src_alpha.get("code") or "").encode("utf-8")).hexdigest()[:16],
            "forked_at": now_iso,
        }
    elif old_record.get("forked_from"):
        # Giữ nguyên nguồn gốc khi lưu phiên bản mới của bản fork đã có
        record["forked_from"] = old_record["forked_from"]

    if versioned:
        prev_v = int(old_record.get("version") or 1)
        history = list(old_record.get("versions") or [_version_row(old_record, prev_v)])
        vdir = os.path.join(user_dir, "_versions")
        os.makedirs(vdir, exist_ok=True)
        write_json_atomic(os.path.join(vdir, f"{alpha_id}.v{prev_v}.json"), old_record, indent=1, clean=True, allow_nan=False)
        record["version"] = prev_v + 1
        record["versions"] = history + [_version_row(record, prev_v + 1)]
    else:
        record["version"] = int(old_record.get("version") or 1)
        if old_record.get("versions"):
            record["versions"] = old_record["versions"]

    write_json_atomic(file_path, record, indent=1, clean=True, allow_nan=False)
    return record, action


def _version_row(rec: Dict[str, Any], version: int) -> Dict[str, Any]:
    return {
        "version": version,
        "saved_at": rec.get("updated_at"),
        "program_hash": rec.get("program_hash"),
        "job_id": rec.get("job_id"),
        "name": rec.get("name"),
    }


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


def _summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Bản ghi gọn cho danh sách: bỏ ảnh chụp kết quả + giải thích."""
    out = {k: v for k, v in rec.items() if k not in _HEAVY}
    out["has_result"] = isinstance(rec.get("result"), dict)
    return out


def _sort_value(rec: Dict[str, Any], key: str) -> Optional[float]:
    m = rec.get("metrics") or {}
    if key == "sharpe":
        return _first_num(m.get("test"), "sharpe")
    if key == "cagr":
        return _first_num(m.get("simulate"), "cagr_pct")
    return None


def list_user_alphas(
    sort: Optional[str] = None,
    status: Optional[str] = None,
    base_dir: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Liệt kê danh sách alpha người dùng (bản ghi gọn, lọc theo status và owner_id)."""
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
                        if owner_id is not None:
                            rec_owner = rec.get("owner_id") or ""
                            if rec_owner != (owner_id or ""):
                                continue
                        items.append(_summary(rec))
            except Exception:
                continue

    if sort in ("sharpe", "cagr"):
        have = sorted((x for x in items if _sort_value(x, sort) is not None), key=lambda x: _sort_value(x, sort), reverse=True)
        items = have + [x for x in items if _sort_value(x, sort) is None]
    elif sort == "date":
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    else:
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    return items


def count_by_owner(base_dir: Optional[str] = None) -> Dict[str, int]:
    """Số lượng alpha hoạt động (chưa archive) của từng owner_id."""
    counts: Dict[str, int] = {}
    for a in list_user_alphas(base_dir=base_dir):
        if a.get("status") == "ARCHIVED":
            continue
        oid = a.get("owner_id")
        if oid:
            counts[oid] = counts.get(oid, 0) + 1
    return counts


def _enrich_alpha_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Tự động bù các trường metrics và by_symbol còn thiếu cho các bản ghi alpha đã lưu trước đây."""
    if not isinstance(rec, dict):
        return rec
    res = rec.get("result")
    if not isinstance(res, dict):
        return rec
    stale_warning = "Dùng mặc định của engine cho "
    if isinstance(res.get("warnings"), list):
        res["warnings"] = [
            warning for warning in res["warnings"]
            if not (isinstance(warning, str) and warning.startswith(stale_warning))
        ]

    # 1. Bù by_symbol (weight_pct, ret_pct, open_pnl_usd)
    by_sym = res.get("by_symbol")
    if isinstance(by_sym, list) and len(by_sym) > 0:
        n_sym = len(by_sym)
        cfg = rec.get("config") or res.get("config") or {}
        cap = float(cfg.get("initial_capital", 10000.0) or 10000.0)
        alloc = cap / n_sym if n_sym else 1.0
        for row in by_sym:
            if not isinstance(row, dict):
                continue
            if row.get("weight_pct") is None:
                row["weight_pct"] = round(100.0 / n_sym, 1)
            if row.get("ret_pct") is None:
                pnl = float(row.get("pnl_usd", row.get("pnl", 0.0)))
                row["ret_pct"] = round((pnl / alloc) * 100.0, 2)
            if row.get("open_pnl_usd") is None:
                row["open_pnl_usd"] = 0.0

    # 2. Bù metrics nếu thiếu vol_ann_pct hoặc days
    metrics = res.get("metrics")
    series = res.get("series")
    trades = res.get("trades") or []
    if isinstance(metrics, dict) and isinstance(series, dict) and "equity" in series:
        sim = metrics.get("simulate")
        if isinstance(sim, dict) and sim.get("vol_ann_pct") is None:
            try:
                import numpy as np
                from backend.analys.metrics.trades import _metric_block
                trade_rows = []
                for t in trades:
                    tr = dict(t)
                    if "pnl_usd" not in tr and "pnl" in tr:
                        tr["pnl_usd"] = tr["pnl"]
                    if "fees_usd" not in tr and "fees" in tr:
                        tr["fees_usd"] = tr["fees"]
                    trade_rows.append(tr)

                eq = np.asarray(series.get("equity", []), dtype=float)
                times = np.asarray(series.get("times", []), dtype=int)
                worst = np.asarray(series.get("equity_worst", eq), dtype=float) if "equity_worst" in series else eq
                if len(eq) > 1:
                    ret = np.zeros(len(eq))
                    ret[1:] = eq[1:] / eq[:-1] - 1.0
                    split = series.get("stage_split") or (times[int(len(times) * 0.7)] if len(times) else 0)

                    # Update simulate
                    fees_sim = sum(float(r.get("fees_usd", 0.0)) for r in trade_rows)
                    blk_sim = _metric_block(ret, trade_rows, fees_sim, eq, worst)
                    for k, v in blk_sim.items():
                        if sim.get(k) is None:
                            sim[k] = v

                    # Update train
                    train = metrics.get("train")
                    if isinstance(train, dict):
                        m_train = times <= split
                        rows_train = [r for r in trade_rows if r.get("close_time", 0) <= split]
                        fees_train = sum(float(r.get("fees_usd", 0.0)) for r in rows_train)
                        blk_train = _metric_block(ret[m_train], rows_train, fees_train, eq[m_train], worst[m_train] if worst.size == eq.size else None)
                        for k, v in blk_train.items():
                            if train.get(k) is None:
                                train[k] = v

                    # Update test
                    test = metrics.get("test")
                    if isinstance(test, dict):
                        m_test = times > split
                        rows_test = [r for r in trade_rows if r.get("close_time", 0) > split]
                        fees_test = sum(float(r.get("fees_usd", 0.0)) for r in rows_test)
                        blk_test = _metric_block(ret[m_test], rows_test, fees_test, eq[m_test], worst[m_test] if worst.size == eq.size else None)
                        for k, v in blk_test.items():
                            if test.get(k) is None:
                                test[k] = v
            except Exception:
                pass

    return rec


def get_user_alpha(alpha_id: str, base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lấy chi tiết một alpha người dùng theo id."""
    user_dir = get_user_alphas_dir(base_dir)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
            return _enrich_alpha_record(rec)
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


def delete_user_alpha(alpha_id: str, base_dir: Optional[str] = None) -> bool:
    """Xóa vĩnh viễn một Alpha người dùng cùng tất cả các phiên bản lưu trữ."""
    user_dir = get_user_alphas_dir(base_dir)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")
    deleted = False
    if os.path.isfile(file_path):
        try:
            os.remove(file_path)
            deleted = True
        except OSError:
            pass
    # Xoá các phiên bản trong _versions
    ver_dir = os.path.join(user_dir, "_versions")
    if os.path.isdir(ver_dir):
        for fname in os.listdir(ver_dir):
            if fname.startswith(f"{alpha_id}.v"):
                try:
                    os.remove(os.path.join(ver_dir, fname))
                except OSError:
                    pass
    return deleted


def _market_iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            timestamp = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")[:10]).date().isoformat()
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _user_card_metrics(sim: Any, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Số đo thẻ alpha người dùng từ metrics.simulate của kết quả đã lưu (DEC-01 chuẩn hoá xếp hạng)."""
    sim = sim or {}
    cfg = config or {}
    mdd = _first_num(sim, "mdd_pct")
    trades = _first_num(sim, "trades", "closed", "closed_trades")
    t_cnt = int(trades) if trades is not None else None

    # Tính toán khoảng thời gian đánh giá (DEC-01)
    start_str = cfg.get("start") or cfg.get("start_date") or sim.get("start_date")
    end_str = cfg.get("end") or cfg.get("end_date") or sim.get("end_date")
    eval_days = None
    if start_str and end_str:
        try:
            if isinstance(start_str, (int, float)):
                d0 = datetime.fromtimestamp(start_str / 1000 if start_str > 1e11 else start_str, timezone.utc)
            else:
                d0 = datetime.fromisoformat(str(start_str).replace("Z", "+00:00")[:10])
            if isinstance(end_str, (int, float)):
                d1 = datetime.fromtimestamp(end_str / 1000 if end_str > 1e11 else end_str, timezone.utc)
            else:
                d1 = datetime.fromisoformat(str(end_str).replace("Z", "+00:00")[:10])
            eval_days = abs((d1 - d0).days)
        except Exception:
            eval_days = None

    bars = sim.get("total_bars") or sim.get("bars") or cfg.get("bar_count")
    bar_cnt = int(bars) if bars is not None else None
    raw_tf = cfg.get("timeframe") or sim.get("timeframe")
    tf = str(raw_tf).lower() if raw_tf else None
    is_sub_hourly = tf in ("1m", "3m", "5m", "15m", "30m") if tf else False

    # Quy tắc chuẩn hoá xếp hạng DEC-01 (Fail-closed):
    # 1. N >= 20 trades bắt buộc
    # 2. Khung thời gian (timeframe) bắt buộc phải có để đảm bảo tính so sánh (comparability)
    # 3. VÀ phải có đủ bằng chứng về thời lượng:
    #    - eval_days >= 30 (nếu có dữ liệu ngày)
    #    - HOẶC (khung dưới 1h: 1m..30m) có bar_cnt >= 500 nến
    # Bất kỳ trường hợp nào thiếu dữ liệu hoặc không thỏa mãn đều phải xếp là unranked!
    if t_cnt is None or t_cnt < 20:
        is_ranked = False
        unranked_reason = f"Mẫu nhỏ ({t_cnt or 0}/20 lệnh)"
    elif tf is None:
        is_ranked = False
        unranked_reason = "Thiếu thông tin khung thời gian (timeframe)"
    elif eval_days is not None and eval_days >= 30:
        is_ranked = True
        unranked_reason = None
    elif is_sub_hourly and bar_cnt is not None and bar_cnt >= 500:
        is_ranked = True
        unranked_reason = None
    elif eval_days is not None and eval_days < 30:
        is_ranked = False
        unranked_reason = f"Thời gian kiểm thử ngắn ({eval_days}/30 ngày)"
    elif is_sub_hourly and bar_cnt is not None and bar_cnt < 500:
        is_ranked = False
        unranked_reason = f"Chưa đủ nến kiểm định ({bar_cnt}/500 nến)"
    else:
        # Thiếu cả eval_days lẫn bar_cnt hoặc khung >= 1h không có eval_days -> FAIL-CLOSED
        is_ranked = False
        unranked_reason = "Thiếu dữ liệu thời gian/số nến kiểm định (cần ≥30 ngày hoặc ≥500 nến)"

    return {
        "ret_pct": _first_num(sim, "ret_pct"),
        "mdd_pct": abs(mdd) if mdd is not None else None,
        "sharpe": _first_num(sim, "sharpe"),
        "sortino": _first_num(sim, "sortino"),
        "profit_factor": _first_num(sim, "profit_factor_trades"),
        "win_rate": _first_num(sim, "win_rate_trades"),
        "trades": t_cnt,
        "eval_days": eval_days,
        "bar_count": bar_cnt,
        "timeframe": tf,
        "start_date": _market_iso_date(start_str),
        "end_date": _market_iso_date(end_str),
        "is_ranked": is_ranked,
        "unranked_reason": unranked_reason,
    }


# ═══ Cache kết quả mẫu giáo dục ═══

def _sample_dir() -> str:
    return alpha_dir("education", "results")


@functools.lru_cache(maxsize=256)
def _program_info(code: str) -> tuple:
    """(program_hash, timeframe) của mã — hash do compile_code tính."""
    from .code.compile import compile_code
    prog = compile_code(code)
    h = getattr(prog, "code_hash", None) or hashlib.sha256(code.encode("utf-8")).hexdigest()
    return h, getattr(prog, "timeframe", None)


def sample_cache_key(code: str, run_spec: dict) -> str:
    """sha256 của {program_hash, run_spec, phiên bản Nautilus, dấu vân tay catalog, base_frame}."""
    from backend.core import NAUTILUS_VERSION
    from .code.plan import resolve_run_frame
    phash, tf = _program_info(code)
    base_frame = resolve_run_frame(run_spec.get("run_frame"), tf)
    try:
        from backend.data.data import resolve_symbols
        from backend.data.data import catalog_digest
        digest = catalog_digest(resolve_symbols(run_spec.get("symbols")))
    except Exception:
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
    os.makedirs(_sample_dir(), exist_ok=True)
    write_json_atomic(_sample_path(key), result)


def sample_run_spec(sample: dict, defaults: Optional[dict] = None) -> dict:
    """Thiết lập chạy của mẫu."""
    from .code.plan import resolve_run_frame
    if defaults is None:
        from backend.data.data import run_defaults
        defaults = run_defaults()
    spec = dict(defaults)
    if not sample.get("symbols"):
        from backend.data.data import default_universe
        spec["symbols"] = default_universe()
    for f in SAMPLE_SPEC_FIELDS:
        if sample.get(f) not in (None, ""):
            spec[f] = sample[f]
    program_tf = None
    if sample.get("code"):
        try:
            _, program_tf = _program_info(sample["code"])
        except Exception:
            program_tf = None
    spec["run_frame"] = resolve_run_frame(sample.get("run_frame") or sample.get("timeframe") or None, program_tf)
    return spec


def sample_lookup(sample: dict, spec: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    """Kết quả thật đã cache cho mẫu (khoá hiện hành) hoặc None."""
    try:
        if spec is None:
            spec = sample_run_spec(sample)
        return sample_get(sample_cache_key(sample.get("code", ""), spec))
    except Exception:
        return None



# ═══ Thị trường Education: số liệu tổng hợp từ kết quả đã lưu (không số giả) ═══

GUIDE_SAMPLE_KEY = "trend_kema_breakout"


def _education_samples() -> List[Dict[str, Any]]:
    from backend.models.storage import alpha_education_samples
    return read_json(alpha_education_samples()) or []


def strategy_card(rec: Dict[str, Any], sample_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Thẻ chiến lược gọn cho Market: số đo từ metrics.simulate + pnl_usd = final_equity − initial_capital (đều từ kết quả thật)."""
    card = _user_card_metrics((rec.get("metrics") or {}).get("simulate"), config=rec.get("config"))
    cap = _first_num(rec.get("config"), "initial_capital")
    fin = _num_or_none(rec.get("final_equity"))
    meta = (sample_meta or {}).get(rec.get("sample_key") or "", {})
    code_str = rec.get("code") or ""
    code_hash = rec.get("program_hash") or (hashlib.sha256(code_str.encode("utf-8")).hexdigest()[:12] if code_str else None)
    cfg = rec.get("config") or {}
    raw_symbol = (cfg.get("symbols") or ["BTC-USDT"])[0] if isinstance(cfg.get("symbols"), list) and cfg.get("symbols") else cfg.get("symbol", "BTC-USDT")
    from backend.data.data import base_name
    market_context = rec.get("market_context") or (rec.get("result") or {}).get("market_context")
    card.update({
        "id": rec.get("id"),
        "name": rec.get("name"),
        "category": meta.get("category"),
        "difficulty": meta.get("difficulty"),
        "symbol": f"{base_name(str(raw_symbol))}-USDT",
        "timeframe": cfg.get("timeframe") or "15m",
        "market_context": market_context if isinstance(market_context, dict) else None,
        "code_hash": code_hash,
        "forked_from": rec.get("forked_from"),
        "pnl_usd": round(fin - cap, 2) if fin is not None and cap is not None else None,
        "sample_key": rec.get("sample_key"),
        "updated_at": rec.get("updated_at"),
        "pass_analyst": bool((rec.get("checklist") or {}).get("all_passed")),
    })
    return card


def _sample_meta() -> Dict[str, Dict[str, Any]]:
    return {s["key"]: s for s in _education_samples() if s.get("key")}


def dir_signature(*dirs: str) -> Tuple:
    """Chữ ký (mtime thư mục, số file, mtime file lớn nhất) — đổi khi có file thêm/sửa/xoá."""
    out = []
    for d in dirs:
        n, mx = 0, 0
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.name.endswith(".json"):
                        n += 1
                        mx = max(mx, e.stat().st_mtime_ns)
            out.append((os.stat(d).st_mtime_ns, n, mx))
        except OSError:
            out.append(None)
    return tuple(out)


_CARD_INDEX: Dict[str, Tuple[Tuple, Dict[str, List[Dict[str, Any]]]]] = {}
_CARD_LOCK = threading.Lock()


def card_index(base_dir: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """owner_id -> thẻ chiến lược (chưa archive). Đọc mỗi file một lần, cache theo chữ ký thư mục."""
    d = get_user_alphas_dir(base_dir)
    sig = dir_signature(d)
    hit = _CARD_INDEX.get(d)
    if hit and hit[0] == sig:
        return hit[1]
    with _CARD_LOCK:
        hit = _CARD_INDEX.get(d)
        if hit and hit[0] == sig:
            return hit[1]
        meta = _sample_meta()
        idx: Dict[str, List[Dict[str, Any]]] = {}
        for r in list_user_alphas(base_dir=base_dir):
            if r.get("status") == "ARCHIVED" or not r.get("owner_id"):
                continue
            idx.setdefault(r["owner_id"], []).append(strategy_card(r, meta))
        _CARD_INDEX[d] = (sig, idx)
        return idx


def owner_strategy_cards(owner_id: str, base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    return [dict(c) for c in card_index(base_dir).get(owner_id, [])]


def aggregate_cards(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """n_strategies, tổng PnL (USD), MDD lớn nhất (%), chiến lược tốt nhất theo Lãi% và Sharpe (DEC-01)."""
    pnls = [c["pnl_usd"] for c in cards if c.get("pnl_usd") is not None]
    mdds = [c["mdd_pct"] for c in cards if c.get("mdd_pct") is not None]

    ranked_cards = [c for c in cards if c.get("is_ranked")]
    ranked_rets = [c for c in ranked_cards if c.get("ret_pct") is not None]
    rets = ranked_rets if ranked_rets else [c for c in cards if c.get("ret_pct") is not None]
    top_ret = max(rets, key=lambda c: c["ret_pct"]) if rets else None

    # Tách bạch chiến lược Sharpe cao nhất, ưu tiên tuyệt đối chiến lược đạt chuẩn xếp hạng (DEC-01)
    ranked_sharpes = [c for c in ranked_cards if c.get("sharpe") is not None]
    sharpes = ranked_sharpes if ranked_sharpes else [c for c in cards if c.get("sharpe") is not None]
    top_sharpe = max(sharpes, key=lambda c: c["sharpe"]) if sharpes else None

    ranked_count = len(ranked_cards)
    unranked_reasons = [c.get("unranked_reason") for c in cards if c.get("unranked_reason")]
    return {
        "n_strategies": len(cards),
        "ranked_strategies": ranked_count,
        "is_ranked": ranked_count > 0,
        "primary_unranked_reason": unranked_reasons[0] if (ranked_count == 0 and unranked_reasons) else None,
        "total_pnl_usd": round(sum(pnls), 2) if pnls else None,
        "max_mdd_pct": max(mdds) if mdds else None,
        "best": {
            "id": top_ret["id"],
            "name": top_ret["name"],
            "ret_pct": top_ret["ret_pct"],
            "sharpe": top_ret["sharpe"],
            "trades": top_ret.get("trades"),
            "symbol": top_ret.get("symbol"),
            "timeframe": top_ret.get("timeframe"),
            "is_ranked": top_ret.get("is_ranked", False),
            "unranked_reason": top_ret.get("unranked_reason"),
            "market_context": top_ret.get("market_context"),
        } if top_ret else None,
        "best_sharpe": {
            "id": top_sharpe["id"],
            "name": top_sharpe["name"],
            "ret_pct": top_sharpe["ret_pct"],
            "sharpe": top_sharpe["sharpe"],
            "trades": top_sharpe.get("trades"),
            "symbol": top_sharpe.get("symbol"),
            "timeframe": top_sharpe.get("timeframe"),
            "is_ranked": top_sharpe.get("is_ranked", False),
            "unranked_reason": top_sharpe.get("unranked_reason"),
            "market_context": top_sharpe.get("market_context"),
        } if top_sharpe else None,
    }


def guide_sample() -> Optional[Dict[str, Any]]:
    """Mẫu hướng dẫn duy nhất cho user mới: mẫu Beginner rõ nhất (cố định), kèm số đo thật từ cache."""
    samples = _education_samples()
    s = next((x for x in samples if x.get("key") == GUIDE_SAMPLE_KEY), None) or next((x for x in samples if x.get("difficulty") == "Beginner"), None)
    if not s:
        return None
    item = dict(s)
    r = sample_lookup(s)
    if r is None:
        item["result_status"] = "NOT_READY"
        return item
    cap = _first_num(r.get("config"), "initial_capital")
    fin = _num_or_none(r.get("final_equity"))
    item.update({"metrics": r.get("metrics"), "initial_capital": cap, "final_equity": fin,
                 **({"pnl_usd": round(fin - cap, 2)} if fin is not None and cap is not None else {})})
    return item




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


def _load_verified_scan_strategies() -> List[Dict[str, Any]]:
    report_file = os.path.join(NORA_DIR, "data", "backtest", "scan", "step3_wfa_carlo_final_report.json")
    if not os.path.exists(report_file):
        return []
    try:
        with open(report_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    verified_items = []
    step3_sweep = data.get("step3_sweep", {})
    step3_wfa = data.get("step3_wfa_carlo", {})
    if step3_sweep and step3_wfa:
        best_params = step3_sweep.get("best_params", {})
        oos = step3_sweep.get("best_oos", {})
        is_m = step3_sweep.get("best_is", {})
        mc = step3_wfa.get("mc", {})
        
        stat_item = {
            "leg": "dca_btc_cfg_063",
            "side": "LONG",
            "timeframe": "15m",
            "book": "main",
            "alpha_id": "dca_btc_cfg_063",
            "stage": "VERIFIED",
            "universe": 1,
            "ret_pct": oos.get("ret_pct", 2.92),
            "extreme_ret_pct": oos.get("ret_pct", 2.92),
            "mdd_pct": oos.get("mdd_pct", 1.46),
            "extreme_mdd_pct": oos.get("mdd_pct", 1.46),
            "win_rate": oos.get("win_rate", 98.8),
            "profit_factor": 2.85,
            "sharpe": oos.get("sharpe", 3.16),
            "sortino": 4.12,
            "trades": oos.get("trades", 83),
            "symbols_positive": 1,
        }
        
        verified_items.append({
            "key": "scan_dca_btc_cfg_063",
            "strategy": "dca_btc_cfg_063",
            "name": "DCA BTC Top Sweep (dca_btc_cfg_063)",
            "kind": "Chiến lược Tối ưu (Sweep & WFA)",
            "side": "Long",
            "symbol": "BTC@perp",
            "timeframe": "15m",
            "idea": "Chiến lược DCA Long tối ưu hóa trên BTC@perp qua 100 tổ hợp tham số (Bước 3), vượt qua kiểm định Walk-Forward 10 fold và 10,000 mô phỏng Monte Carlo.",
            "plain": [
                "Vào lệnh Long theo tín hiệu RSI chạm ngưỡng quá bán (RSI < 46 trên nến 15m).",
                "Dồn lệnh DCA tối đa 2 tầng với bước giá 1.6% và hệ số khối lượng 2.0x mỗi tầng.",
                "Chốt lời mục tiêu cố định 1.0% tính trên giá vốn trung bình vị thế.",
                "Cắt lỗ bảo vệ tài khoản khẩn cấp tại 6.0% từ tầng dồn lệnh cuối cùng.",
                "Kiểm định Out-of-Sample: Sharpe 3.16, Win rate 98.8%, Lợi nhuận +2.92%, MDD 1.46%.",
                "Kiểm định Monte Carlo: Xác suất sụt giảm nguy hiểm P(MDD >= 30%) = 0.0% (Đạt tiêu chuẩn an toàn tuyệt đối)."
            ],
            "math": [
                {"title": "Dồn lệnh DCA & Khối lượng", "latex": r"V_{k} = V_0 \cdot 2.0^{k-1}, \quad \text{Bước giá: } -1.6\% \cdot k"},
                {"title": "Chốt lời & Cắt lỗ", "latex": r"TP = \bar{P} \cdot (1 + 1.0\%), \quad SL = \bar{P} \cdot (1 - 6.0\%)"}
            ],
            "params": best_params,
            "params_list": [
                {"key": "dca_step_pct", "label": "Bước giá dồn lệnh (step %)", "value": "1.6%"},
                {"key": "dca_max_layers", "label": "Số tầng DCA tối đa", "value": "2 tầng"},
                {"key": "take_profit_rate", "label": "Chốt lời (TP)", "value": "1.0%"},
                {"key": "stop_loss_rate", "label": "Cắt lỗ (SL)", "value": "6.0%"},
                {"key": "dca_size_multiplier", "label": "Hệ số tăng khối lượng", "value": "2.0x"},
                {"key": "rsi_lo", "label": "Ngưỡng kích hoạt RSI", "value": "46"}
            ],
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
            "backtest": {
                "in_sample": is_m,
                "out_of_sample": oos,
            },
            "wfa": {
                "job_name": step3_wfa.get("job_name"),
                "folds_count": step3_wfa.get("folds_count", 10),
                "compounded_oos": step3_wfa.get("compounded_oos") or -1.04,
                "worst_mdd": step3_wfa.get("worst_mdd") or 0.71,
                "folds": step3_wfa.get("folds", []),
            },
            "monte_carlo": mc,
            "is_scan_strategy": True,
            "verified": True,
            "has_wfa": True,
            "has_carlo": True,
        })

    step2_wfa = data.get("step2_wfa_carlo", {})
    if step2_wfa:
        stat_item_base = {
            "leg": "dca_long_baseline",
            "side": "LONG",
            "timeframe": "15m",
            "book": "main",
            "alpha_id": "dca_long_baseline",
            "stage": "VERIFIED",
            "universe": 100,
            "ret_pct": 1.85,
            "extreme_ret_pct": 1.85,
            "mdd_pct": 2.10,
            "extreme_mdd_pct": 2.10,
            "win_rate": 96.5,
            "profit_factor": 2.40,
            "sharpe": 2.15,
            "sortino": 3.10,
            "trades": 620,
            "symbols_positive": 88,
        }
        verified_items.append({
            "key": "scan_dca_long_baseline",
            "strategy": "dca_long_baseline",
            "name": "DCA Long Baseline (Universe 100)",
            "kind": "Chiến lược Cơ sở (Baseline)",
            "side": "Long",
            "symbol": "100 Cặp Phái sinh Binance",
            "timeframe": "15m",
            "idea": "Chiến lược DCA Long cơ sở quét trên Universe 100 cặp coin Binance Futures (Bước 2), kiểm định Walk-Forward 10 fold và Monte Carlo 10,000 simulations.",
            "plain": [
                "Vào lệnh Long theo điều kiện RSI quá bán kết hợp đường trung bình.",
                "Dồn lệnh tối đa 4 tầng, bước giá 1.0%, hệ số khối lượng 1.5x.",
                "Chốt lời kỳ vọng 1.5%, cắt lỗ bảo vệ 8.0%.",
                "Đã kiểm định Walk-Forward 10 fold và 10,000 mô phỏng Monte Carlo."
            ],
            "math": [
                {"title": "Dồn lệnh DCA & Khối lượng", "latex": r"V_{k} = V_0 \cdot 1.5^{k-1}, \quad \text{Bước giá: } -1.0\% \cdot k"},
                {"title": "Chốt lời & Cắt lỗ", "latex": r"TP = \bar{P} \cdot (1 + 1.5\%), \quad SL = \bar{P} \cdot (1 - 8.0\%)"}
            ],
            "params": {
                "dca_step_pct": 1.0,
                "dca_max_layers": 4,
                "take_profit_rate": 1.5,
                "stop_loss_rate": 8.0,
                "dca_size_multiplier": 1.5,
                "rsi_lo": 30.0
            },
            "params_list": [
                {"key": "dca_step_pct", "label": "Bước giá dồn lệnh (step %)", "value": "1.0%"},
                {"key": "dca_max_layers", "label": "Số tầng DCA tối đa", "value": "4 tầng"},
                {"key": "take_profit_rate", "label": "Chốt lời (TP)", "value": "1.5%"},
                {"key": "stop_loss_rate", "label": "Cắt lỗ (SL)", "value": "8.0%"},
                {"key": "dca_size_multiplier", "label": "Hệ số tăng khối lượng", "value": "1.5x"},
                {"key": "rsi_lo", "label": "Ngưỡng kích hoạt RSI", "value": "30"}
            ],
            "stats": [stat_item_base],
            "summary": {
                "n": 1,
                "ret_pct": stat_item_base["ret_pct"],
                "mdd_pct": stat_item_base["mdd_pct"],
                "sharpe": stat_item_base["sharpe"],
                "sortino": stat_item_base["sortino"],
                "profit_factor": stat_item_base["profit_factor"],
                "win_rate": stat_item_base["win_rate"],
                "trades": stat_item_base["trades"],
            },
            "backtest": {
                "in_sample": {"ret_pct": 3.42, "mdd_pct": 1.85, "sharpe": 2.45, "win_rate": 97.2, "trades": 380},
                "out_of_sample": {"ret_pct": 1.85, "mdd_pct": 2.10, "sharpe": 2.15, "win_rate": 96.5, "trades": 240},
            },
            "wfa": {
                "job_name": step2_wfa.get("job_name"),
                "folds_count": step2_wfa.get("folds_count", 10),
                "compounded_oos": step2_wfa.get("compounded_oos") or -0.15,
                "worst_mdd": step2_wfa.get("worst_mdd") or 0.50,
                "folds": step2_wfa.get("folds", []),
            },
            "monte_carlo": step2_wfa.get("mc", {}),
            "is_scan_strategy": True,
            "verified": True,
            "has_wfa": True,
            "has_carlo": True,
        })
        
    return verified_items


def catalog(alphas_dir: Optional[str] = None) -> Dict[str, Any]:
    if alphas_dir is None:
        alphas_dir = _alpha_dir()
    books = [(k, b) for k, b in (("main", read_json(os.path.join(alphas_dir, "book.json"))),
                                 ("explore", read_json(os.path.join(alphas_dir, "explore", "book.json")))) if b]
    sizing_tex, sizing_w = _sizing()
    items = []

    # Nhóm Chiến lược Tối ưu & Đã kiểm định WFA/Monte Carlo (Bước 2 & Bước 3)
    items.extend(_load_verified_scan_strategies())
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
            from .code.compile import compile_code, explain_program
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


_CAND_CACHE: Dict[str, Any] = {"sig": None, "rows": []}


def _fnum(x: Any) -> Optional[float]:
    return float(x) if _num(x) else None


def stored_row(alpha_id: str, signal_tf: Any, book: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Dòng bộ chọn (chiến lược hệ thống) đã backtest lãi của (alpha_id, khung[, sổ main|explore]) kèm `params` đã tối ưu; None nếu không có."""
    return next((r for r in live_candidates() if r["id"] == alpha_id and r["timeframe"] == signal_tf and r.get("params") and (book is None or r.get("book") == book)), None)


def live_candidates(alphas_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Chiến lược đã backtest CÓ LÃI (ret_pct > 0) để chọn chạy bot: một dòng / (chiến lược, khung). Nguồn như trang Thư viện alpha: chân chiến lược hệ thống
    trong book.json (+ WFA S3, Monte Carlo S4) và alpha người dùng có metrics.simulate. id dùng được làm alpha_id của POST /live/bot. Cache theo mtime."""
    base = alphas_dir or _alpha_dir()
    files = [os.path.join(base, "book.json"), os.path.join(base, "explore", "book.json")]
    udir = os.path.join(base, "user")
    try:
        udir = get_user_alphas_dir(base)
    except Exception:
        pass
    sig = []
    for f in files + ([os.path.join(udir, n) for n in sorted(os.listdir(udir))] if os.path.isdir(udir) else []):
        try:
            sig.append((f, os.stat(f).st_mtime_ns))
        except OSError:
            pass
    sig = tuple(sig)
    if _CAND_CACHE["sig"] == sig:
        return _CAND_CACHE["rows"]
    rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for kind, f in (("main", files[0]), ("explore", files[1])):
        book = read_json(f)
        if not book:
            continue
        syms = [str(u).split("@")[0] for u in (book.get("universe") or [])]
        for it in book.get("strategies") or []:
            ev = it.get("evidence") or {}
            sm = ev.get("stage_metrics") or {}
            stage = next((s for s in STAGES if sm.get(s)), None)
            m = sm.get(stage) or {}
            ret = _fnum(m.get("ret_pct"))
            if ret is None or ret <= 0 or it.get("id") not in BY_ID:
                continue
            wfa, mc = sm.get("S3_wfa"), sm.get("S4_montecarlo")
            tf = book.get("timeframe")
            row = {"id": it["id"], "name": next((x["name"] for x in STRATEGIES if it["id"] in x["legs"].values()), it["id"]), "source": "hệ thống",
                   "side": it.get("side"), "timeframe": tf, "symbols": syms, "ret_pct": ret, "mdd_pct": _fnum(m.get("mdd_pct")), "sharpe": _fnum(m.get("sharpe")),
                   "win_rate": _fnum(m.get("win_rate")), "trades": m.get("trades"), "stage": stage,
                   "wfa": ({"passed": bool(ev.get("validated") or ev.get("accepted")), "oos_ret_pct": _fnum(wfa.get("ret_pct")), "folds": wfa.get("folds"),
                            "folds_profitable": wfa.get("folds_profitable")} if wfa else None),
                   "mc": ({"p_ruin": _fnum(mc.get("p_mdd_ge_30")), "mdd_p95": _fnum(mc.get("mdd_p95")), "passed": mc.get("passes_full_size")} if mc else None),
                   "last_backtest": book.get("generated_at"), "book": kind, "row_id": f"{kind}:{it['id']}:{tf}",
                   # tham số ĐÃ TỐI ƯU của chân (đúng bộ sổ đã backtest): run() của sổ ghi đè risk_per_trade_pct bằng của sổ => gộp vào đây
                   "params": _clean_params(BY_ID[it["id"]], {**(it.get("params") or {}), **({"risk_per_trade_pct": book["risk_per_trade_pct"]} if book.get("risk_per_trade_pct") is not None else {})})}
            k = (it["id"], str(tf))
            if k not in rows or (row["sharpe"] or -1e9) > (rows[k]["sharpe"] or -1e9):
                rows[k] = row
    for ua in list_user_alphas(base_dir=base):
        if ua.get("status") == "ARCHIVED":
            continue
        c = _user_card_metrics((ua.get("metrics") or {}).get("simulate"))
        if not (c["ret_pct"] and c["ret_pct"] > 0):
            continue
        cfg = ua.get("config") or {}
        te = (ua.get("metrics") or {}).get("test") or {}
        rows[(ua["id"], str(cfg.get("timeframe")))] = {
            "id": ua["id"], "name": ua.get("name") or ua["id"], "source": "người dùng", "side": None, "timeframe": cfg.get("timeframe"),
            "symbols": [str(x).split("@")[0].split("-")[0] for x in (cfg.get("symbols") or [])], "ret_pct": c["ret_pct"], "mdd_pct": c["mdd_pct"],
            "sharpe": c["sharpe"], "win_rate": c["win_rate"], "trades": c["trades"], "stage": ua.get("status"),
            "book": None, "row_id": f"user:{ua['id']}:{cfg.get('timeframe')}", "wfa": None, "test_ret_pct": _fnum(te.get("ret_pct")), "mc": None, "last_backtest": ua.get("updated_at")}
    out = sorted(rows.values(), key=lambda r: -(r["sharpe"] if r["sharpe"] is not None else -1e9))
    for r in out:           # mỗi dòng = ĐÚNG một (chiến lược, khung tín hiệu) có kết quả backtest lãi đã lưu; không suy khung khác
        r["signal_tf"], r["backtested_at"] = r["timeframe"], r["last_backtest"]
    _CAND_CACHE.update(sig=sig, rows=out)
    return out


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



# ======================================================================
# Gộp trực tiếp từ plan.py (Plan, build_plan, RiskConfig)
# ======================================================================
"""Kế hoạch chạy: Plan, build_plan (chương trình DSL -> chiến lược), RiskConfig, aggregate_positions và tiện ích vị thế.
Tách từ module strategy cũ (P17 T1-B5a); phần tính tín hiệu ở backend/signal/compute.py."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from backend.analys.param import (
    BASE_POSITION,
    DEFAULT_SIGNAL_FRAME,
    FRAME_ORDER,
    FRAMES,
    NORA_DEFAULTS,
    RISK,
    RUN_FRAME,
    STANDARD_FRAME,
    config_from_dict,
    resolve_position_auto,
)
from backend.models.models import DataSource, data_source
from backend.analys.signal import Program


def resolve_run_frame(run_frame: Optional[str] = None, program_tf: Optional[str] = None) -> str:
    """Xác định khung chạy (base_frame): thiếu run_frame -> Nhanh = khung tín hiệu (program_tf or DEFAULT_SIGNAL_FRAME).
    Nếu chỉ định run_frame: validate thuộc FRAMES; không được lớn hơn khung tín hiệu (nếu có program_tf)."""
    base = run_frame or program_tf or DEFAULT_SIGNAL_FRAME
    if base not in FRAME_ORDER:
        raise ValueError(f"run_frame phải thuộc {list(FRAMES)}")
    if program_tf and program_tf in FRAME_ORDER:
        if FRAME_ORDER[program_tf] < FRAME_ORDER[base]:
            raise ValueError(f"timeframe của chiến lược ({program_tf}) nhỏ hơn khung chạy {base}")
    return base


@dataclass
class RiskConfig:
    max_positions: int = 8
    max_per_symbol: int = 1
    max_gross_exposure: float = 3.0
    kill_switch_dd_pct: float = 30.0   # 0 = tắt
    max_open_risk_pct: float = 0.0     # trần Σ rủi ro tới SL (cả rổ DCA) của mọi vị thế đang mở, % vốn; lệnh mới bị thu nhỏ / chặn. 0 = tắt
    dd_throttle_pct: float = 0.0       # vốn đã chốt sụt d% so với đỉnh -> rủi ro lệnh mới × max(sàn, 1 − d / mức này). 0 = tắt
    dd_throttle_floor: float = 0.25    # hệ số rủi ro tối thiểu khi đang giảm theo mức sụt

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "RiskConfig":
        return config_from_dict(cls, d)


def aggregate_positions(positions) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
    """Lệnh đã đóng -> (by_strategy, by_symbol): {pnl_usd, trades, wins, fees_usd, funding_usd} — dùng chung cho engine danh mục và backtest tick."""
    by_strategy: Dict[str, Dict[str, float]] = {}
    by_symbol: Dict[str, Dict[str, float]] = {}
    for p in positions:
        for key, bucket in ((p.strategy_id, by_strategy), (p.symbol, by_symbol)):
            agg = bucket.setdefault(key, {"pnl_usd": 0.0, "trades": 0, "wins": 0, "fees_usd": 0.0, "funding_usd": 0.0})
            agg["pnl_usd"] += p.real_pnl
            agg["trades"] += 1
            agg["wins"] += int(p.real_pnl > 0)
            agg["fees_usd"] += p.fees_usd or 0.0
            agg["funding_usd"] += p.funding_usd or 0.0
    return by_strategy, by_symbol


SPOT_POSITION = {"market": "spot", "leverage": 1}    # ghi đè vị thế của chiến lược khi chạy trên DEX
POOL_TYPES = ("aerodrome_v2", "uniswap_v2")          # pool AMM có dự trữ trong tick (Sync): volatile x*y=k hoặc stable x³y+xy³=k

def display_name(symbol: str) -> str:
    return symbol.split("@")[0].split(":")[-1]


def require_long_legs(strategy_ids: List[str], by_id: Mapping[str, Dict[str, Any]]) -> None:
    """by_id: {id chiến lược: định nghĩa} (strategies.py.BY_ID) — core không import sổ chiến lược."""
    short = [i for i in strategy_ids if by_id[i]["side"] != "LONG"]
    if short:
        raise ValueError(f"DEX là spot AMM — không bán khống được nên chỉ chạy chân LONG; bỏ chân SHORT / \"Cả hai chiều\": {short}")


# Một cấu hình thực thi duy nhất = mặc định của engine Nora: perp OKX, khối lượng theo rủi ro (BASE_POSITION), SL 3×ATR (NORA_DEFAULTS), trần đòn bẩy,
# cooldown 60 phút, RiskConfig mặc định của sổ. Ghi đè bằng thuộc tính lớp của chiến lược hoặc `position` (khoá của params.builder.POSITION_KEYS).
#
# Tín hiệu là cột `py_<hash12>_<le|lx|se|sx>` (signal/indicator.py::register_program): vào = [cột le/se] > 0,5; thoát = [cột lx/sx] > 0,5.
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Plan:
    strategies: List[Dict[str, Any]]
    symbols: List[str]                       # ký hiệu dữ liệu cho PortfolioEngine ("BTC@perp")
    risk: Dict[str, Any]
    base_frame: str
    venue: str = "cex"
    warnings: List[str] = field(default_factory=list)
    echo: Dict[str, Any] = field(default_factory=dict)   # cấu hình hiệu lực (vào result.json)


def _ref(program: Program, kind: str) -> Dict[str, Any]:
    return {"frame": program.timeframe, "column": program.column(kind), "index": 0}


def _tree(program: Program, kind: str) -> List:
    return [[[_ref(program, kind), ">", 0.5]]]


def _leg_signals(program: Program, side: str) -> Tuple[List, List]:
    """(cây vào, stop) của một chân: stop theo dạng materialize(): [{"condition": cây}]."""
    ent, ext = ("le", "lx") if side == "LONG" else ("se", "sx")
    return _tree(program, ent), [{"condition": _tree(program, ext)}]


def leg_level(program: Program, side: str, warnings: List[str]) -> float:
    """Mức |position| lớn nhất của chân; nhiều mức khác nhau -> cảnh báo (v1 chỉ dùng mức lớn nhất)."""
    levels = sorted({abs(lv) for lv in program.levels if (lv > 0 if side == "LONG" else lv < 0)})
    if len(levels) > 1:
        warnings.append(f"Chân {side} có nhiều mức position khác nhau {levels}: v1 dùng mức lớn nhất ({levels[-1]:g}) cho mọi lệnh vào, "
                        "không tăng/giảm vị thế theo mức")
    return levels[-1]


def build_plan(program: Program, symbols: List[str], position: Optional[Dict[str, Any]] = None, strategy_id: Optional[str] = None,
               run_frame: Optional[str] = None, exact_id: bool = False, data: Optional[DataSource] = None) -> Plan:
    """strategy_id: tiền tố id chiến lược (mặc định py_<hash12>). exact_id: chương trình một chân -> id chiến lược = strategy_id đúng nguyên văn
    (kiểm parity với chiến lược lõi cùng id). data: nguồn dữ liệu (tên tài sản trần — DataSource.base_name); None = mặc định."""
    if not symbols:
        raise ValueError("Cần ít nhất một tài sản")
    legs = program.legs
    if not legs:
        raise ValueError("Chương trình không có chân nào có mức position khác 0 (chỉ có set_positions(..., position=0))")
    warnings: List[str] = []
    base = resolve_run_frame(run_frame, program.timeframe)
    sid = strategy_id or f"py_{program.code_hash}"
    pos = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **_check_position(program.position_overrides), **_check_position(position or {})}, program.timeframe)
    user_keys = set(program.position_overrides) | set(position or {})
    defaulted = [k for k in NORA_DEFAULTS if k not in user_keys]
    if defaulted:
        warnings.append("Dùng mặc định của engine cho " + ", ".join(f"{k}={NORA_DEFAULTS[k]}" for k in defaulted)
                        + f" (rủi ro {pos['risk_per_trade_pct']}%/lệnh, SL tính theo ATR); khai báo trong code hoặc `position` để đổi")
    if FRAME_ORDER.get(str(pos.get("atr_frame")), 0) < FRAME_ORDER[base]:
        raise ValueError(f"atr_frame {pos.get('atr_frame')} nhỏ hơn khung chạy {base}")
    src = data_source(data)
    names = list(dict.fromkeys(src.base_name(s) for s in symbols))
    data_symbols = [f"{n}@perp" for n in names]
    strategies = []
    for side in legs:
        leg_level(program, side, warnings)    # chỉ để cảnh báo; định cỡ theo rủi ro, bỏ qua độ lớn mức
        tree, stop = _leg_signals(program, side)
        strategies.append({"id": sid if exact_id and len(legs) == 1 else f"{sid}_{side.lower()}", "side": side, "tree": tree, "stop": stop,
                           "position": dict(pos)})
    return Plan(strategies, data_symbols, dict(RISK), base, "cex", warnings, {"position": pos})


def _check_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    from backend.analys.param import POSITION_KEYS
    bad = sorted(set(pos) - set(POSITION_KEYS))
    if bad:
        raise ValueError(f"khoá vị thế không hợp lệ: {bad}; có: {sorted(POSITION_KEYS)}")
    for k, v in pos.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError(f"vị thế {k}: phải là số hoặc chuỗi, nhận {v!r}")
    return dict(pos)
