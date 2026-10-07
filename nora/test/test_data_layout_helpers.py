"""
test_data_layout_helpers.py — P9.3a: API đường dẫn dữ liệu của crawl/store.py (ADR-P9 §4).

Mỗi helper được kiểm trên cây tạm ở 3 trạng thái: (1) chỉ layout cũ, (2) chỉ layout mới, (3) đã chuyển + symlink tương đối ở đường cũ.
Cộng: env đọc ở thời điểm gọi, chế độ phẳng (NORA_LOCAL_DATA_ROOT), bí danh binance_hist đã gỡ, cache chỉ process/ + shared/, cache_dir() định tuyến mọi tên cũ, allowed_roots theo realpath.
"""
import os

import pytest

from backend.crawl import store as st
from backend.db import data_layout as dl   # shim: cùng một module


def _mk(root, *rel):
    path = os.path.join(root, *rel)
    os.makedirs(path, exist_ok=True)
    return path


def _touch(root, *rel):
    path = os.path.join(root, *rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write("{}")
    return path


def _link(home, old_rel, new_rel):
    """Symlink tương đối ở đường cũ trỏ về đường mới (như script migrate)."""
    old = os.path.join(home, old_rel)
    os.makedirs(os.path.dirname(old), exist_ok=True)
    os.symlink(os.path.relpath(os.path.join(home, new_rel), os.path.dirname(old)), old)


# (đường cũ, đường mới, là file?)
PAIRS = [
    ("okx", "market/okx", 0), ("binance", "market/binance", 0), ("_meta", "market/_meta", 0),
    ("alphas", "alpha", 0), ("education/samples.json", "alpha/education/samples.json", 1), ("education/results", "backtest/education", 0),
    ("_cache/funnel", "alpha/funnel", 0), ("_cache/book", "alpha/book", 0), ("_cache/book_wfa", "wfa", 0), ("_cache/live", "live", 0),
    ("_cache/api_jobs", "cache/process", 0), ("_cache/runs", "cache/process/_mem", 0), ("_cache/quality_gate", "cache/shared/quality_gate", 0),
    ("_cache/backtest", "backtest", 0), ("_cache/carlo", "carlo", 0), ("_cache/shared", "cache/shared", 0),
]


def build(home, state):
    """state ∈ old | new | migrated. Tạo các nút NGUỒN (kèm vài mục con để kiểm leaf-level)."""
    os.makedirs(home, exist_ok=True)
    real = (lambda o, n: o) if state == "old" else (lambda o, n: n)
    for ex in ("okx", "binance"):
        _mk(home, real(ex, f"market/{ex}"), "cex", "BTC", "perp")
    _mk(home, real("okx", "market/okx"), "dex", "AERO")
    _mk(home, real("_meta", "market/_meta"))
    a = real("alphas", "alpha")
    _touch(home, a, "book.json"); _touch(home, a, "registry.json"); _touch(home, a, "presets.json")
    _mk(home, a, "user"); _touch(home, a, "explore", "book.json")
    _touch(home, real("education/samples.json", "alpha/education/samples.json"))
    _touch(home, real("education/results", "backtest/education"), "r1.json")
    for old, new in (("_cache/funnel", "alpha/funnel"), ("_cache/book", "alpha/book"), ("_cache/book_wfa", "wfa"), ("_cache/live", "live"),
                     ("_cache/api_jobs", "cache/process"), ("_cache/runs", "cache/process/_mem"),
                     ("_cache/quality_gate", "cache/shared/quality_gate"), ("_cache/shared", "cache/shared")):
        _mk(home, real(old, new), "RUN1")
    if state == "migrated":
        for old, new, _ in PAIRS:
            if old == "_cache/backtest" or old == "_cache/carlo":
                continue
            _link(home, old, new)
    return home


@pytest.fixture(params=["old", "new", "migrated"])
def layout(request, tmp_path, monkeypatch):
    for k in ("NORA_LOCAL_DATA_ROOT", "NORA_ALPHAS_DIR", "NORA_BOOK_PATH", "NORA_PRESETS_PATH", "NORA_EXCHANGE"):
        monkeypatch.delenv(k, raising=False)
    home = build(str(tmp_path / "home"), request.param)
    monkeypatch.setenv("NORA_DATA_ROOT", home)
    return request.param, home


def exp(state, home, old, new):
    """Đường kỳ vọng: cũ ở trạng thái old, mới ở new/migrated."""
    return os.path.join(home, old if state == "old" else new)


def test_data_home_and_flat(layout, monkeypatch, tmp_path):
    state, home = layout
    assert st.data_home() == home and st.layout_version() == (1 if state == "old" else 2)
    assert dl.data_home is st.data_home
    flat = tmp_path / "flat"
    flat.mkdir()
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(flat))     # test: ưu tiên NORA_LOCAL_DATA_ROOT, phẳng
    assert st.data_home() == str(flat) and st.market_root() == st.market_root("binance") == str(flat)
    monkeypatch.setenv("NORA_EXCHANGE", "kraken")             # chế độ phẳng không kiểm sàn (như trước P9.3)
    assert st.default_data_root() == str(flat)


def test_market_root_and_dir(layout, monkeypatch):
    state, home = layout
    assert st.market_root() == exp(state, home, "okx", "market/okx") == st.exchange_root() == st.default_data_root()
    assert st.market_root("binance") == exp(state, home, "binance", "market/binance")
    assert st.market_dir() == os.path.join(st.market_root(), "cex")
    assert st.market_dir("okx", "cex", "btc", "perp") == os.path.join(st.market_root("okx"), "cex", "BTC", "perp")
    assert st.market_dir(symbol="BTC@perp") == st.market_dir(symbol="BTC", instrument="perp")
    assert st.market_dir("okx", "dex", "AERO") == os.path.join(st.market_root("okx"), "dex", "AERO")
    assert os.path.isdir(st.market_dir("okx", "cex", "BTC", "perp"))
    monkeypatch.setenv("NORA_EXCHANGE", "binance")             # env đọc lúc gọi: đổi sàn có hiệu lực ngay
    assert st.market_root() == st.market_root("binance")
    with pytest.raises(ValueError):
        st.market_dir("binance", "cex_ref")                    # venue cex_ref đã gỡ cùng binance_hist
    with pytest.raises(ValueError):
        st.market_dir("okx", "futures")
    with pytest.raises(ValueError):
        st.market_root("kraken")
    monkeypatch.setenv("NORA_EXCHANGE", "kraken")
    with pytest.raises(ValueError):
        st.market_root()


def test_binance_hist_alias_removed(layout):
    state, home = layout
    assert not hasattr(st, "HISTORICAL_ALIASES")
    with pytest.raises(ValueError):
        st.resolve_source("binance_hist")
    okx = st.resolve_source("okx")
    assert okx == st.resolve_source() and okx.root == st.market_root("okx") and okx.cex_dir == "cex" and okx.alias is None
    assert st.resolve_source("binance").root == st.market_root("binance")
    with pytest.raises(ValueError):
        st.resolve_source("nope")


def test_resolve_source_dirname_and_default_exchange(layout, monkeypatch):
    state, home = layout
    monkeypatch.setenv("NORA_EXCHANGE", "binance")
    assert st.resolve_source().exchange == "binance"
    _mk(home, "mydata", "cex", "ETH")                          # thư mục nguồn bất kỳ <home>/<tên>/cex
    s = st.resolve_source("mydata")
    assert s.root == os.path.join(home, "mydata") and s.cex_path.endswith(os.path.join("mydata", "cex"))


def test_meta_alpha_and_files(layout, monkeypatch):
    state, home = layout
    assert st.meta_dir() == exp(state, home, "_meta", "market/_meta")
    a = exp(state, home, "alphas", "alpha")
    assert st.alpha_dir() == a
    assert st.alpha_dir("explore", "book.json") == os.path.join(a, "explore", "book.json") and os.path.isfile(st.alpha_dir("explore", "book.json"))
    assert st.alpha_user_dir() == os.path.join(a, "user")
    for name in ("book.json", "registry.json", "presets.json"):
        assert st.alpha_file(name) == os.path.join(a, name) and os.path.isfile(st.alpha_file(name))
    assert st.alpha_file("book") == st.alpha_file("book.json")
    assert st.alpha_file("research.json").startswith(a)         # file chưa có: vẫn ở gốc đang dùng
    # ghi đè bằng env, đọc lúc gọi
    monkeypatch.setenv("NORA_ALPHAS_DIR", "/x/alphas")
    assert st.alpha_dir("user") == "/x/alphas/user" and st.alpha_file("registry.json") == "/x/alphas/registry.json"
    monkeypatch.setenv("NORA_BOOK_PATH", "/y/b.json")
    monkeypatch.setenv("NORA_PRESETS_PATH", "/y/p.json")
    assert st.alpha_file("book") == "/y/b.json" and st.alpha_file("presets.json") == "/y/p.json" and st.alpha_file("registry") == "/x/alphas/registry.json"
    monkeypatch.delenv("NORA_ALPHAS_DIR")
    assert st.alpha_dir() == a                                  # bỏ env -> trở lại ngay


def test_education_paths(layout, monkeypatch):
    state, home = layout
    assert st.alpha_education_samples() == exp(state, home, "education/samples.json", "alpha/education/samples.json")
    assert os.path.isfile(st.alpha_education_samples())
    assert st.education_results_dir() == exp(state, home, "education/results", "backtest/education")
    monkeypatch.setenv("NORA_ALPHAS_DIR", "/elsewhere")          # samples không đi theo NORA_ALPHAS_DIR
    assert st.alpha_education_samples() == exp(state, home, "education/samples.json", "alpha/education/samples.json")


def test_run_dirs(layout):
    state, home = layout
    assert st.alpha_run_dir("funnel") == exp(state, home, "_cache/funnel", "alpha/funnel")
    assert st.alpha_run_dir("book", "RUN1") == os.path.join(exp(state, home, "_cache/book", "alpha/book"), "RUN1")
    assert os.path.isdir(st.alpha_run_dir("book", "RUN1"))
    new_id = st.alpha_run_dir("funnel", "NEWRUN")                 # id chưa có: theo gốc đang dùng
    assert new_id == os.path.join(st.alpha_run_dir("funnel"), "NEWRUN") and not os.path.exists(new_id)
    assert st.run_dir("wfa") == exp(state, home, "_cache/book_wfa", "wfa")
    assert st.run_dir("wfa", "RUN1") == os.path.join(st.run_dir("wfa"), "RUN1")
    # backtest/carlo chưa từng có ở cây cũ: không có gì tồn tại -> LUÔN đường mới (không bao giờ tạo thư mục cũ chưa có)
    assert st.run_dir("backtest", "b1") == os.path.join(home, "backtest", "b1")
    assert st.run_dir("carlo") == os.path.join(home, "carlo")
    with pytest.raises(ValueError):
        st.alpha_run_dir("wfa")
    with pytest.raises(ValueError):
        st.run_dir("funnel")


def test_live_dir(layout):
    state, home = layout
    assert st.live_dir("okx", "demo", engine="unified") == os.path.join(exp(state, home, "_cache/live", "live"), "okx_demo_unified")
    assert st.live_dir("okx", "paper", "explore", "unified") == os.path.join(st.live_dir("okx", "paper", "main").rsplit(os.sep, 1)[0], "okx_paper_explore")
    assert os.path.basename(st.live_dir("okx", "demo")) == "okx_demo"
    assert os.path.basename(st.live_dir("okx", "demo", "explore", "unified")) == "okx_demo_explore_unified"


def test_state_key_copy_matches_bot():
    from backend.live.bot import state_key
    for args in (("okx", "demo"), ("okx", "demo", "main", "unified"), ("okx", "paper", "explore", "unified"), ("okx", "live", "explore", "legacy"), ("paper", "x")):
        assert st.live_state_key(*args) == state_key(*args)


def test_cache_helpers(layout):
    state, home = layout
    assert st.cache_process_dir() == exp(state, home, "_cache/api_jobs", "cache/process")
    assert st.cache_process_dir("RUN1") == os.path.join(st.cache_process_dir(), "RUN1") and os.path.isdir(st.cache_process_dir("RUN1"))
    assert st.cache_shared_dir() == exp(state, home, "_cache/shared", "cache/shared")
    assert st.cache_shared_dir("k") == os.path.join(st.cache_shared_dir(), "k")
    assert st.cache_quality_gate_dir() == exp(state, home, "_cache/quality_gate", "cache/shared/quality_gate")
    assert st.cache_runs_dir() == exp(state, home, "_cache/runs", "cache/process/_mem")


def test_staging_dir_and_no_crawl_dir(layout):
    state, home = layout
    nora = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(st.__file__))))
    old_staging = os.path.join(nora, "data_staging")
    if os.path.exists(old_staging):
        pytest.skip("nora/data_staging tồn tại trên máy này")
    assert st.cache_staging_dir() == os.path.join(home, "cache", "process", "_staging")   # thư mục cũ chưa có -> không dùng (không tạo lại)
    assert not hasattr(st, "cache_crawl_dir")                      # zip crawler không thuộc cây dữ liệu (ADR-P9 §4)


def test_new_dir_preferred_when_both_exist(tmp_path, monkeypatch):
    """Cả đường mới lẫn cũ cùng tồn tại thật (chưa symlink) -> mới thắng."""
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    home = str(tmp_path)
    _mk(home, "alphas"); _mk(home, "alpha"); _mk(home, "_cache", "funnel"); _mk(home, "alpha", "funnel")
    monkeypatch.setenv("NORA_DATA_ROOT", home)
    assert st.alpha_dir() == os.path.join(home, "alpha") and st.alpha_run_dir("funnel") == os.path.join(home, "alpha", "funnel")


def test_fresh_tree_uses_new_paths(tmp_path, monkeypatch):
    """Cây trống (chưa có đường cũ nào) -> luôn đường MỚI; đường cũ chỉ được dùng khi nó đã tồn tại."""
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setenv("NORA_DATA_ROOT", str(tmp_path))
    assert st.alpha_dir() == str(tmp_path / "alpha") and st.market_root("okx") == str(tmp_path / "market" / "okx")
    assert st.cache_process_dir("j1") == str(tmp_path / "cache" / "process" / "j1")
    (tmp_path / "alphas").mkdir()                                  # đường cũ có sẵn -> vẫn dùng (cây chưa chuyển)
    assert st.alpha_dir() == str(tmp_path / "alphas")


def test_env_resolved_at_call_time(tmp_path, monkeypatch):
    a, b = build(str(tmp_path / "a"), "old"), build(str(tmp_path / "b"), "new")
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setenv("NORA_DATA_ROOT", a)
    first = (st.alpha_dir(), st.market_root(), st.cache_process_dir(), st.live_dir("okx", "demo"))
    monkeypatch.setenv("NORA_DATA_ROOT", b)
    second = (st.alpha_dir(), st.market_root(), st.cache_process_dir(), st.live_dir("okx", "demo"))
    assert all(x.startswith(a) for x in first) and all(x.startswith(b) for x in second) and first[0].endswith("alphas") and second[0].endswith("alpha")
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", a)                  # LOCAL ưu tiên hơn NORA_DATA_ROOT
    assert st.data_home() == a and st.alpha_dir() == os.path.join(a, "alphas")
    monkeypatch.setenv("NORA_EXCHANGE", "binance")
    assert st.exchange() == "binance"


def test_legacy_nora_data_root_as_flat_exchange_root(tmp_path, monkeypatch):
    """NORA_DATA_ROOT cũ = gốc sàn (có cex/ ngay dưới) -> phẳng như trước."""
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    _mk(str(tmp_path), "cex", "BTC")
    monkeypatch.setenv("NORA_DATA_ROOT", str(tmp_path))
    assert st.market_root() == st.exchange_root("binance") == str(tmp_path)


CACHE_ROUTES = [   # tên cũ -> (đường cũ, đường mới)
    ("api_jobs", "_cache/api_jobs", "cache/process"), ("book", "_cache/book", "alpha/book"), ("funnel", "_cache/funnel", "alpha/funnel"),
    ("book_wfa", "_cache/book_wfa", "wfa"), ("live", "_cache/live", "live"), ("quality_gate", "_cache/quality_gate", "cache/shared/quality_gate"),
    ("runs", "_cache/runs", "cache/process/_mem"),
]


@pytest.mark.parametrize("name,old,new", CACHE_ROUTES)
def test_cache_dir_routes_old_names(layout, name, old, new):
    state, home = layout
    want = exp(state, home, old, new)
    assert st.cache_dir(None, name) == want and os.path.isdir(want)
    leaf = st.cache_dir(None, name, "X1")                         # có tham số con -> tạo, nằm dưới gốc đã chọn
    assert leaf == os.path.join(want, "X1") and os.path.isdir(leaf)
    assert os.path.realpath(leaf) == os.path.realpath(os.path.join(home, old if state == "old" else new, "X1"))


def test_cache_dir_routes_real_target(layout):
    """Sau khi tạo qua đường nào cũng thấy qua đường kia (state migrated: symlink; new: đường cũ không có)."""
    state, home = layout
    p = st.cache_dir(None, "funnel", "ZZ")
    assert os.path.isdir(p)
    if state == "migrated":
        assert os.path.isdir(os.path.join(home, "_cache", "funnel", "ZZ")) and os.path.isdir(os.path.join(home, "alpha", "funnel", "ZZ"))


def test_cache_dir_other_names_and_root(layout):
    state, home = layout
    cache_root = exp(state, home, "_cache", "cache/process")     # tên lạ -> dưới cache/process (cũ: _cache), không sinh cache/<tên>
    assert st.cache_dir(None) == cache_root
    assert st.cache_dir(None, "research", "x") == os.path.join(cache_root, "research", "x")
    assert os.path.isdir(os.path.join(cache_root, "research", "x"))


def test_cache_has_only_process_and_shared(layout):
    """Mọi helper cache (kể cả tên lạ, quality gate, staging, log RAM) chỉ dùng cache/process và cache/shared."""
    state, home = layout
    for name in ("research", "reports", "x", "quality_gate", "runs", "api_jobs"):
        st.cache_dir(None, name, "t")
    st.cache_dir(None)
    os.makedirs(st.cache_runs_dir(), exist_ok=True); os.makedirs(st.cache_staging_dir(), exist_ok=True)
    os.makedirs(st.cache_quality_gate_dir(), exist_ok=True)
    cache = os.path.join(home, "cache")
    if os.path.isdir(cache):
        assert set(os.listdir(cache)) <= {"process", "shared"}
    if state != "old":
        assert os.path.realpath(st.cache_quality_gate_dir()) == os.path.realpath(os.path.join(home, "cache", "shared", "quality_gate"))
        assert os.path.realpath(st.cache_runs_dir()).startswith(os.path.realpath(os.path.join(home, "cache", "process")))


def test_cache_dir_signature_and_explicit_root(tmp_path, monkeypatch):
    """data_root tường minh = home cho định tuyến; chưa có gì -> đường MỚI (không tạo _cache/ cũ)."""
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", str(tmp_path / "ignored"))
    root = str(tmp_path / "explicit")
    p = st.cache_dir(root, "quality_gate")
    assert p == os.path.join(root, "cache", "shared", "quality_gate") and os.path.isdir(p)
    assert not os.path.exists(os.path.join(root, "_cache"))
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT")
    monkeypatch.setenv("NORA_DATA_ROOT", str(tmp_path / "envhome"))
    assert st.cache_dir(None, "book") == str(tmp_path / "envhome" / "alpha" / "book")


def test_quality_gate_disk_cache_path_still_under_cache(layout):
    state, home = layout
    path = st._disk_cache_path(("d", "1m", ()), None)             # data_root=None -> home từ env
    assert os.path.dirname(path) == exp(state, home, "_cache/quality_gate", "cache/shared/quality_gate")


def test_allowed_roots_realpath(layout, tmp_path):
    state, home = layout
    real = os.path.realpath
    funnel = st.allowed_roots("funnel")
    assert all(p == real(p) for p in funnel)
    if state == "old":     # hai gốc khác nhau (alpha/funnel chưa tồn tại: realpath giữ nguyên chuỗi)
        assert funnel == [real(os.path.join(home, "alpha", "funnel")), real(os.path.join(home, "_cache", "funnel"))]
    else:                  # migrated: symlink cũ trỏ về mới -> một gốc; new: đường cũ chưa tồn tại nhưng vẫn được liệt kê
        assert real(os.path.join(home, "alpha", "funnel")) in funnel
        if state == "migrated":
            assert funnel == [real(os.path.join(home, "alpha", "funnel"))]
    runs = st.allowed_roots("runs")
    for kind in ("book", "funnel", "wfa", "process"):
        assert set(st.allowed_roots(kind)) <= set(runs)
    assert real(st.alpha_run_dir("book", "RUN1")) in [r + os.sep + "RUN1" for r in st.allowed_roots("book")]
    for kind in ("alpha", "live", "mem", "shared", "quality_gate", "staging", "education_results", "meta", "backtest", "wfa", "carlo"):
        roots = st.allowed_roots(kind)
        assert roots and all(os.path.isabs(r) for r in roots) and len(set(roots)) == len(roots)
    with pytest.raises(ValueError):
        st.allowed_roots("etc")


def test_is_within_path_traversal(layout, tmp_path):
    state, home = layout
    run = st.alpha_run_dir("book", "RUN1")
    assert st.is_within(os.path.join(run, "out.json"), "runs") and st.is_within(run, "book")
    assert st.is_within(os.path.join(home, "alpha", "book", "RUN1"), "book") and st.is_within(os.path.join(home, "_cache", "book", "RUN1"), "book")
    assert not st.is_within(os.path.join(run, "..", "..", "..", "etc", "passwd"), "runs")
    assert not st.is_within(str(tmp_path), "runs")
    sibling = os.path.join(os.path.dirname(os.path.join(home, "_cache", "book")), "book_evil")   # tiền tố chuỗi giống nhưng khác thư mục
    assert not st.is_within(sibling, "book")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = os.path.join(run, "esc")
    os.symlink(str(outside), link)                                  # symlink thoát khỏi gốc phải bị chặn (so realpath)
    assert not st.is_within(link, "runs")


def test_allowed_roots_env_call_time(tmp_path, monkeypatch):
    a, b = build(str(tmp_path / "a"), "old"), build(str(tmp_path / "b"), "old")
    monkeypatch.delenv("NORA_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setenv("NORA_DATA_ROOT", a)
    ra = st.allowed_roots("book")
    monkeypatch.setenv("NORA_DATA_ROOT", b)
    rb = st.allowed_roots("book")
    assert all(x.startswith(os.path.realpath(a)) for x in ra) and all(x.startswith(os.path.realpath(b)) for x in rb)


def test_shim_is_same_module():
    import backend.crawl.store as s
    assert dl is s and dl.cache_dir is s.cache_dir and dl.allowed_roots is s.allowed_roots
