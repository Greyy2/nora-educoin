"""P9.0 — kiểm luật phụ thuộc của ADR-P9 (docs/bmad/adr-p9-backend-layout.md §2 "Luật phụ thuộc").

Cây đích chưa tồn tại (P9.2..P9.8 chuyển dần), nên test ánh xạ ĐƯỜNG DẪN HIỆN TẠI -> TẦNG ĐÍCH bằng bảng LAYER_RULES (theo §3 của ADR)
rồi phân tích import (ast, gồm cả import cục bộ trong hàm) của MỌI module trong backend/.

Luật (ADR §2):
  core <- {metrics, regime, wfa, carlo, verdict} <- optimize <- {live, routes};   crawl chỉ được gọi từ optimize, live, routes;
  core không import gì ngoài core; trong core theo thứ tự models <- params <- indicator <- signal <- position_size <- backtest
  (file trước không import file sau).
Diễn giải của test này:
  - tầng giữa {metrics, regime, wfa, carlo, verdict} được import core và import lẫn nhau (cùng hạng), KHÔNG import optimize/live/routes/crawl;
  - crawl chỉ import crawl (dữ liệu và cấu hình nạp ở tầng trên rồi truyền xuống);
  - optimize import core + tầng giữa + crawl + optimize; live thêm optimize; routes import mọi tầng trừ main;
  - module có dòng đánh dấu `# P9-SHIM` trong 5 dòng đầu là shim tương thích (đường dẫn cũ tái xuất đường dẫn mới) -> không tính khi làm bên import.

Chế độ:
  - BÁO CÁO (mặc định): test luôn xanh, ghi danh sách vi phạm vào docs/bmad/p9_layering_report.md và in ra (pytest -s).
  - NGHIÊM NGẶT (P9.10): NORA_LAYERING_STRICT=1 -> fail nếu còn vi phạm (hoặc module chưa có trong bảng ánh xạ).
  - NORA_LAYERING_WRITE=0 tắt việc ghi file báo cáo.
"""
import ast
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

NORA = Path(__file__).resolve().parents[1]
BACKEND = NORA / "backend"
REPORT = NORA / "docs" / "bmad" / "p9_layering_report.md"

STRICT = os.environ.get("NORA_LAYERING_STRICT", "0") not in ("", "0", "false", "False")
WRITE = os.environ.get("NORA_LAYERING_WRITE", "1") not in ("", "0", "false", "False")

MID = {"metrics", "regime", "wfa", "carlo", "verdict"}
ALLOWED: Dict[str, set] = {
    "core": {"core"},
    "metrics": {"core"} | MID,
    "regime": {"core"} | MID,
    "wfa": {"core"} | MID,
    "carlo": {"core"} | MID,
    "verdict": {"core"} | MID,
    "crawl": {"crawl"},
    "optimize": {"core", "crawl", "optimize"} | MID,
    "live": {"core", "crawl", "optimize", "live"} | MID,
    "routes": {"core", "crawl", "optimize", "live", "routes"} | MID,
}
EXEMPT_LAYERS = {"script"}      # không ràng buộc (script vận hành / nghiên cứu)

# Thứ tự trong core: file hạng thấp KHÔNG được import file hạng cao hơn.
CORE_ORDER = ["models", "params", "indicator", "signal", "position_size", "backtest"]


# Bảng ánh xạ: đường dẫn hiện tại (tính từ backend/, bỏ .py, dùng "/") -> (tầng đích, hạng trong core hoặc None).
# Khớp theo tiền tố DÀI NHẤT. Nguồn: ADR §3 + chỉ đạo P9.2 (promote và utils/{lru,jsonsafe} nằm trong crawl/store).
def _r(name: str) -> int:
    return CORE_ORDER.index(name)


LAYER_RULES: List[Tuple[str, str, Optional[int]]] = [
    # --- crawl (P9.2: đã chuyển thật vào backend/crawl/; đường dẫn cũ là shim) ---
    ("crawl", "crawl", None),
    ("core", "core", None),                                  # core/__init__ và mọi file chưa liệt kê
    ("db", "crawl", None),
    ("core/data", "crawl", None),
    ("utils/lru", "crawl", None),
    ("utils/jsonsafe", "crawl", None),
    # --- core: models ---
    ("core/execute/models", "core", _r("models")),
    ("core/execute/events", "core", _r("models")),
    ("core/execute/account", "core", _r("models")),
    ("core/execute/ledger", "core", _r("models")),
    # --- core: params ---
    ("core/params/schema", "core", _r("params")),
    ("core/params/template", "core", _r("params")),
    ("core/params/builder", "core", _r("params")),
    ("core/params/presets", "optimize", None),               # -> optimize/book/build.py
    ("core/params/modes", "routes", None),                   # -> routes/modes.py
    ("core/params", "core", _r("params")),
    ("core/strategy/book", "core", _r("params")),            # materialize, BASE_POSITION
    ("core/strategy/library", "core", _r("params")),         # P9.9 thành dữ liệu
    ("core/strategy", "core", _r("params")),
    # --- core: indicator ---
    ("core/signals/kernels", "core", _r("indicator")),
    ("core/strategy/pydsl/features", "core", _r("indicator")),
    ("core/strategy/pydsl/ops", "core", _r("indicator")),
    # --- core: signal ---
    ("core/signals", "core", _r("signal")),                  # evaluator, snapshot, diagnostics
    ("core/strategy/pydsl/profiles", "core", _r("backtest")),   # build_plan -> core/backtest.py
    ("core/strategy/pydsl/weights", "optimize", None),       # nạp ở optimize, không nạp trong core
    ("core/strategy/pydsl", "core", _r("signal")),           # spec, parser, program, errors, explain
    # --- core: position_size ---
    ("core/execute/policy", "core", _r("position_size")),
    ("core/execute/risk", "core", _r("position_size")),
    # --- core: backtest (engine thực thi) ---
    ("core/backtest/run", "optimize", None),                 # run_job -> optimize/process/tasks.py
    ("core/backtest/custom_run", "optimize", None),
    ("core/backtest/tick_run", "optimize", None),
    ("core/backtest/edu_precompute", "optimize", None),
    ("core/backtest", "core", _r("backtest")),               # engine, portfolio, dex, kernel
    ("core/execute", "core", _r("backtest")),                # venue, amm, tracker, manager, sim_venue, runner (P9.4b gỡ)
    # --- metrics ---
    ("core/metrics/diagnose", "verdict", None),
    ("core/metrics/diagnose_inputs", "verdict", None),       # phần nạp dữ liệu -> optimize/process/tasks.py (khi tách)
    ("core/metrics", "metrics", None),                       # returns, portfolio, xno, trades
    ("core/analytics/insights", "verdict", None),
    ("core/analytics/user_alphas", "optimize", None),
    ("core/analytics/strategy_doc", "optimize", None),
    ("core/analytics/top_agents", "script", None),           # -> test/scripts/
    ("core/analytics", "metrics", None),                     # dashboard, signal_explain, feeds
    # --- regime / wfa / carlo / verdict ---
    ("core/regime/report", "optimize", None),                # run_job
    ("core/regime", "regime", None),
    ("wfa/run", "optimize", None),                           # run_job
    ("wfa", "wfa", None),
    ("carlo", "carlo", None),
    ("optimize/funnel/antiluck", "verdict", None),
    # --- optimize ---
    ("optimize", "optimize", None),
    ("utils/jobs", "optimize", None),                        # -> optimize/process/process.py
    ("utils/parallel", "optimize", None),                    # -> optimize/process/workers.py
    ("utils/memwatch", "optimize", None),
    ("utils/ops", "script", None),                           # shell/ops, không phải module import
    ("utils", "optimize", None),
    # --- live ---
    ("live", "live", None),
    # --- routes ---
    ("api", "routes", None),
    ("main", "routes", None),
]
_RULES_SORTED = sorted(LAYER_RULES, key=lambda r: -len(r[0]))


def layer_of(mod: str) -> Tuple[Optional[str], Optional[int]]:
    """mod = 'core/data/loader' (không có 'backend/'). Trả (tầng, hạng core) hoặc (None, None) nếu chưa ánh xạ."""
    for prefix, layer, rank in _RULES_SORTED:
        if mod == prefix or mod.startswith(prefix + "/"):
            return layer, rank
    return None, None


def _modname(path: Path) -> str:
    rel = path.relative_to(BACKEND).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return "/".join(parts)


def _all_modules() -> Dict[str, Path]:
    out = {}
    for p in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        out[_modname(p)] = p
    return out


def _is_shim(path: Path) -> bool:
    head = "\n".join(path.read_text(encoding="utf-8").split("\n")[:5])
    return "# P9-SHIM" in head


def _imports_of(path: Path, mod: str, modules: Dict[str, Path]) -> List[Tuple[str, int]]:
    """Mọi import tới module backend (gồm import cục bộ trong hàm) -> [(đường dẫn module backend, số dòng)]."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    is_pkg = path.name == "__init__.py"
    pkg_parts = mod.split("/") if mod else []
    if not is_pkg:
        pkg_parts = pkg_parts[:-1]
    found: List[Tuple[str, int]] = []

    def add(dotted: str, line: int) -> None:
        parts = dotted.split(".")
        if parts and parts[0] == "backend":
            found.append(("/".join(parts[1:]), line))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                add(a.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else list(pkg_parts)
                base_dotted = ".".join(["backend"] + base + ([node.module] if node.module else []))
            else:
                base_dotted = node.module or ""
            if not base_dotted.startswith("backend"):
                continue
            base_path = "/".join(base_dotted.split(".")[1:])
            for a in node.names:
                cand = f"{base_path}/{a.name}" if base_path else a.name
                if a.name != "*" and cand in modules:   # from backend.core.data import shared  -> module con
                    found.append((cand, node.lineno))
                else:
                    found.append((base_path, node.lineno))
    return found


def collect() -> dict:
    modules = _all_modules()
    violations: List[dict] = []
    unmapped: List[str] = []
    shims: List[str] = []
    edges = Counter()
    for mod, path in modules.items():
        if mod == "":
            continue
        if _is_shim(path):
            shims.append(mod)
            continue
        layer, rank = layer_of(mod)
        if layer is None:
            unmapped.append(mod)
            continue
        if layer in EXEMPT_LAYERS:
            continue
        seen = set()
        for tgt, line in _imports_of(path, mod, modules):
            if tgt == "" or tgt == mod:
                continue
            t_layer, t_rank = layer_of(tgt)
            if t_layer is None or t_layer in EXEMPT_LAYERS:
                continue
            key = (tgt, line)
            if key in seen:
                continue
            seen.add(key)
            edges[(layer, t_layer)] += 1
            if t_layer not in ALLOWED[layer]:
                violations.append({"rule": f"{layer} -> {t_layer}", "from": mod, "to": tgt, "line": line})
            elif layer == "core" and rank is not None and t_rank is not None and t_rank > rank:
                violations.append({"rule": f"core order {CORE_ORDER[rank]} -> {CORE_ORDER[t_rank]}", "from": mod, "to": tgt, "line": line})
    return {"modules": len(modules), "violations": violations, "unmapped": unmapped, "shims": shims, "edges": edges}


def render(res: dict) -> str:
    by_rule: Dict[str, List[dict]] = defaultdict(list)
    for v in res["violations"]:
        by_rule[v["rule"]].append(v)
    L = [
        "# P9 — báo cáo luật phụ thuộc (tự sinh bởi nora/test/test_layering.py, chế độ BÁO CÁO)",
        "",
        "Không sửa tay. Sinh lại: `PYTHONDONTWRITEBYTECODE=1 backend/utils/ops/run_limited.sh --no-lock -- -m pytest -q test/test_layering.py`.",
        "Bật bắt buộc (P9.10): `NORA_LAYERING_STRICT=1`. Luật: ADR-P9 §2; ánh xạ đường dẫn hiện tại -> tầng đích: bảng `LAYER_RULES` trong test.",
        "",
        f"- Module backend: {res['modules']} · shim (`# P9-SHIM`, bỏ qua): {len(res['shims'])} · chưa ánh xạ: {len(res['unmapped'])}",
        f"- **Vi phạm: {len(res['violations'])}**",
        "",
        "## Tóm tắt theo luật",
        "",
        "| Luật | Số vi phạm |",
        "|---|---:|",
    ]
    for rule, vs in sorted(by_rule.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        L.append(f"| {rule} | {len(vs)} |")
    if not by_rule:
        L.append("| (không có) | 0 |")
    L += ["", "## Chi tiết", ""]
    for rule, vs in sorted(by_rule.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        L.append(f"### {rule} ({len(vs)})")
        L.append("")
        for v in sorted(vs, key=lambda x: (x["from"], x["line"], x["to"])):
            L.append(f"- `backend/{v['from']}.py:{v['line']}` -> `{v['to']}`")
        L.append("")
    if res["unmapped"]:
        L += ["## Module chưa có trong bảng ánh xạ", ""] + [f"- `{m}`" for m in sorted(res["unmapped"])] + [""]
    if res["shims"]:
        L += ["## Shim (tương thích ngược, gỡ ở P9.10)", ""] + [f"- `{m}`" for m in sorted(res["shims"])] + [""]
    return "\n".join(L)


def test_layering_rules():
    res = collect()
    assert res["modules"] > 100, "không đọc được backend/ (đường dẫn sai?)"
    text = render(res)
    if WRITE:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        if not REPORT.exists() or REPORT.read_text(encoding="utf-8") != text:
            REPORT.write_text(text, encoding="utf-8")
    print(f"\n[layering] modules={res['modules']} shims={len(res['shims'])} unmapped={len(res['unmapped'])} violations={len(res['violations'])}")
    for rule, n in Counter(v["rule"] for v in res["violations"]).most_common():
        print(f"[layering]   {rule}: {n}")
    if STRICT:
        assert not res["unmapped"], f"module chưa ánh xạ: {res['unmapped']}"
        assert not res["violations"], f"{len(res['violations'])} vi phạm luật phụ thuộc — xem {REPORT}"


def test_layer_table_sanity():
    """Bảng ánh xạ tự kiểm: vài đường dẫn đã biết phải rơi đúng tầng (chống sửa bảng nhầm)."""
    assert layer_of("core/data/loader") == ("crawl", None)
    assert layer_of("db/local_pkl") == ("crawl", None)
    assert layer_of("crawl/store") == ("crawl", None)
    assert layer_of("api/routers/book") == ("routes", None)
    assert layer_of("core/backtest/engine") == ("core", _r("backtest"))
    assert layer_of("core/backtest/run") == ("optimize", None)
    assert layer_of("core/signals/kernels") == ("core", _r("indicator"))
    assert layer_of("optimize/funnel/antiluck") == ("verdict", None)
    assert layer_of("core/metrics/diagnose_inputs") == ("verdict", None)
    assert layer_of("core/metrics/returns") == ("metrics", None)
    assert layer_of("live/okx") == ("live", None)
