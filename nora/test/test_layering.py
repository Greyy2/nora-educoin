"""Luật phụ thuộc của backend/ (P17 T1-B5): routes -> jobs -> strategies -> {wfa, nautilus} -> {metrics, carlo} -> data -> {alpha, signal} -> models.

Phân tích import bằng ast (gồm import cục bộ trong hàm) của MỌI module trong backend/. Ngoại lệ có lý do liệt kê ở EXCEPTIONS.
Chế độ BÁO CÁO (mặc định): in vi phạm; NORA_LAYERING_STRICT=1 -> fail nếu còn vi phạm hoặc có module chưa ánh xạ.
nautilus_trader chỉ được import trong backend/nautilus/ (test_only_nautilus_package_imports_engine)."""
import ast
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

NORA = Path(__file__).resolve().parents[1]
BACKEND = NORA / "backend"
REPORT = NORA / "docs" / "bmad" / "p9_layering_report.md"

STRICT = os.environ.get("NORA_LAYERING_STRICT", "0") not in ("", "0", "false", "False")
WRITE = os.environ.get("NORA_LAYERING_WRITE", "0") not in ("", "0", "false", "False")   # chỉ ghi báo cáo khi đặt NORA_LAYERING_WRITE=1

# Cây backend đích (P17 T1-B5): routes -> jobs -> {wfa, nautilus, metrics, carlo} -> {alpha, signal} -> models; data và strategies đứng cạnh.
#   models (đáy)  <-  signal, alpha (cùng hạng: plan <-> nodes/compute)  <-  data  <-  metrics, carlo  <-  wfa, nautilus  <-  strategies  <-  jobs  <-  routes  <-  main
ALLOWED: Dict[str, set] = {
    "models": {"models"},
    "signal": {"models", "signal", "alpha"},
    "alpha": {"models", "signal", "alpha"},
    "data": {"models", "data"},
    "carlo": {"models", "carlo"},                                      # không import nautilus / signal
    "metrics": {"models", "data", "alpha", "signal", "carlo", "metrics"},   # không import nautilus (regime lấy nến qua signal.compute + data.data)
    "wfa": {"models", "alpha", "signal", "metrics", "carlo", "wfa"},
    "nautilus": {"models", "data", "alpha", "signal", "metrics", "nautilus"},
    "strategies": {"models", "data", "alpha", "signal", "metrics", "carlo", "nautilus", "strategies"},
    "jobs": {"models", "data", "alpha", "signal", "metrics", "carlo", "wfa", "nautilus", "strategies", "jobs"},
    "meta": {"models", "data", "alpha", "signal", "metrics", "carlo", "nautilus", "strategies", "jobs", "routes"},   # models/meta.py: lắp ráp metadata từ mọi nguồn (lười)
    "users": {"models", "users"},
    "routes": {"models", "data", "alpha", "signal", "metrics", "carlo", "wfa", "nautilus", "strategies", "jobs", "routes", "meta", "users"},
    "main": {"models", "data", "alpha", "signal", "metrics", "carlo", "wfa", "nautilus", "strategies", "jobs", "routes", "meta", "main", "users"},
}
# Ngoại lệ có ghi lý do: (module nguồn, module đích) được phép dù ngược chiều.
EXCEPTIONS = {
    ("data/data", "jobs/evaluate"),        # nguồn dữ liệu mặc định nối kho mmap dùng chung của job (đảo phụ thuộc qua DataSource, import lười + ImportError)
    ("data/data", "nautilus/catalog"),     # EngineData.instrument_spec: spec công cụ từ ParquetDataCatalog của Nautilus (import lười)
    ("alpha/strategies", "jobs/runner"),   # save_user_alpha đọc job đã xong từ runner (import lười)
    ("alpha/store", "jobs/runner"),        # save_user_alpha đọc job đã xong từ runner (import lười)
    ("data/crawl", "nautilus/catalog"),    # ghi catalog Nautilus khi crawl nến
}
# Ngoại lệ theo tầng: (tầng nguồn, module đích). metrics lấy thống kê hiệu suất từ nautilus/stats (bộ chuyển PortfolioAnalyzer -> khoá UI) — chỗ DUY NHẤT metrics chạm nautilus.
LAYER_EXCEPTIONS = {("metrics", "nautilus/stats")}
EXEMPT_LAYERS = {"script"}      # không ràng buộc (script vận hành / nghiên cứu)

LAYER_RULES: List[Tuple[str, str, Optional[int]]] = [
    ("models", "models", None),
    ("models/meta", "meta", None),
    ("signal", "signal", None),
    ("alpha/strategies", "strategies", None),
    ("alpha/store", "strategies", None),
    ("alpha", "alpha", None),
    ("data", "data", None),
    ("metrics", "metrics", None),
    ("carlo", "carlo", None),
    ("wfa", "wfa", None),
    ("nautilus", "nautilus", None),
    ("jobs", "jobs", None),
    ("users", "users", None),
    ("routes", "routes", None),
    ("main", "main", None),
]
_RULES_SORTED = sorted(LAYER_RULES, key=lambda r: -len(r[0]))
CORE_ORDER: List[str] = []


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
        k = _modname(p)
        if k in out and _is_shim(p):   # P9.4: core/backtest.py + stub core/backtest/__init__.py cùng tên module -> lấy file thật, không lấy stub
            continue
        out[k] = p
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
                if a.name != "*" and cand in modules:   # from backend.models import storage  -> module con
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
            if t_layer not in ALLOWED[layer] and (mod, tgt) not in EXCEPTIONS and (layer, tgt) not in LAYER_EXCEPTIONS:
                violations.append({"rule": f"{layer} -> {t_layer}", "from": mod, "to": tgt, "line": line})
    return {"modules": len(modules), "violations": violations, "unmapped": unmapped, "shims": shims, "edges": edges}


def render(res: dict) -> str:
    by_rule: Dict[str, List[dict]] = defaultdict(list)
    for v in res["violations"]:
        by_rule[v["rule"]].append(v)
    L = [
        "# P9 — báo cáo luật phụ thuộc (tự sinh bởi nora/test/test_layering.py, chế độ BÁO CÁO)",
        "",
        "Không sửa tay. Sinh lại: `NORA_LAYERING_WRITE=1 PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- -m pytest -q test/test_layering.py`.",
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
    assert res["modules"] > 40, "không đọc được backend/ (đường dẫn sai?)"
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
    assert layer_of("data/crawl") == ("data", None)
    assert layer_of("routes/book") == ("routes", None)
    assert layer_of("signal/compute") == ("signal", None)
    assert layer_of("alpha/plan") == ("alpha", None)
    assert layer_of("models/meta") == ("meta", None)
    assert layer_of("models/params") == ("models", None)
    assert layer_of("jobs/tasks") == ("jobs", None)
    assert layer_of("alpha/strategies") == ("strategies", None)
    assert layer_of("nautilus/engine") == ("nautilus", None)


def test_only_nautilus_package_imports_engine():
    """nautilus_trader (và chuỗi tên của nó) chỉ xuất hiện trong backend/nautilus/."""
    bad = [str(p.relative_to(NORA)) for p in BACKEND.rglob("*.py") if "__pycache__" not in p.parts and "nautilus" != p.relative_to(BACKEND).parts[0]
           and "nautilus_trader" in p.read_text(encoding="utf-8")]
    assert not bad, bad


def test_layering_strict_now():
    """Sau B5 cây đích sạch: không vi phạm, không module chưa ánh xạ."""
    res = collect()
    assert not res["unmapped"], res["unmapped"]
    assert not res["violations"], [f"{v['from']}:{v['line']} -> {v['to']}" for v in res["violations"]]
