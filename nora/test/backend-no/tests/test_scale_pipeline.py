# Đã chuyển khỏi test/ (P17 T1-B5c): kiểm tính năng nghiên cứu đã gỡ (funnel/revalidate/kho dựng sổ); bản gốc còn ở tag pre-p17-research.
"""Pipeline tối ưu quy mô lớn (tới ~1.000.000 cấu hình) mà KHÔNG đổi kết quả:
cổng dữ liệu bắt buộc, pool streaming có chặn, kho kết quả SQLite, lấy mẫu cấu hình lười, top-K, resume, ước lượng/trần, tiến độ/huỷ.

Dữ liệu giả lập 3 tài sản perp 70 ngày (fixture `market` của test_strategy_book; manifest synthetic=False).
"""
import pathlib

from backend.models.storage import alpha_run_dir, run_dir
import itertools
import json
import os
import random
import signal
import sqlite3
import subprocess
import sys
from subprocess import Popen as _RealPopen   # fixture `client` thay subprocess.Popen bằng bản giả
import time

import pytest

from backend.data import data as qg
from backend.optimize.funnel import storage as rs
from backend.jobs.runner import Progress
from backend.jobs._store import stream_stage
from backend.jobs import workers as parallel
from test_portfolio_wfa import DAY, START, T0, _load_script, _small_book, market  # noqa: F401  (market là fixture)

pytestmark = pytest.mark.usefixtures("synthetic_data")   # P15: engine Nautilus lấy nến thực thi + spec từ DataSource; dữ liệu giả lập -> conftest.synthetic_data


# ─── 12.1 cổng chất lượng dữ liệu bắt buộc ──────────────────────────────────
def _tamper(market, sym="AAA", **changes):
    """Ghi verdict BLOCKED giả vào manifest của <sym> (mô phỏng crawl.evaluate_data_quality chặn dữ liệu hỏng); changes["issue"] = lý do."""
    path = market / "market" / "okx" / "catalog" / "_manifest" / f"{sym}.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    m["quality"] = {"symbol": sym, "status": "BLOCKED", "quality_score": 0.0, "issues": [changes["issue"]], "metrics": {}}
    path.write_text(json.dumps(m), encoding="utf-8")
    qg._WARNED.clear()


BAD = {"synthetic": dict(issue="Chặn chạy: dữ liệu đánh dấu synthetic"), "digest": dict(issue="Chặn chạy: digest_1m không khớp")}


def test_require_data_ok_passes_clean_market_and_lists_issues_for_bad(market):
    ok = qg.require_data_ok(["AAA@perp", "BBB@perp"])
    assert set(ok) == {"AAA@perp", "BBB@perp"} and all(v["status"] in ("APPROVED", "WARNING") for v in ok.values())
    _tamper(market, "AAA", **BAD["synthetic"])
    _tamper(market, "BBB", **BAD["digest"])
    with pytest.raises(qg.DataQualityError) as e:
        qg.require_data_ok(["AAA@perp", "BBB@perp", "CCC@perp"])
    msg = str(e.value)
    assert "AAA@perp" in msg and "BBB@perp" in msg and "CCC@perp" not in msg      # liệt kê từng tài sản lỗi
    assert "BLOCKED" in msg and "synthetic" in msg and "digest_1m" in msg
    with pytest.raises(SystemExit) as se:                                         # bản cho CLI: SystemExit(thông điệp)
        qg.require_data_ok_or_exit(["AAA@perp"])
    assert "AAA@perp" in str(se.value)


def test_require_data_ok_needs_more_data_and_warning(market, monkeypatch, caplog):
    def fake(symbol, data_root=None):
        return {"symbol": symbol, "status": {"S1": "NEEDS_MORE_DATA", "S2": "WARNING"}[symbol], "issues": [f"vấn đề của {symbol}"]}
    monkeypatch.setattr(qg, "quality_verdict", fake)
    with pytest.raises(qg.DataQualityError, match="S1"):
        qg.require_data_ok(["S1", "S2"])
    with caplog.at_level("WARNING"):
        out = qg.require_data_ok(["S2"])                                            # WARNING được phép, có log
    assert out["S2"]["status"] == "WARNING" and "vấn đề của S2" in caplog.text


@pytest.mark.parametrize("kind", sorted(BAD))
def test_portfolio_engine_refuses_bad_data(market, monkeypatch, kind):
    from backend.nautilus.engine import PortfolioEngine
    from backend.analys.param import materialize
    sb = _small_book(monkeypatch)
    cands = sb.BY_ID
    st = materialize(cands["t_long"], {"sig.lo": 40, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720})
    _tamper(market, "BBB", **BAD[kind])
    eng = PortfolioEngine(sb.perp_symbols(), [st], T0, T0 + 30 * DAY, trade_start_ts=T0 + 3 * DAY, use_cache=False)
    with pytest.raises(qg.DataQualityError, match="BBB@perp"):
        eng.load_data()


@pytest.mark.parametrize("kind", sorted(BAD))
def test_every_entry_point_refuses_bad_data(market, monkeypatch, tmp_path, kind):
    _small_book(monkeypatch)
    _tamper(market, "CCC", **BAD[kind])
    common = {"workers": 1, "per_worker_mb": 300}
    bsb = _load_script("build_strategy_book")
    with pytest.raises(SystemExit, match="CCC@perp"):
        bsb.run_job({**common, "n": 2, "out": str(tmp_path / "alphas")})
    vb = _load_script("validate_book")
    with pytest.raises(SystemExit, match="CCC@perp"):
        vb.run_job({**common, "candidates": "t_long", "n": 1})
    rbb = _load_script("run_book_backtest")
    with pytest.raises(SystemExit, match="CCC@perp"):
        rbb.run_job({"strategies": [{"id": "t_long"}], "start": "2023-11-20", "end": "2023-11-25"})


# ─── 12.2 pool_imap_bounded ─────────────────────────────────────────────────
def _sq(x):
    return x * x


def _boom_on_five(x):
    if x == 5:
        raise ValueError("lỗi thật trong job")
    return x


def _killed_once(arg):
    x, flag = arg
    if x == 7 and not os.path.exists(flag):
        open(flag, "w").close()
        os._exit(1)                      # mô phỏng worker bị OOM-kill
    return x * 10


def _always_killed(arg):
    os._exit(1)


def test_pool_imap_bounded_yields_all_and_bounds_inflight():
    pulled = []

    def gen():
        for i in range(40):
            pulled.append(i)
            yield i
    got = {}
    for idx, res in parallel.pool_imap_bounded(_sq, gen(), 2, "t", max_inflight=4):
        got[idx] = res
        assert len(pulled) - len(got) <= 4 + 1          # không bao giờ nạp trước quá max_inflight job
    assert got == {i: i * i for i in range(40)}


def test_pool_imap_bounded_default_inflight_and_empty():
    assert list(parallel.pool_imap_bounded(_sq, iter([]), 3, "t")) == []
    assert sorted(parallel.pool_imap_bounded(_sq, iter(range(9)), 3, "t")) == [(i, i * i) for i in range(9)]


def test_pool_imap_bounded_surfaces_job_errors_without_retry(capsys):
    with pytest.raises(ValueError, match="lỗi thật"):
        list(parallel.pool_imap_bounded(_boom_on_five, iter(range(10)), 2, "t"))
    assert "[WARN]" not in capsys.readouterr().out


def test_pool_imap_bounded_reruns_unfinished_after_worker_kill(tmp_path, capsys):
    flag = str(tmp_path / "killed")
    out = dict(parallel.pool_imap_bounded(_killed_once, ((x, flag) for x in range(12)), 2, "t", max_inflight=4))
    assert out == {x: x * 10 for x in range(12)}        # giữ kết quả đã xong, chỉ chạy lại job chưa xong
    assert "[WARN]" in capsys.readouterr().out


def test_pool_imap_bounded_second_break_raises(capsys):
    with pytest.raises(RuntimeError, match="vẫn hỏng"):
        list(parallel.pool_imap_bounded(_always_killed, iter([(1,), (2,), (3,)]), 2, "t"))


def test_pool_map_safe_on_done_callback():
    seen = []
    res = parallel.pool_map_safe(_sq, list(range(6)), 2, "t", on_done=lambda i, r: seen.append((i, r)))
    assert res == [x * x for x in range(6)] and sorted(seen) == [(i, i * i) for i in range(6)]


# ─── 12.2 kho kết quả ───────────────────────────────────────────────────────
def test_results_store_put_is_idempotent_and_queries(tmp_path):
    st = rs.ResultsStore(str(tmp_path))
    k1 = rs.make_job_key("A", "c1", {"x": 1}, [0, 1], "level", {"r": 1}, ["fp"])
    assert st.put(k1, "A", "c1", {"x": 1}, {"ret": 5.0}, ord=0, score=2.0) is True
    assert st.put(k1, "A", "c1", {"x": 1}, {"ret": 99.0}, ord=0, score=9.0) is False     # idempotent: không ghi đè
    assert st.get(k1)["metrics"] == {"ret": 5.0} and st.has(k1) and st.count() == 1
    for i in range(1, 8):
        st.put(f"k{i}", "A", "c1", {"x": i + 1}, {"ret": float(i)}, ord=i, score=float(i % 3) if i != 4 else None)
    st.put("other", "B", "c2", {}, {}, ord=0)
    assert st.count("A", "c1") == 8 and st.count("B") == 1 and st.count(stage="A") == 8
    assert set(st.done_keys("A", "c1")) == {k1} | {f"k{i}" for i in range(1, 8)}
    # top_k theo cột score: giảm dần, hoà theo ord, NULL (-inf) cuối
    top = st.top_k("A", "c1", 4)
    assert [r["ord"] for r in top] == [0, 2, 5, 1]    # score 2.0(ord0), 2(ord2), 2(ord5), 1(ord1)... xem dưới
    # top_k theo score_fn: giống sorted ổn định theo -điểm
    fn = lambda row: float("-inf") if row["score"] is None else row["score"]
    rows = sorted(st.iter_rows("A", "c1"), key=lambda r: (-fn(r), r["ord"]))
    assert [r["ord"] for r in st.top_k("A", "c1", 8, fn)] == [r["ord"] for r in rows]
    assert [r["ord"] for r in st.page("A", "c1", 2, 3)] == [2, 3, 4] and len(st.page("A", "c1", 0, 100, sort="score")) == 8
    st.set_meta("m", {"a": 1})
    assert st.get_meta("m") == {"a": 1} and st.get_meta("nope", 7) == 7
    st.close()
    # kho bền: mở lại thấy đủ dữ liệu; WAL
    st2 = rs.ResultsStore(str(tmp_path), read_only=True)
    assert st2.count() == 9
    assert sqlite3.connect(str(tmp_path / "results.sqlite")).execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    st2.close()


def test_job_key_changes_with_every_component():
    base = dict(stage="A", candidate="c", params={"a": 1, "b": 2}, window=[0, 1], stop_fill="level", risk={"r": 1}, data=["x"], code="v1")
    k0 = rs.make_job_key(**base)
    assert rs.make_job_key(**{**base, "params": {"b": 2, "a": 1}}) == k0           # thứ tự khoá không ảnh hưởng
    for name, val in (("stage", "B"), ("candidate", "d"), ("params", {"a": 2, "b": 2}), ("window", [0, 2]), ("stop_fill", "extreme"),
                      ("risk", {"r": 2}), ("data", ["y"]), ("code", "v2")):
        assert rs.make_job_key(**{**base, name: val}) != k0, name


def test_results_store_test_hook_fails_after_n_puts(tmp_path, monkeypatch):
    monkeypatch.setenv("NORA_TEST_FAIL_AFTER_PUTS", "3")
    st = rs.ResultsStore(str(tmp_path))
    st.put("a", "A", "c", {}, {}, ord=0)
    st.put("b", "A", "c", {}, {}, ord=1)
    with pytest.raises(RuntimeError, match="mô phỏng sập"):
        st.put("c", "A", "c", {}, {}, ord=2)
    st.close()
    monkeypatch.delenv("NORA_TEST_FAIL_AFTER_PUTS")
    assert rs.ResultsStore(str(tmp_path), read_only=True).count() == 3             # đã commit trước khi ném


# ─── 12.2 cấu hình lười + top-K ────────────────────────────────────────────
def _old_configs(candidate, n, seed):
    """Bản gốc của build_strategy_book.configs trước khi chuyển sang lười (giữ nguyên để so từng phần tử)."""
    keys = sorted(candidate["space"])
    grid = [dict(zip(keys, v)) for v in itertools.product(*(candidate["space"][k] for k in keys))]
    if len(grid) <= n:
        return grid
    return random.Random(seed).sample(grid, n)


@pytest.mark.parametrize("n,seed", [(1, 7), (5, 7), (24, 7), (24, 1), (150, 3), (400, 3), (10_000, 3)])
def test_iter_configs_same_sequence_as_old_configs(n, seed):
    bsb = _load_script("build_strategy_book")
    cand = {"space": {"b": [1, 2, 3, 4, 5], "a": [0.5, 1.0, 1.5], "c": [10, 20, 30, 40], "d": [7, 8, 9, 10, 11, 12]}}   # 360 tổ hợp
    assert list(bsb.iter_configs(cand, n, seed)) == _old_configs(cand, n, seed)
    assert bsb.configs(cand, n, seed) == _old_configs(cand, n, seed)
    gen = bsb.configs(cand, n, seed, lazy=True)
    assert not isinstance(gen, list) and next(iter(gen)) == _old_configs(cand, n, seed)[0]
    assert bsb.config_count(cand, n) == len(_old_configs(cand, n, seed))


def test_iter_configs_real_candidate_spaces_and_huge_space_is_lazy():
    bsb = _load_script("build_strategy_book")
    from backend.strategies import CANDIDATES
    for c in CANDIDATES:
        assert list(bsb.iter_configs(c, 24, 7)) == _old_configs(c, 24, 7)
    huge = {"space": {f"k{i}": list(range(10)) for i in range(40)}}                   # 10^40 tổ hợp (> 2^63): không dựng lưới
    first = list(itertools.islice(bsb.iter_configs(huge, 1000, 5), 5))
    assert len(first) == 5 and all(len(c) == 40 for c in first)
    assert bsb.config_count(huge, 1000) == 1000
    mid = {"space": {f"k{i}": list(range(10)) for i in range(9)}}                    # 10^9 tổ hợp, mẫu 2000: không dựng lưới 10^9
    got = list(bsb.iter_configs(mid, 2000, 1))
    assert len(got) == 2000 and len({json.dumps(c, sort_keys=True) for c in got}) == 2000


def _old_sample_configs(space, n, seed, fixed=None, venue="cex", symbol=None, oa=None):
    keys = sorted(space)
    total = 1
    for k in keys:
        total *= len(space[k])
    valid, invalid = oa._dca_filter(space, fixed, venue, symbol)
    rng = random.Random(seed)
    if total - invalid <= n:
        combos = [dict(zip(keys, c)) for c in itertools.product(*[space[k] for k in keys])]
        combos = [c for c in combos if valid(c)]
    else:
        seen, combos = set(), []
        while len(combos) < n:
            c = tuple(rng.choice(space[k]) for k in keys)
            if c not in seen:
                seen.add(c)
                cfg = dict(zip(keys, c))
                if valid(cfg):
                    combos.append(cfg)
    return combos, total


def test_topk_equals_stable_sort_prefix():
    bsb = _load_script("build_strategy_book")
    rng = random.Random(4)
    ninf = float("-inf")
    scores = [rng.choice([ninf, 1.0, 2.0, 3.0, 2.5, rng.random()]) for _ in range(300)]
    ref = sorted(range(300), key=lambda i: -scores[i])                      # sorted ổn định: hoà -> thứ tự sinh
    for k in (1, 3, 50, 300, 500):
        order = list(range(300))
        rng.shuffle(order)                                                  # kết quả đến theo thứ tự hoàn thành bất kỳ
        top = bsb.TopK(k)
        for i in order:
            top.offer(scores[i], i, {"i": i})
        assert [r["i"] for r in top.rows()] == ref[:k]


# ─── stream_stage + resume ở mức khung ──────────────────────────────────────
def _echo(job):
    return {"v": job * 2}


def test_stream_stage_skips_done_keys_and_normalizes(tmp_path):
    store = rs.ResultsStore(str(tmp_path))
    seen = []

    def handle(o, p, m, from_store):
        seen.append((o, from_store))
        return m, float(m["v"])
    items = lambda: ((i, {"i": i}, i) for i in range(10))
    kw = dict(workers=2, label="t", store=store, stage="S", candidate="c", key_of=lambda o, p, j: f"key{o}", handle=handle)
    r1 = stream_stage((x for x in items() if x[0] < 6), _echo, **kw)
    assert r1 == {"new": 6, "resumed": 0}
    seen.clear()
    r2 = stream_stage(items(), _echo, **kw)
    assert r2 == {"new": 4, "resumed": 6} and sorted(o for o, fs in seen if fs) == list(range(6))
    assert store.count("S", "c") == 10 and store.get("key7")["metrics"] == {"v": 14}
    store.close()


# ─── 12.3 resume build_strategy_book: byte-identical với lần chạy thẳng ─────
def _strip_rss(o):
    if isinstance(o, dict):
        return {k: _strip_rss(v) for k, v in o.items() if k not in ("_peak_rss_mb", "_rss_anon_mb")}
    if isinstance(o, list):
        return [_strip_rss(x) for x in o]
    return o


def _run_dirs(market):
    base = pathlib.Path(alpha_run_dir("book"))
    return sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []


def _files(run_dir, names):
    return {n: json.dumps(_strip_rss(json.loads((run_dir / n).read_text()))) for n in names}


BOOK_ARGS = {"workers": 2, "per_worker_mb": 300, "n": 4}


@pytest.mark.parametrize("fail_after", [2, 3, 6, 9])
def test_build_strategy_book_resume_is_identical_to_straight_run(market, monkeypatch, tmp_path, fail_after):
    _small_book(monkeypatch)
    bsb = _load_script("build_strategy_book")
    bsb.run_job({**BOOK_ARGS, "out": str(tmp_path / "straight")})
    straight = _run_dirs(market)[-1]
    # lần chạy bị "sập" sau N job (móc kiểm thử), rồi --resume
    monkeypatch.setenv("NORA_TEST_FAIL_AFTER_PUTS", str(fail_after))
    with pytest.raises(RuntimeError, match="mô phỏng sập"):
        bsb.run_job({**BOOK_ARGS, "out": str(tmp_path / "resumed")})
    killed = [d for d in _run_dirs(market) if d != straight][-1]
    assert not (killed / "report.json").exists()
    assert json.loads((killed / "progress.json").read_text())["status"] == "failed"
    monkeypatch.delenv("NORA_TEST_FAIL_AFTER_PUTS")
    store_rows_before = rs.ResultsStore(str(killed), read_only=True).count()
    assert store_rows_before >= fail_after
    bsb.run_job({**BOOK_ARGS, "out": str(tmp_path / "resumed"), "resume": str(killed)})
    names = ["report.json", "stage_a.json", "stage_b.json", "stage_a_counts.json"]
    assert _files(killed, names) == _files(straight, names)
    assert (tmp_path / "resumed" / "book.json").exists() == (tmp_path / "straight" / "book.json").exists()
    if (tmp_path / "straight" / "book.json").exists():
        a, b = (json.loads((tmp_path / d / "book.json").read_text()) for d in ("straight", "resumed"))
        for j in (a, b):
            for k in ("generated_at", "source", "code"):
                j.pop(k, None)
        assert a == b
    # kho đầy đủ như lần chạy thẳng và resume không chạy lại job nào đã có
    assert rs.ResultsStore(str(killed), read_only=True).count() == rs.ResultsStore(str(straight), read_only=True).count()
    assert json.loads((killed / "progress.json").read_text())["status"] == "done"


def test_build_strategy_book_resume_requires_store(market, monkeypatch, tmp_path):
    _small_book(monkeypatch)
    bsb = _load_script("build_strategy_book")
    with pytest.raises(SystemExit, match="results.sqlite"):
        bsb.run_job({**BOOK_ARGS, "resume": str(tmp_path)})


# ─── 12.2 stage A: top-K + đếm + store; 12.4 trần/ước lượng/tiến độ ─────────
def test_stage_a_keeps_only_topk_counts_and_full_rows_in_store(market, monkeypatch, tmp_path):
    sb = _small_book(monkeypatch)
    sb.CANDIDATES[0]["space"] = {"sig.lo": [25, 30, 35, 40, 45, 50], "stop_loss_rate": [1.5, 2.0], "take_profit_rate": [2.0], "timeout": [720]}
    bsb = _load_script("build_strategy_book")
    job_dir = tmp_path / "job"
    os.makedirs(job_dir, exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(job_dir))
    bsb.run_job({"workers": 2, "per_worker_mb": 300, "n": 12, "keep_top": 4, "only": "t_long", "out": str(tmp_path / "a")})
    run = _run_dirs(market)[-1]
    sa = json.loads((run / "stage_a.json").read_text())
    counts = json.loads((run / "stage_a_counts.json").read_text())
    assert len(sa["t_long"]) == 4 and counts["t_long"]["tried"] == 12 and counts["t_long"]["kept"] == 4
    assert counts["t_long"]["passed"] >= 0
    st = rs.ResultsStore(str(run), read_only=True)
    assert st.count("A", "t_long") == 12                                       # mọi hàng trong kho
    scores = [r["score"] for r in sa["t_long"]]
    assert scores == sorted(scores, reverse=True)
    top_store = st.top_k("A", "t_long", 4)
    assert [r["params"] for r in top_store if r["score"] is not None] == [r["params"] for r in sa["t_long"] if r["score"] > float("-inf")][:len([1 for r in top_store if r["score"] is not None])]
    # top-K giữ chuỗi daily (stage_a.json như cũ); hàng bị loại ngay khi đến (kém hơn top-K hiện có) được bỏ daily khi lưu
    assert all("daily" in r["dev1"] for r in sa["t_long"])
    rows = list(st.iter_rows("A", "t_long"))
    keep_params = {json.dumps(r["params"], sort_keys=True) for r in sa["t_long"]}
    for r in rows:
        if json.dumps(r["params"], sort_keys=True) in keep_params:
            assert "daily" in r["metrics"]                                        # top-K cuối cùng luôn có daily trong kho (cần cho resume)
        assert "_rss_anon_mb" not in r["metrics"] or "daily" in r["metrics"]       # RSS chỉ còn ở hàng được giữ đầy đủ
    res = json.loads((job_dir / "result.json").read_text())
    assert len(res["stage_a"]["t_long"]) == 4 and res["stage_a_counts"]["t_long"]["tried"] == 12
    assert res["store"]["rows"] >= 12 and res["estimate"]["candidates"]["t_long"]
    prog = json.loads((run / "progress.json").read_text())
    assert prog["status"] == "done" and {"stage", "done", "total", "rate", "eta_s", "peak_rss_mb"} <= set(prog)
    assert (job_dir / "progress.json").exists()                                # API đọc từ thư mục job


def test_max_configs_refuses_unless_force_large(market, monkeypatch, tmp_path, capsys):
    sb = _small_book(monkeypatch)
    sb.CANDIDATES[0]["space"] = {"sig.lo": list(range(20, 60)), "stop_loss_rate": [1.5, 2.0], "take_profit_rate": [2.0], "timeout": [720]}
    bsb = _load_script("build_strategy_book")
    args = {"workers": 2, "per_worker_mb": 300, "n": 1000, "only": "t_long", "max_configs": 50, "out": str(tmp_path / "o")}
    with pytest.raises(SystemExit, match="max_configs"):
        bsb.run_job(args)
    assert not _run_dirs(market)                                                # từ chối trước khi tạo thư mục chạy
    monkeypatch.setenv("NORA_TEST_FAIL_AFTER_PUTS", "1")                       # --force-large: cho chạy (dừng ngay sau 1 job để test nhanh)
    with pytest.raises(RuntimeError, match="mô phỏng sập"):
        bsb.run_job({**args, "force_large": True})


def test_estimate_printed_and_recorded_when_calibrating(market, monkeypatch, tmp_path, capsys):
    sb = _small_book(monkeypatch)
    sb.CANDIDATES[0]["space"] = {"sig.lo": [30, 35, 40, 45, 50], "stop_loss_rate": [1.5, 2.0], "take_profit_rate": [2.0], "timeout": [720]}
    bsb = _load_script("build_strategy_book")
    bsb.run_job({"workers": 1, "per_worker_mb": 300, "n": 10, "only": "t_long", "out": str(tmp_path / "o")})
    out = capsys.readouterr().out
    assert "[estimate] 10 cấu hình ×" in out and "s/cấu hình" in out and "worker" in out
    est = json.loads((_run_dirs(market)[-1] / "estimate.json").read_text())
    assert est["overall"]["configs"] == 10 and est["overall"]["sec_per_config"] > 0 and est["overall"]["eta_s"] > 0


# ─── 12.3 resume validate_book ──────────────────────────────────────────────
def _vb_args(market):
    import pandas as pd
    start, end = (f"{pd.Timestamp(t, unit='ms'):%Y-%m-%d}" for t in (START, T0 + 66 * DAY))
    return {"candidates": "t_long,t_short", "n": 2, "workers": 2, "per_worker_mb": 300, "start": start, "end": end,
            "train_days": 15, "test_days": 10, "sims": 200}


@pytest.mark.parametrize("fail_after", [2, 5, 11])
def test_validate_book_resume_is_identical_to_straight_run(market, monkeypatch, fail_after):
    _small_book(monkeypatch)
    vb = _load_script("validate_book")
    args = _vb_args(market)
    base = pathlib.Path(run_dir("wfa"))
    vb.run_job(args)
    straight = sorted(base.iterdir())[-1]
    monkeypatch.setenv("NORA_TEST_FAIL_AFTER_PUTS", str(fail_after))
    with pytest.raises(RuntimeError, match="mô phỏng sập"):
        vb.run_job(args)
    killed = [d for d in sorted(base.iterdir()) if d != straight][-1]
    assert not (killed / "report.json").exists()
    monkeypatch.delenv("NORA_TEST_FAIL_AFTER_PUTS")
    vb.run_job({**args, "resume": str(killed)})

    def load(d):
        r = json.loads((d / "report.json").read_text())
        r.pop("source"), r.pop("mem")
        r["provenance"].pop("computed_at")      # dấu thời gian tính (tasks.stamp_provenance) khác nhau mỗi lần chạy
        return json.dumps(_strip_rss(r))
    assert load(killed) == load(straight)
    assert rs.ResultsStore(str(killed), read_only=True).count() == rs.ResultsStore(str(straight), read_only=True).count()


def test_validate_book_max_configs(market, monkeypatch):
    _small_book(monkeypatch)
    vb = _load_script("validate_book")
    with pytest.raises(SystemExit, match="max_configs"):
        vb.run_job({**_vb_args(market), "max_configs": 3})


# ─── 12.3 resume optimize_alphas (sàng lọc theo cấu hình + cặp) ─────────────
def _oa_space(sb, market="perp"):
    from backend.alpha.compile import cond, f, tree_p
    return {"id": "t_space", "venue": "cex", "side": "LONG", "tree": cond((f("15m", "rsi_14"), "<", tree_p("lo", 40))),
            "fixed": {"market": market, "leverage": 2, "order_size_pct": 50, "take_profit_rate": 2.0, "stop_loss_rate": 2.0},
            "space": {"sig.lo": [25, 30, 35, 40, 45, 50], "trailing_stop": [1.0, 2.0, 3.0]}}


# ─── 12.4 tiến độ + huỷ (SIGTERM flush kho) ─────────────────────────────────
def test_progress_file_throttled_and_fields(tmp_path, monkeypatch):
    monkeypatch.delenv("NORA_JOB_DIR", raising=False)
    p = Progress(str(tmp_path), min_interval=5.0)
    p.start_stage("A", 100)
    first = json.loads((tmp_path / "progress.json").read_text())
    assert first["stage"] == "A" and first["total"] == 100 and first["done"] == 0 and first["status"] == "running"
    for _ in range(10):
        p.tick()
    assert json.loads((tmp_path / "progress.json").read_text())["done"] == 0       # chưa qua 5 giây: không ghi lại
    p.min_interval = 0
    p.tick(worker_peak_mb=321.0)
    cur = json.loads((tmp_path / "progress.json").read_text())
    assert cur["done"] == 11 and cur["worker_peak_rss_mb"] == 321.0 and cur["rate"] > 0 and cur["eta_s"] is not None and cur["peak_rss_mb"]
    p.finish("done")
    assert json.loads((tmp_path / "progress.json").read_text())["status"] == "done"


def test_progress_resumed_ticks_do_not_count_toward_rate(tmp_path):
    p = Progress(str(tmp_path), min_interval=0)
    p.start_stage("A", 10)
    p.tick(5, resumed=True)
    assert p.snapshot()["rate"] == 0.0 and p.snapshot()["eta_s"] is None


_KILL_SCRIPT = r"""
import os, sys, time
sys.path.insert(0, {root!r})
from backend.jobs._store import ResultsStore
from backend.jobs.runner import Progress, graceful_sigterm
d = sys.argv[1]
store = ResultsStore(d)
prog = Progress(d)
print("ready", flush=True)
try:
    with graceful_sigterm(prog):
        i = 0
        while True:
            store.put(f"k{{i}}", "A", "c", {{}}, {{"i": i}}, ord=i)   # lô chưa commit khi SIGTERM tới
            i += 1
            time.sleep(0.001)
finally:
    store.close()
"""


def test_sigterm_flushes_store_and_marks_cancelled(tmp_path):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    script = tmp_path / "k.py"
    script.write_text(_KILL_SCRIPT.format(root=root))
    proc = subprocess.Popen([sys.executable, str(script), str(tmp_path)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "ready"
    time.sleep(0.8)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=30) == 143
    n = rs.ResultsStore(str(tmp_path), read_only=True).count()
    assert n > 0 and rs.ResultsStore(str(tmp_path), read_only=True).get(f"k{n - 1}") is not None       # không mất lô cuối
    assert json.loads((tmp_path / "progress.json").read_text())["status"] == "cancelled"


# ─── 12.4 API: tiến độ, huỷ, stage_a có phân trang, tham số build lớn ───────
from test_book_ui_backend import client  # noqa: E402,F401  (fixture: app FastAPI + Popen giả)
from backend.jobs import runner as batch_jobs  # noqa: E402


def _job(state="running", pid=None, name="20260101_000009_a1b2c3", **extra):
    d = os.path.join(batch_jobs.jobs_root(), name)
    os.makedirs(d, exist_ok=True)
    batch_jobs._write_meta(d, {"id": name, "kind": "book_build", "params": {"n": 5}, "pid": pid, "created": time.time(), "started": time.time(),
                               "finished": None, "state": state, "exit_code": None if state == "running" else 0, **extra})
    return name, d


def test_job_status_surfaces_progress_file(client):
    name, d = _job("running", pid=os.getpid())
    assert client.get(f"/api/studio/book/jobs/{name}").json()["progress"] is None
    prog = {"run_dir": "/x", "stage": "A · trend_long", "done": 30, "total": 100, "rate": 2.5, "eta_s": 28.0, "peak_rss_mb": 410.0, "status": "running"}
    with open(os.path.join(d, "progress.json"), "w") as fh:
        json.dump(prog, fh)
    got = client.get(f"/api/studio/book/jobs/{name}").json()
    assert got["progress"]["done"] == 30 and got["progress"]["eta_s"] == 28.0 and got["status"] == "running"
    listed = {j["id"]: j for j in client.get("/api/studio/book/jobs").json()["jobs"]}
    assert listed[name]["progress"]["total"] == 100


def test_cancel_endpoint_sigterms_process_group_and_marks_cancelled(client):
    child = _RealPopen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    try:
        name, d = _job("running", pid=child.pid)
        r = client.post(f"/api/studio/book/jobs/{name}/cancel")
        assert r.status_code == 200, r.text
        assert child.wait(timeout=20) == -signal.SIGTERM
        got = client.get(f"/api/studio/book/jobs/{name}").json()
        assert got["status"] == "cancelled" and got["state"] == "cancelled" and got["cancel_requested"]
        # job đã kết thúc: huỷ lần nữa -> 409; job lạ -> 404
        assert client.post(f"/api/studio/book/jobs/{name}/cancel").status_code == 409
        assert client.post("/api/studio/book/jobs/20260101_000099_ffffff/cancel").status_code == 404
        assert client.post("/api/studio/book/jobs/bad-id/cancel").status_code == 422
    finally:
        if child.poll() is None:
            child.kill()


def test_stage_a_endpoint_paginates_store(client, tmp_path, monkeypatch):
    from backend.models.storage import cache_dir
    run = cache_dir(None, "book", "20260101_000000")
    st = rs.ResultsStore(run)
    for i in range(25):
        st.put(f"a{i}", "A", "trend_long", {"p": i}, {"ret_pct": float(i), "mdd_pct": 1.0, "trades": 40, "symbols_positive": 5, "sharpe": 1.0, "daily": [0.1]},
               ord=i, score=float(i) if i % 5 else None)
    for i in range(3):
        st.put(f"b{i}", "A", "trend_short", {"p": i}, {"ret_pct": 1.0}, ord=i, score=1.0)
    st.close()
    name, d = _job("done", name="20260101_000010_a1b2c3")
    with open(os.path.join(d, "progress.json"), "w") as fh:
        json.dump({"run_dir": run, "stage": "A", "done": 1, "total": 1}, fh)
    r = client.get(f"/api/studio/book/jobs/{name}/stage_a?candidate=trend_long&offset=10&limit=5").json()
    assert r["total"] == 25 and [x["ord"] for x in r["rows"]] == [10, 11, 12, 13, 14] and r["candidates"] == ["trend_long", "trend_short"]
    assert set(r["rows"][0]) == {"candidate", "ord", "params", "dev1", "score", "passed"} and "daily" not in r["rows"][0]["dev1"]
    assert r["rows"][0]["score"] is None and r["rows"][0]["passed"] is False and r["rows"][1]["passed"] is True      # ord 10: không đạt
    by_score = client.get(f"/api/studio/book/jobs/{name}/stage_a?candidate=trend_long&sort=score&limit=3").json()["rows"]
    assert [x["ord"] for x in by_score] == [24, 23, 22]
    assert client.get(f"/api/studio/book/jobs/{name}/stage_a").json()["total"] == 28                                  # mọi chiến lược
    assert client.get(f"/api/studio/book/jobs/{name}/stage_a?candidate=nope").status_code == 404
    assert client.get(f"/api/studio/book/jobs/{name}/stage_a?limit=0").status_code == 422
    assert client.get(f"/api/studio/book/jobs/{name}/stage_a?sort=x").status_code == 422
    # run_dir ngoài data/cache/process/ bị từ chối; job không có progress/result -> 404
    with open(os.path.join(d, "progress.json"), "w") as fh:
        json.dump({"run_dir": str(tmp_path)}, fh)
    assert client.get(f"/api/studio/book/jobs/{name}/stage_a").status_code == 404
    other, _ = _job("done", name="20260101_000011_a1b2c3")
    assert client.get(f"/api/studio/book/jobs/{other}/stage_a").status_code == 404


def test_build_request_accepts_large_n_and_new_flags(client):
    from test_book_ui_backend import FakePopen
    r = client.post("/api/studio/book/build", json={"only": ["trend_long"], "n": 500_000, "keep_top": 100, "force_large": True})
    assert r.status_code == 200, r.text
    from job_modules import launched
    p = launched(FakePopen.calls[-1])[1]
    assert p["n"] == 500_000 and p["keep_top"] == 100 and p["force_large"] is True
    assert client.post("/api/studio/book/build", json={"n": 1_000_001}).status_code == 422
    assert client.post("/api/studio/book/build", json={"keep_top": 2}).status_code == 422
    # resume / max_configs chỉ qua launch() ở tầng batch (không phải đầu vào người dùng của router)
    batch_jobs._check_params("book_build", {"resume": "/x", "max_configs": 9})
    with pytest.raises(batch_jobs.JobError):
        batch_jobs._check_params("book_backtest", {"resume": "/x"})


def _fast_then_slow(x):
    if x > 0:
        time.sleep(60)
    return x


def test_pool_imap_bounded_terminates_workers_on_sigterm_exit():
    """SIGTERM của cha (-> SystemExit ném vào generator) phải đóng pool và kết thúc worker đang chạy dở, không văng lỗi khác."""
    import multiprocessing
    before = {p.pid for p in multiprocessing.active_children()}   # tiến trình con do test khác để lại: không tính
    gen = parallel.pool_imap_bounded(_fast_then_slow, iter(range(4)), 2, "t")
    assert next(gen) == (0, 0)
    ours = {p.pid for p in multiprocessing.active_children()} - before
    assert ours
    t0 = time.time()
    with pytest.raises(SystemExit):
        gen.throw(SystemExit(143))

    def alive():
        return ours & {p.pid for p in multiprocessing.active_children()}

    deadline = time.time() + 20
    while alive() and time.time() < deadline:
        time.sleep(0.2)
    assert not alive() and time.time() - t0 < 25      # worker (đang ngủ 60 giây) đã bị kết thúc
