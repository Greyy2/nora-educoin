"""Metadata duy nhất cho UI (GET /api/studio/meta): khung chạy, giới hạn trường, hằng số cổng Monte Carlo, loại job, vũ trụ, chỉ số, hồ sơ rủi ro, đường dẫn dữ liệu.

build_meta() chỉ LẮP RÁP từ nguồn thật (carlo, metrics, data, jobs.runner, strategies, models.position_size/params); các mô hình yêu cầu pydantic
của route (nguồn của giới hạn + danh sách khung) do route truyền vào (`limit_models`) nên models/ không import ngược routes/.
"""
import hashlib
import json
import os
import re
from typing import Any, Dict, List

from backend.models import storage as store
from backend.analys.param import FRAME_MS

_BOUNDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems")
BOOK_DEFAULT_FRAME = "1h"      # khung chạy mặc định của backtest/WFA sổ (frames.defaults.book)
DEFAULT_EXEC_MODE = "fast"     # chế độ khớp lệnh mặc định: fast = khung tín hiệu; standard = nến 1m


def _prop(model, field: str) -> Dict[str, Any]:
    p = model.model_json_schema()["properties"][field]
    for alt in p.get("anyOf", []):   # Optional[...] -> nhánh không-null
        if alt.get("type") != "null":
            return {**alt, **{k: v for k, v in p.items() if k != "anyOf"}}
    return p


def _choices(model, field: str) -> List[str]:
    """Tập giá trị mà validator của route chấp nhận: pattern `^(a|b|c)$` hoặc enum/Literal (Pydantic schema)."""
    p = _prop(model, field)
    if "enum" in p:
        return list(p["enum"])
    m = re.match(r"^\^\(([^()]*)\)\$$", p.get("pattern", ""))
    return m.group(1).split("|") if m else []


def _limits(limit_models: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, model in limit_models.items():
        if not model:
            continue
        fields = {}
        for f in model.model_json_schema()["properties"]:
            p = _prop(model, f)
            b = {k: p[k] for k in _BOUNDS if k in p}
            if b:
                if "default" in p:
                    b["default"] = p["default"]
                if name == "book_mc" and p.get("description"):   # mô tả tiếng Việt của Field McRequest (một nơi)
                    b["help_vi"] = p["description"]
                fields[f] = b
        out[name] = fields
    return out


def _gates() -> List[Dict[str, Any]]:
    """Hằng số ngưỡng Monte Carlo hiện hành (carlo/carlo.py) — UI đọc cho chú giải và cổng chuẩn."""
    from backend.carlo import carlo
    return [{"key": name, "value": getattr(carlo, name), "source": "carlo/carlo.py"}
            for name in ("MC_MIN_SIMULATIONS", "MC_MAX_SIMULATIONS", "MC_RUIN_THRESHOLD_PCT", "MC_MAX_RUIN_PCT", "STRESS_MAX_MDD_PCT")]


def _live() -> Dict[str, Any]:
    return {"modes": ["paper", "testnet", "live"], "venues": ["okx"], "books": ["main", "explore"], "engines": ["unified"]}


def _engine() -> Dict[str, Any]:
    from backend.nautilus.version import ENGINE_NAME, NAUTILUS_VERSION
    from backend.analys.param import STANDARD_FRAME
    return {"name": ENGINE_NAME, "version": NAUTILUS_VERSION, "docs_url": "https://nautilustrader.io/docs/latest/",
            "default_exec_mode": DEFAULT_EXEC_MODE, "standard_frame": STANDARD_FRAME,
            "run_modes": ["backtest"]}



_NO_SIM_HELP = "Nautilus không mô phỏng — bị bỏ qua (có cảnh báo trong kết quả)"
UNSUPPORTED = [   # tính năng của Nautilus 1.231 mà engine báo không mô phỏng (results["warnings"]); UI ẩn/khoá, API bỏ qua + cảnh báo (không giả số)
    {"key": "slippage_rate", "condition": "> 0", "unsupported": True, "help_vi": _NO_SIM_HELP},
    {"key": "limit_through_pct", "condition": "> 0", "unsupported": True, "help_vi": _NO_SIM_HELP},
    {"key": "stop_fill", "condition": "== 'extreme'", "unsupported": True, "help_vi": _NO_SIM_HELP},
    {"key": "intrabar_path", "condition": "== 'adverse_first'", "unsupported": True,
     "help_vi": "Nautilus không mô phỏng — engine từ chối (ValueError): chỉ 'ohlc' / 'adaptive'"},
    {"key": "maintenance_margin_rate", "condition": "always", "unsupported": True, "help_vi": _NO_SIM_HELP + " (thanh lý)"},
    {"key": "liquidation", "condition": "always", "unsupported": True, "help_vi": _NO_SIM_HELP + " (thanh lý: vị thế đòn bẩy không bị thanh lý)"},
    {"key": "funding", "condition": "always", "unsupported": True, "help_vi": _NO_SIM_HELP + " (funding perp: funding_usd = 0)"},
    {"key": "venue_dex", "condition": "always", "unsupported": True, "help_vi": "Nautilus không mô phỏng DEX/AMM: tài sản DEX và backtest tick bị từ chối (501 NOT_READY)"},
]


def _jobs() -> Dict[str, Any]:
    from backend.jobs import runner
    kinds = []
    for kind, entry in runner.KINDS.items():
        dest = runner.persist_dest_base(kind)
        kinds.append({"kind": kind, "label_vi": entry["label_vi"], "persist_to": os.path.relpath(dest, store.data_home()) if dest else None,
                      "ephemeral": kind in runner.EPHEMERAL_KINDS,
                      "params": sorted(entry["params"])})
    return {"kinds": kinds}


def _risk_profiles() -> Dict[str, Any]:
    from backend.analys.position import RISK_PROFILES
    return {k: {"name": v.name, "label_vi": v.label_vi, "description": v.description, "sl_anchor": v.sl_anchor, "sl_required": v.sl_required,
                "dca_mode": v.dca_mode, "dca_max_limit": v.dca_max_limit, "exits_allowed": list(v.exits_allowed),
                "exits_required_any": list(v.exits_required_any), "sizing_default": v.sizing_default, "reentry_rule": v.reentry_rule,
                "portfolio_bucket": v.portfolio_bucket} for k, v in RISK_PROFILES.items()}


def build_meta(limit_models: Dict[str, Any]) -> Dict[str, Any]:
    """limit_models: {tên: lớp pydantic} của route — nguồn giới hạn trường (`limits`); các khoá bắt buộc: custom_backtest (trường run_frame),
    book_backtest_req (trường run_frame) cho danh sách khung."""
    from backend.carlo import carlo
    from backend.data import data as market_data
    from backend.metrics.charts import EDUCATION_HIDDEN_SECTIONS, NOTE_TOUR
    from backend.metrics.metrics import METRIC_DEFS, METRIC_GROUPS
    from backend.analys.param import DEFAULT_ALLOCATION
    from backend.alpha.strategies import book_engine_status
    home = store.data_home()
    rel = lambda p: os.path.relpath(p, home)   # noqa: E731
    main_path, explore_path = store.alpha_file("book"), store.alpha_dir("explore", "book.json")
    main_book, explore_book = store.read_json(main_path), store.read_json(explore_path)
    okx_root = os.path.dirname(market_data.default_catalog_path())   # data/market/okx: sàn triển khai duy nhất
    perp = [a["symbol"] for a in market_data.coverage()]
    book_frames = _choices(limit_models["book_backtest_req"], "run_frame")
    custom_frames = _choices(limit_models["custom_backtest"], "run_frame")
    limits = _limits({k: m for k, m in limit_models.items() if k != "book_backtest_req"})
    payload = {
        "gates": _gates(),
        "frames": {"all": list(FRAME_MS), "custom_backtest": custom_frames, "book": book_frames,
                   "defaults": {"custom_backtest": custom_frames[0] if custom_frames else None,
                                "book": BOOK_DEFAULT_FRAME if BOOK_DEFAULT_FRAME in book_frames else (book_frames[0] if book_frames else None)}},
        "live": _live(),
        "jobs": _jobs(),
        "universe": {"data": {"exchange": "okx", "instrument": "perp", "assets": perp, "markets": {"okx": rel(okx_root)}},
                     "book": list((main_book or {}).get("universe") or []), "explore": list((explore_book or {}).get("universe") or [])},
        "limits": limits,
        "stress": carlo.STRESS_SCENARIOS,
        "metrics": {"defs": METRIC_DEFS, "groups": METRIC_GROUPS},
        "explain_tour": NOTE_TOUR,
        "education_hidden_sections": EDUCATION_HIDDEN_SECTIONS,
        "engine": _engine(),
        "unsupported": UNSUPPORTED,
        "risk_profiles": _risk_profiles(),
        "allocation": DEFAULT_ALLOCATION,
        "books": {"main": book_engine_status(main_book), "explore": book_engine_status(explore_book)},
        "paths": {"book": rel(main_path), "explore_book": rel(explore_path), "presets": rel(store.alpha_file("presets")),
                  "alpha_user": rel(store.alpha_user_dir()), "cache_process": rel(store.cache_process_dir()), "market": {"okx": rel(okx_root)}},
    }
    payload["version"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    return payload
