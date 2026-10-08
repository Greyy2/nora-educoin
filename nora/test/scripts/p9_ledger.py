"""P9 ledger: chứng minh không mất logic khi gộp/chuyển file trong nora/backend (ADR-P9 §3). Chỉ đọc, chỉ AST (không import backend).

Baseline = commit f5cd58e (trước P9); hiện tại = working tree. Với mỗi symbol cấp module của mọi .py baseline dưới nora/backend, tìm nơi nó nằm
bây giờ (file backend KHÔNG phải shim + nora/test/) rồi so AST chuẩn hoá: IDENTICAL / CHANGED / MISSING / AMBIGUOUS.

  ops/run_limited.sh --no-lock -- test/scripts/p9_ledger.py [--folder core/backtest] [--diff] [--json out.json] [--hide-identical]

Gợi ý nơi chốn (hint) theo thứ tự: đích của shim (import backend.* + dict đổi tên + `x = _t.y`), bảng ánh xạ §3 của ADR, chính file cũ nếu chưa là shim.
Luôn thoát mã 0; dòng cuối: MISSING=<n> CHANGED=<n> IDENTICAL=<n>.
"""
from __future__ import annotations

import argparse
import ast
import copy
import difflib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASELINE = "f5cd58e"
NORA = Path(__file__).resolve().parents[2]          # .../nora
BACKEND = NORA / "backend"
TESTDIR = NORA / "test"
ADR = NORA / "docs/bmad/adr-p9-backend-layout.md"

# Đổi tên thủ công: "<đường cũ không .py, tính từ backend>.<tên cũ>" -> tên mới (khi shim không khai báo).
RENAMES: dict[str, str] = {
    "core/analytics/signal_explain._num": "_sx_num",
    "core/analytics/top_agents._FROZEN_PATH": "_frozen_path",          # hằng số -> hàm (registry.py)
    "optimize/book.DEFAULTS": "BOOK_BUILD_DEFAULTS",
    "optimize/book.run_job": "run_book_build",
    "optimize/store._SCHEMA": "_RESULTS_SCHEMA",             # P9.10a: shim (renames) đã xoá -> khai báo ở đây
    "optimize/store._dumps": "_results_dumps",
    "optimize/revalidate.wfa": "wfa_check",
    "optimize/funnel/storage._SCHEMA": "_RUN_SCHEMA",
    "optimize/funnel/storage._dumps": "_run_dumps",
    "core/strategy/book._int": "schema_int",
    "core/strategy/book._flt": "schema_flt",
    "core/strategy/book._choice": "schema_choice",
    "core/strategy/book._exit_risk_schema": "exit_risk_schema",
    "core/strategy/library.p": "tree_p",                                  # P9.9: trùng p() của DSL trong core/signal.py
    "core/backtest/kernel.pack_trackers": "pack_slots",                  # P9.4b: tracker -> slot arrays
    "live/bot.state_key": "live_state_key",                              # P9.10c: crawl/store.py (MỘT định nghĩa)
    "live/bot.evaluate": "evaluate_signals",                             # P9.10c: core/backtest.py
    "live/signals.evaluate": "evaluate_signals",
    # Dọn dẹp "một định nghĩa cho một logic": bản trùng đã gộp vào định nghĩa duy nhất bên phải
    "api/routers/funnel._Lru": "LruCache",
    "core/analytics/dashboard._date": "iso_date",
    "wfa/walk_forward._date": "iso_date",
    "core/analytics/user_alphas._write_json": "atomic_write_json",
    "core/backtest/edu_precompute._atomic_write": "atomic_write_json",
    "core/backtest/edu_precompute._json_default": "json_default",
    "optimize/funnel/promote._atomic_dump": "atomic_write_json",
    "core/backtest/engine.BASE_COLS": "DATA_COLUMNS",
    "core/regime/classifier.MINUTE": "MINUTE_MS",
    "core/regime/report.MINUTE": "MINUTE_MS",
    "core/signals/snapshot.MINUTE": "MINUTE_MS",
    "core/strategy/book._REGIME_NAMES": "REGIME_NAMES",
    "core/strategy/pydsl/program.TF_MS": "FRAME_MS",
    "optimize/funnel/gates.INITIAL_CAPITAL": "DEFAULT_CAPITAL",
    "optimize/funnel/stats.DIST_KEYS": "FLAT_KEYS",
}

# P9.10a: shim đã xoá -> bảng nhà mới của module cũ (thay cho việc đọc shim) + đổi tên khi gộp. Sinh từ các shim trước khi xoá.
OLD_HOME: dict[str, list[str]] = {
    "core/strategy/book": ["core/params.py", "optimize/book/build.py", "alpha/compile.py"],
    "core/strategy/library": ["core/params.py", "optimize/book/build.py", "alpha/compile.py"],
    "live/bot": ["live/live.py", "core/backtest.py", "crawl/store.py"],    # P9.10c: live/ chia theo môi trường — bot/okx/state_migrate -> live/live.py; evaluate/_portfolio/_engine -> core/backtest.py; state_key -> crawl/store.py
    "live/okx": ["live/live.py"],
    "live/state_migrate": ["live/live.py"],
    "live/paper": ["core/backtest.py"],                                   # PaperBook / KernelPaperBook / _SlotRO
    "live/signals": ["core/backtest.py"],
    "live/unified": ["live/live.py"],
    "live/okx_venue": ["live/live.py"],
    "live/exchange": ["live/live.py"],
    "live/secrets": ["live/live.py"],
    "live/compare": ["metrics/trades.py"],
    "api/jobs/batch": ["optimize/process/process.py", "routes/process.py"],   # P11: routes gộp còn 5 file (alpha, optimize, data, live, process)
    "api/jobs/runner": ["optimize/process/process.py"],
    "api/modes": ["routes/process.py"],
    "api/routers/alphas": ["routes/alpha.py"],
    "api/routers/book": ["routes/optimize.py", "optimize/book/build.py"],
    "api/routers/chart": ["routes/alpha.py"],
    "api/routers/custom": ["routes/alpha.py"],
    "api/routers/data": ["routes/data.py"],
    "api/routers/education": ["routes/alpha.py"],
    "api/routers/funnel": ["routes/optimize.py"],
    "api/routers/live": ["routes/live.py"],
    "api/routers/market": ["routes/data.py"],
    "api/routers/portfolio": ["routes/optimize.py"],
    "api/routers/strategies": ["routes/alpha.py"],
    "carlo/monte_carlo": ["carlo/carlo.py"],
    "core/analytics/dashboard": ["metrics/charts.py"],
    "core/analytics/feeds": ["metrics/charts.py"],
    "core/analytics/insights": ["metrics/charts.py"],
    "core/analytics/signal_explain": ["metrics/charts.py"],
    "core/analytics/strategy_doc": ["optimize/book/registry.py"],
    "core/analytics/top_agents": ["optimize/book/registry.py"],
    "core/analytics/user_alphas": ["optimize/book/registry.py"],
    "core/backtest/custom_run": ["optimize/process/tasks.py", "metrics/trades.py", "crawl/store.py", "core/params.py"],   # P11: tính toán thuần -> metrics/trades.py; nạp dữ liệu/mặc định -> crawl/store.py
    "core/backtest/edu_precompute": ["optimize/process/tasks.py", "metrics/trades.py", "crawl/store.py"],
    "core/backtest/run": ["optimize/search/evaluate.py", "optimize/process/tasks.py", "core/params.py"],
    "core/backtest/run_defaults": ["optimize/process/tasks.py", "crawl/store.py"],
    "core/backtest/tick_run": ["optimize/search/evaluate.py"],
    "core/data/crawler": ["crawl/cex.py"],
    "core/data/loader": ["crawl/store.py"],
    "core/data/okx_crawler": ["crawl/cex.py"],
    "core/data/promote": ["crawl/store.py"],
    "core/data/quality_gate": ["crawl/store.py"],
    "core/data/resampler": ["crawl/store.py"],
    "core/data/shared": ["crawl/store.py"],
    "core/data/tick_crawler": ["crawl/dex.py"],
    "core/metrics/diagnose": ["metrics/trades.py"],
    "core/metrics/diagnose_inputs": ["metrics/trades.py", "crawl/store.py"],
    "core/metrics/portfolio": ["metrics/metrics.py"],
    "core/metrics/returns": ["metrics/metrics.py"],
    "core/metrics/series_stages": ["metrics/charts.py"],
    "core/metrics/trades": ["metrics/trades.py"],
    "core/params/modes": ["routes/process.py", "optimize/book/build.py"],
    "core/params/presets": ["optimize/book/build.py"],
    "core/regime/classifier": ["regime/regime.py"],
    "core/regime/learn": ["regime/regime.py"],
    "core/regime/report": ["optimize/process/tasks.py", "optimize/search/evaluate.py", "metrics/trades.py", "core/params.py"],
    "core/signals/diagnostics": ["core/signal.py"],
    "core/signals/evaluator": ["core/signal.py"],
    "core/signals/kernels": ["core/indicator.py"],
    "core/signals/snapshot": ["core/signal.py", "optimize/book/build.py"],
    "core/strategy/pydsl": ["core/signal.py", "alpha/compile.py"],
    "core/strategy/pydsl/errors": ["core/signal.py", "alpha/contract.py"],
    "core/strategy/pydsl/explain": ["alpha/compile.py"],
    "core/strategy/pydsl/features": ["core/indicator.py"],
    "core/strategy/pydsl/ops": ["core/indicator.py"],
    "core/strategy/pydsl/parser": ["alpha/compile.py", "alpha/contract.py", "core/signal.py"],
    "core/strategy/pydsl/profiles": ["core/params.py", "core/backtest.py"],
    "core/strategy/pydsl/program": ["core/signal.py", "alpha/compile.py"],
    "core/strategy/pydsl/spec": ["core/indicator.py"],
    "db/data_layout": ["crawl/store.py"],
    "db/local_pkl": ["crawl/store.py"],
    "db/tick_storage": ["crawl/dex.py"],
    "optimize/book": ["optimize/book/build.py"],
    "optimize/funnel/antiluck": ["carlo/carlo.py", "wfa/wfa.py"],
    "optimize/funnel/estimate": ["optimize/funnel/stages.py"],
    "optimize/funnel/evaluate": ["optimize/search/evaluate.py"],
    "optimize/funnel/gates": ["optimize/funnel/stages.py", "core/params.py"],   # iso_date / date_ms: MỘT định nghĩa ở core/params.py
    "optimize/funnel/generate": ["optimize/search/generate.py"],
    "optimize/funnel/orchestrator": ["optimize/funnel/stages.py"],
    "optimize/funnel/promote": ["optimize/funnel/stages.py", "optimize/book/registry.py"],
    "optimize/funnel/publish": ["optimize/funnel/stages.py", "optimize/book/registry.py", "optimize/process/tasks.py"],   # P11: build_report/book_source -> registry; run_job->run_funnel_book -> tasks
    "optimize/funnel/recompute": ["optimize/funnel/stages.py"],
    "optimize/funnel/run": ["optimize/funnel/stages.py"],
    "optimize/funnel/sizing": ["optimize/funnel/stages.py"],
    "optimize/funnel/stats": ["optimize/funnel/stages.py"],
    "optimize/registry": ["optimize/book/registry.py"],
    "optimize/revalidate": ["optimize/book/registry.py"],
    "optimize/shared": ["optimize/search/evaluate.py"],
    "optimize/store": ["optimize/funnel/storage.py"],
    "utils/engine_version": ["optimize/book/registry.py"],
    "utils/jobs": ["optimize/process/process.py"],
    "utils/jsonsafe": ["crawl/store.py"],
    "utils/lru": ["crawl/store.py"],
    "utils/memwatch": ["optimize/process/workers.py"],
    "utils/parallel": ["optimize/process/workers.py"],
    "wfa/run": ["optimize/process/tasks.py", "optimize/search/evaluate.py", "core/params.py"],
    "wfa/walk_forward": ["wfa/wfa.py", "optimize/search/evaluate.py", "core/params.py"],   # P11: phần chạy engine (run_portfolio_wfa, plan_*, _pool_shared, run_job->run_wfa_job) ở search/evaluate.py; _date -> iso_date (core/params.py)
}
OLD_HOME.update({   # P9.10b: ba _read_json cũ -> MỘT crawl/store.read_json (thêm vào gợi ý, không thay gợi ý ADR)
    "core/backtest/dex": ["crawl/store.py"],          # engine-API pass: is_dex_symbol/classify_symbols/require_perp đọc đĩa -> crawl/store.py
    "core/data/shared": ["optimize/search/evaluate.py"],                  # engine-API pass: kho mmap dùng chung (crawl/store.py -> cạnh SharedExporter)
    "core/backtest/portfolio": ["core/backtest.py", "crawl/store.py", "optimize/search/evaluate.py"],
    "core/params/builder": ["core/params.py", "crawl/store.py", "optimize/search/evaluate.py"],
    "core/signals/snapshot": ["core/backtest.py", "core/signal.py", "optimize/book/build.py"],   # signal_snapshot cần PortfolioEngine -> core/backtest.py
    "core/signals/diagnostics": ["core/backtest.py", "core/signal.py"],   # check_signals cần BacktestEngine -> core/backtest.py
    "core/regime/classifier": ["core/signal.py", "regime/regime.py"],
    "core/params/presets": ["crawl/store.py"],
    "optimize/funnel/estimate": ["crawl/store.py"],
})
RENAMES.update({
    "core/params/builder.venue_of_symbol": "manifest_venue",          # engine-API pass: core không đọc manifest — nhận manifest từ DataSource
    "core/params/builder.pool_fee_rate": "manifest_pool_fee",
    "core/backtest/portfolio._DATA_CACHE": "ENGINE_DATA",             # engine-API pass: bộ đệm mảng = EngineData.memo (optimize/search/evaluate.py)
    "core/backtest/dex._read_json": "read_json",
    "core/params/presets._read_json": "read_json",
    "optimize/funnel/estimate._read_json": "read_json",
    "wfa/walk_forward.run_job": "run_wfa_job",                       # P9.10b: chuyển sang optimize/process/tasks.py, đổi tên (tránh va tên run_job của module job)
    "api/jobs/runner.run": "run_job_dir",
    "api/routers/book._METRIC_KEYS": "METRIC_KEYS",
    "core/analytics/top_agents._FROZEN_PATH": "_frozen_path",
    "core/backtest/custom_run.DEFAULTS": "CUSTOM_BACKTEST_DEFAULTS",
    "core/backtest/custom_run.run_job": "run_custom_backtest",
    "core/backtest/edu_precompute.DEFAULTS": "EDU_PRECOMPUTE_DEFAULTS",
    "core/backtest/edu_precompute.run_job": "run_edu_precompute",
    "core/backtest/run.DEFAULTS": "BOOK_BACKTEST_DEFAULTS",
    "core/backtest/run.run_job": "run_book_backtest",
    "core/data/okx_crawler.DEFAULT_CACHE_DIR": "OKX_DEFAULT_CACHE_DIR",
    "core/data/okx_crawler.crawl": "okx_crawl",
    "core/data/okx_crawler.crawl_funding": "okx_crawl_funding",
    "core/data/okx_crawler.run_job": "okx_run_job",
    "core/execute/amm.BISECT_MAX_ITER": "_AMM_BISECT",
    "core/execute/amm.amount_out": "amm_amount_out",
    "core/execute/amm.price_impact": "amm_price_impact",
    "core/params/presets.run_job": "run_presets_build",
    "core/regime/report.DEFAULTS": "REGIME_REPORT_DEFAULTS",
    "core/regime/report.run_job": "run_regime_report",
    "core/strategy/pydsl/features.evaluate": "evaluate_feature",
    "optimize/book.DEFAULTS": "BOOK_BUILD_DEFAULTS",
    "optimize/book.NORA_ROOT": "NORA_DIR",
    "optimize/book.run_job": "run_book_build",
    "optimize/funnel/evaluate.make_engine": "make_engine_from_dict",
    "optimize/funnel/publish.DEFAULTS": "FUNNEL_BOOK_DEFAULTS",
    "optimize/funnel/publish.run_job": "run_funnel_book",
    "optimize/funnel/recompute.run_job": "run_funnel_recompute",
    "optimize/funnel/run.DEFAULTS": "FUNNEL_RUN_DEFAULTS",
    "optimize/funnel/run.run_job": "run_funnel_run",
    "optimize/revalidate.DEFAULTS": "ALPHA_REVALIDATE_DEFAULTS",
    "optimize/revalidate.run_job": "run_alpha_revalidate",
    "optimize/revalidate.wfa": "wfa_check",
    "optimize/store._SCHEMA": "_RESULTS_SCHEMA",
    "optimize/store._dumps": "_results_dumps",
    "wfa/run.DEFAULTS": "BOOK_WFA_DEFAULTS",
    "wfa/run.run_job": "run_book_wfa",
    # P11: routes gộp còn 5 file -> tên handler có tiền tố miền (tránh va tên trong cùng file)
    "api/routers/alphas.get_catalog": "get_alpha_catalog",
    "api/routers/strategies.get_catalog": "get_strategy_catalog",
    "api/routers/strategies.ExplainRequest": "StrategyExplainRequest",
    "api/routers/strategies.post_explain": "post_strategy_explain",
    "api/routers/chart.ExplainRequest": "ChartExplainRequest",
    "api/routers/chart.post_explain": "post_chart_explain",
    "api/routers/book.get_alphas": "get_book_alphas",
    "api/routers/funnel.get_alphas": "get_funnel_alphas",
    "api/routers/funnel.get_trades": "get_funnel_trades",
    "api/routers/portfolio.get_trades": "get_portfolio_trades",
    "core/strategy/pydsl/features._clean": "nan_nonfinite",          # core/indicator.py (thân giống hệt, chỉ thêm docstring)
    "core/backtest/custom_run._ts": "date_ms",                         # core/params.py (MỘT định nghĩa)
    "core/backtest/run._ts": "date_ms",
    "core/regime/report._ts": "date_ms",
    "wfa/run._ts": "date_ms",
    "crawl/store.fetch_local_candles_df": "fetch_candles_df",          # bí danh cũ đã xoá: gọi thẳng tên thật
    "crawl/store.has_local_frame": "has_frame",
    "crawl/store.DATA_HOME": "DATA_DIR",                               # P11: MỘT định nghĩa ở core/models.py (crawl/store dùng thẳng DATA_DIR)
})
OLD_HOME.update({
    "crawl/store": ["core/models.py"],
})

SHIM_MARK = "P9-SHIM"


# ---------------------------------------------------------------------------------------------- git / fs
def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=NORA, capture_output=True, text=True, check=True)
    return r.stdout


def repo_prefix() -> str:
    return git("rev-parse", "--show-prefix").strip()          # vd. "nora/"


def baseline_files() -> dict[str, str]:
    """{backend-relative path: source} của mọi .py dưới backend tại baseline."""
    pre = repo_prefix()
    names = git("ls-tree", "-r", "--name-only", BASELINE, "--full-name", "--", "backend").splitlines()
    out = {}
    for n in names:
        if not n.endswith(".py") or "__pycache__" in n:
            continue
        rel = n[len(pre + "backend/"):]
        out[rel] = git("show", f"{BASELINE}:{n}")
    return out


def is_shim(src: str) -> bool:
    return SHIM_MARK in "\n".join(src.splitlines()[:3])


# ---------------------------------------------------------------------------------------------- symbols
def _target_names(t: ast.AST) -> list[str]:
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, (ast.Tuple, ast.List)):
        return [n for e in t.elts for n in _target_names(e)]
    if isinstance(t, ast.Starred):
        return _target_names(t.value)
    return []


def _is_main_guard(n: ast.If) -> bool:
    return "__name__" in ast.dump(n.test) and "__main__" in ast.dump(n.test)


def top_symbols(tree: ast.Module) -> dict[str, ast.AST]:
    """name -> statement node (def/class/assign) cấp module (đệ quy vào if/try/with không phải main-guard); bỏ import, __all__, docstring."""
    out: dict[str, ast.AST] = {}

    def walk(body):
        for st in body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out[st.name] = st
            elif isinstance(st, ast.Assign):
                for t in st.targets:
                    for n in _target_names(t):
                        if n != "__all__":
                            out[n] = st
            elif isinstance(st, ast.AnnAssign):
                for n in _target_names(st.target):
                    if n != "__all__":
                        out[n] = st
            elif isinstance(st, ast.If):
                if not _is_main_guard(st):
                    walk(st.body)
                    walk(st.orelse)
            elif isinstance(st, ast.Try):
                walk(st.body)
                for h in st.handlers:
                    walk(h.body)
                walk(st.orelse)
                walk(st.finalbody)
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                walk(st.body)

    walk(tree.body)
    return out


def norm_dump(node: ast.AST) -> str:
    """AST chuẩn hoá: bỏ vị trí; tên def/class và vế trái phép gán không tính (đổi tên khi gộp); docstring giữ."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        n = copy.copy(node)
        n.name = "_"
        return ast.dump(n)
    if isinstance(node, ast.Assign):
        return "Assign:" + ast.dump(node.value)
    if isinstance(node, ast.AnnAssign):
        return "AnnAssign:" + ast.dump(node.annotation) + "|" + (ast.dump(node.value) if node.value is not None else "None")
    return ast.dump(node)


def unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception as e:                                   # pragma: no cover
        return f"<unparse error {e}>"


# ---------------------------------------------------------------------------------------------- current tree index
class FileInfo:
    def __init__(self, rel: str, path: Path, src: str):
        self.rel = rel                       # "core/backtest.py" hoặc "test/scripts/x.py"
        self.path = path
        self.src = src
        self.shim = is_shim(src)
        self.tree = None
        self.syms: dict[str, ast.AST] = {}
        try:
            self.tree = ast.parse(src)
            if not self.shim:
                self.syms = top_symbols(self.tree)
        except SyntaxError as e:
            print(f"[warn] không parse được {rel}: {e}", file=sys.stderr)


def load_current() -> dict[str, FileInfo]:
    files: dict[str, FileInfo] = {}
    for p in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(BACKEND).as_posix()
        files[rel] = FileInfo(rel, p, p.read_text(encoding="utf-8", errors="replace"))
    for p in sorted(TESTDIR.rglob("*.py")):
        if "__pycache__" in p.parts or "data_legacy" in p.parts:
            continue
        rel = "test/" + p.relative_to(TESTDIR).as_posix()
        files[rel] = FileInfo(rel, p, p.read_text(encoding="utf-8", errors="replace"))
    return files


def module_to_files(mod: str, cur: dict[str, FileInfo]) -> list[str]:
    """'backend.crawl.cex' -> ['crawl/cex.py']; nếu X.py và X/__init__.py cùng tồn tại ưu tiên file không phải shim."""
    if not mod.startswith("backend"):
        return []
    parts = mod.split(".")[1:]
    if not parts:
        return []
    base = "/".join(parts)
    out = []
    for cand in (base + ".py", base + "/__init__.py"):
        if cand in cur:
            out.append(cand)
    return out


def shim_info(fi: FileInfo, cur: dict[str, FileInfo]):
    """(hint_files theo thứ tự, renames dict) của một file shim."""
    hints: list[str] = []
    renames: dict[str, str] = {}
    if fi.tree is None:
        return hints, renames
    for node in ast.walk(fi.tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend") and node.level == 0:
            for a in node.names:
                sub = module_to_files(f"{node.module}.{a.name}", cur)
                found = sub or module_to_files(node.module, cur)
                for f in found:
                    if f not in hints:
                        hints.append(f)
        elif isinstance(node, ast.Dict) and node.keys and all(
            isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Constant) and isinstance(v.value, str)
            for k, v in zip(node.keys, node.values)
        ):
            for k, v in zip(node.keys, node.values):
                renames[k.value] = v.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) and node.value.value.id.startswith("_t"):
            renames[node.targets[0].id] = node.value.attr
    # stub gói X/__init__.py nạp X.py
    if fi.rel.endswith("/__init__.py"):
        sib = fi.rel[: -len("/__init__.py")] + ".py"
        if sib in cur and sib not in hints:
            hints.append(sib)
    return hints, renames


def resolve_hints(rel: str, cur: dict[str, FileInfo], seen=None):
    """Đi theo chuỗi shim -> các file thật. Trả (files, renames hợp nhất)."""
    seen = seen or set()
    if rel in seen or rel not in cur:
        return [], {}
    seen.add(rel)
    fi = cur[rel]
    if not fi.shim:
        return [rel], {}
    direct, rn = shim_info(fi, cur)
    files: list[str] = []
    ren = dict(rn)
    for d in direct:
        fs, r2 = resolve_hints(d, cur, seen)
        for f in fs:
            if f not in files:
                files.append(f)
        for k, v in r2.items():
            ren.setdefault(k, v)
    return files, ren


# ---------------------------------------------------------------------------------------------- ADR map
def brace_expand(piece: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", piece)
    if not m:
        return [piece]
    out = []
    for alt in m.group(1).split(","):
        out += brace_expand(piece[: m.start()] + alt.strip() + piece[m.end():])
    return out


def split_outside_braces(s: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def adr_map() -> list[tuple[str, str]]:
    """[(dest .py file, source prefix)] từ bảng §3 (nguồn là đường backend-relative không .py, có thể là thư mục)."""
    out: list[tuple[str, str]] = []
    if not ADR.exists():
        return out
    sec = False
    for line in ADR.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 3."):
            sec = True
            continue
        if sec and line.startswith("## "):
            break
        if not (sec and line.startswith("|")):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        dest = cells[0].replace("`", "").split(" ")[0]
        if not dest.endswith(".py") or "*" in dest:
            continue
        for piece in split_outside_braces(cells[1]):
            tok = piece.strip().replace("`", "").split(" ")[0].rstrip(",;—")
            tok = re.sub(r"\s+.*$", "", tok)
            if not tok or "*" in tok:
                continue
            for src in brace_expand(tok):
                src = src.removesuffix(".py")
                if re.match(r"^[A-Za-z_][\w/]*$", src) and "/" in src:
                    out.append((dest, src))
    return out


def adr_hints_for(old_rel: str, amap) -> list[str]:
    stem = old_rel.removesuffix(".py")
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    hits = []
    for dest, src in amap:
        if stem == src or stem.startswith(src + "/"):
            if dest not in hits:
                hits.append(dest)
    return hits


# ---------------------------------------------------------------------------------------------- ledger
class Row:
    __slots__ = ("old_file", "sym", "new_file", "new_sym", "status", "note", "old_node", "new_node")

    def __init__(self, old_file, sym):
        self.old_file, self.sym = old_file, sym
        self.new_file = self.new_sym = None
        self.status = "MISSING"
        self.note = ""
        self.old_node = self.new_node = None

    def to_json(self):
        return {"old_file": self.old_file, "symbol": self.sym, "new_file": self.new_file, "new_symbol": self.new_sym,
                "status": self.status, "note": self.note}


def build_ledger(cur: dict[str, FileInfo], base: dict[str, str]) -> tuple[list[Row], set[tuple[str, str]], set[str]]:
    amap = adr_map()
    # chỉ mục tên -> [(file, node)] trên mọi file không phải shim
    index: dict[str, list[tuple[str, ast.AST]]] = defaultdict(list)
    for rel, fi in cur.items():
        for name, node in fi.syms.items():
            index[name].append((rel, node))
    rows: list[Row] = []
    dests: set[tuple[str, str]] = set()
    base_names: set[str] = set()
    for old_rel in sorted(base):
        try:
            tree = ast.parse(base[old_rel])
        except SyntaxError as e:
            print(f"[warn] baseline {old_rel}: {e}", file=sys.stderr)
            continue
        if is_shim(base[old_rel]):
            continue
        syms = top_symbols(tree)
        hint_files, shim_ren = resolve_hints(old_rel, cur) if old_rel in cur else ([], {})
        for h in OLD_HOME.get(old_rel.removesuffix(".py"), []):
            if h in cur and h not in hint_files:
                hint_files.append(h)
        for h in adr_hints_for(old_rel, amap):
            if h in cur and h not in hint_files:
                hint_files.append(h)
        for sym, onode in syms.items():
            base_names.add(sym)
            row = Row(old_rel, sym)
            row.old_node = onode
            names = []
            manual = RENAMES.get(f"{old_rel.removesuffix('.py')}.{sym}")
            for n in (manual, shim_ren.get(sym), sym):
                if n and n not in names:
                    names.append(n)
            odump = norm_dump(onode)
            # ứng viên: (file, tên, node) theo thứ tự ưu tiên: hint trước, rồi mọi file khác
            cands: list[tuple[str, str, ast.AST, bool]] = []
            for hf in hint_files:
                for n in names:
                    if n in cur[hf].syms:
                        cands.append((hf, n, cur[hf].syms[n], True))
            seen_c = {(c[0], c[1]) for c in cands}
            for n in names:
                for f, node in index.get(n, []):
                    if (f, n) not in seen_c:
                        cands.append((f, n, node, False))
                        seen_c.add((f, n))
            chosen = None
            for c in cands:                                   # IDENTICAL ưu tiên (hint trước)
                if norm_dump(c[2]) == odump:
                    chosen = c
                    row.status = "IDENTICAL"
                    break
            if chosen is None:
                in_hint = [c for c in cands if c[3]]
                if in_hint:
                    chosen = in_hint[0]
                    row.status = "CHANGED"
                elif len(cands) == 1:
                    chosen = cands[0]
                    row.status = "CHANGED"
                    row.note = "not-in-hint"
                elif len(cands) > 1:
                    row.status = "AMBIGUOUS"
                    row.note = "candidates: " + ", ".join(f"{c[0]}:{c[1]}" for c in cands[:6])
            if chosen:
                row.new_file, row.new_sym, row.new_node = chosen[0], chosen[1], chosen[2]
                dests.add((chosen[0], chosen[1]))
            rows.append(row)
    return rows, dests, base_names


def folder_of(old_file: str) -> str:
    return old_file.rsplit("/", 1)[0] if "/" in old_file else "."


# ---------------------------------------------------------------------------------------------- main
def find_dups(cur: dict[str, FileInfo], threshold: float = 0.8, folder: str = "") -> list[tuple[str, str, str, str, float]]:
    """Quy tắc "một định nghĩa cho một logic": cặp (file A, file B, tên, loại, độ giống) — cùng tên cấp module ở hai file backend KHÔNG-shim mà AST chuẩn hoá giống hệt
    (IDENTICAL) hoặc ast.unparse giống > threshold (SIMILAR). Chỉ xét def/class và gán có thân dài (>= 3 dòng), bỏ import/hằng ngắn. `folder` lọc theo tiền tố đường file (một trong hai)."""
    by_name: dict[str, list[tuple[str, ast.AST]]] = defaultdict(list)
    for rel, fi in cur.items():
        if rel.startswith("test/") or fi.shim:
            continue
        for name, node in fi.syms.items():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and (node.end_lineno - node.lineno) >= 2:
                by_name[name].append((rel, node))
    out = []
    for name, items in by_name.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ra, na), (rb, nb) = items[i], items[j]
                if folder and not (ra.startswith(folder) or rb.startswith(folder)):
                    continue
                if norm_dump(na) == norm_dump(nb):
                    out.append((ra, rb, name, "IDENTICAL", 1.0))
                else:
                    r = difflib.SequenceMatcher(None, unparse(na), unparse(nb), autojunk=False).ratio()
                    if r > threshold:
                        out.append((ra, rb, name, "SIMILAR", r))
    # cùng thân AST khác tên (hàm >= 2 dòng): helper chép lại dưới tên khác
    by_body: dict[str, list[tuple[str, str, ast.AST]]] = defaultdict(list)
    for rel, fi in cur.items():
        if rel.startswith("test/") or fi.shim:
            continue
        for name, node in fi.syms.items():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (node.end_lineno - node.lineno) >= 1:
                by_body[norm_dump(node)].append((rel, name, node))
    for items in by_body.values():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ra, na, _), (rb, nb, _) = items[i], items[j]
                if ra != rb and na != nb and (not folder or ra.startswith(folder) or rb.startswith(folder)):
                    out.append((ra, rb, f"{na}={nb}", "IDENTICAL", 1.0))
    return sorted(out, key=lambda t: (t[0], t[2]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dups", nargs="?", const="", metavar="FOLDER", help="liệt kê định nghĩa trùng (cùng tên, AST giống hệt hoặc giống > 0.8) giữa các file backend không-shim; FOLDER lọc theo tiền tố file (vd. optimize/, routes/)")
    ap.add_argument("--folder", help="lọc theo tiền tố đường cũ (tính từ backend), vd. core/backtest, core/execute, api")
    ap.add_argument("--json", help="ghi kết quả JSON ra file")
    ap.add_argument("--diff", action="store_true", help="in unified diff (ast.unparse cũ vs mới) cho mục CHANGED")
    ap.add_argument("--hide-identical", action="store_true", help="không in dòng IDENTICAL")
    args = ap.parse_args(argv)

    if args.dups is not None:
        dups = find_dups(load_current(), folder=args.dups)
        for ra, rb, name, kind, r in dups:
            print(f"{kind:9s} {name}: {ra} <-> {rb} ({r:.2f})")
        print(f"DUPS={len(dups)}")
        return 0

    base = baseline_files()
    cur = load_current()
    rows, dests, base_names = build_ledger(cur, base)
    if args.folder:
        pre = args.folder.removeprefix("backend/")
        rows_f = [r for r in rows if r.old_file.startswith(pre)]
    else:
        rows_f = rows

    # NEW: symbol hiện có ở file backend không-shim, không là đích của symbol cũ nào và tên không có trong baseline
    new_syms: dict[str, list[str]] = defaultdict(list)
    for rel, fi in cur.items():
        if rel.startswith("test/") or fi.shim:
            continue
        for name in fi.syms:
            if (rel, name) not in dests and name not in base_names:
                new_syms[rel].append(name)

    print(f"# P9 ledger: baseline {BASELINE} vs working tree; old files={len({r.old_file for r in rows})} symbols={len(rows)}")
    cur_file = None
    for r in rows_f:
        if args.hide_identical and r.status == "IDENTICAL":
            continue
        dest = f"{r.new_file}:{r.new_sym}" if r.new_file else "-"
        note = f"  [{r.note}]" if r.note else ""
        print(f"{r.old_file}:{r.sym} -> {dest} {r.status}{note}")
        if args.diff and r.status == "CHANGED":
            a = unparse(r.old_node).splitlines()
            b = unparse(r.new_node).splitlines()
            d = list(difflib.unified_diff(a, b, f"old/{r.old_file}:{r.sym}", f"new/{r.new_file}:{r.new_sym}", lineterm="", n=2))
            for line in d:
                print("    " + line)
    print()
    print("# Counts per old folder (IDENTICAL / CHANGED / MISSING / AMBIGUOUS)")
    per = defaultdict(Counter)
    for r in rows_f:
        per[folder_of(r.old_file)][r.status] += 1
    for f in sorted(per):
        c = per[f]
        print(f"{f:34s} IDENTICAL={c['IDENTICAL']:<4d} CHANGED={c['CHANGED']:<4d} MISSING={c['MISSING']:<4d} AMBIGUOUS={c['AMBIGUOUS']:<3d} total={sum(c.values())}")
    print()
    n_new = sum(len(v) for v in new_syms.values())
    print(f"# NEW symbols (in current non-shim backend files, not in any baseline file): {n_new}")
    for rel in sorted(new_syms):
        print(f"{rel}: {', '.join(sorted(new_syms[rel]))}")
    print()

    tot = Counter(r.status for r in rows_f)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "baseline": BASELINE,
            "rows": [r.to_json() for r in rows_f],
            "per_folder": {f: dict(c) for f, c in per.items()},
            "new_symbols": {k: sorted(v) for k, v in new_syms.items()},
            "totals": dict(tot),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"MISSING={tot['MISSING']} CHANGED={tot['CHANGED']} IDENTICAL={tot['IDENTICAL']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
