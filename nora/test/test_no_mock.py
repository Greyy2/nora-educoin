"""Cổng "không mock" (P15 §13.3): không số liệu hằng / kết quả giả trong backend/routes + backend/nautilus; mọi đường dẫn của UI (frontend/src/api.js) có route thật;
endpoint chưa có logic trên Nautilus trả 501 + detail.code NOT_READY."""
import os
import re

import pytest
from fastapi.testclient import TestClient

from backend.main import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_JS = os.path.join(ROOT, "frontend", "src", "api.js")
SCAN_DIRS = [os.path.join(ROOT, "backend", "routes"), os.path.join(ROOT, "backend", "nautilus")]

# Mẫu bị cấm: số liệu hằng / kết quả giả trong response. (regex, lý do)
FORBIDDEN = [
    (r"-15\.8", "số Monte Carlo hằng"),
    (r"confidence_95", "khoảng tin cậy hằng"),
    (r"\"20\d\d-\d\d-\d\d\"", "cửa sổ ngày cố định trong mã (dùng dữ liệu/sổ thật)"),
    (r"\[65500\.0\]", "chuỗi giá hằng"),
    (r"['\"]ord-", "mã lệnh giả"),
    (r"uuid", "id sinh ngẫu nhiên thay cho id thật (job/lệnh)"),
    (r"['\"]balance['\"]\s*:\s*\d", "số dư hằng"),
    (r"['\"]status['\"]\s*:\s*['\"]done['\"]", "trạng thái done không đi kèm job thật"),
]


def _py_files():
    for d in SCAN_DIRS:
        for dp, _dn, fns in os.walk(d):
            if "__pycache__" in dp:
                continue
            for fn in fns:
                if fn.endswith(".py"):
                    yield os.path.join(dp, fn)


@pytest.mark.parametrize("pattern,why", FORBIDDEN, ids=[w for _, w in FORBIDDEN])
def test_no_forbidden_constants(pattern, why):
    rx = re.compile(pattern)
    hits = []
    for path in _py_files():
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if line.lstrip().startswith("#"):
                    continue
                if rx.search(line):
                    hits.append(f"{os.path.relpath(path, ROOT)}:{i}: {line.strip()[:120]}")
    assert not hits, f"{why}:\n" + "\n".join(hits)


# ─── mỗi đường dẫn trong api.js có route thật ───────────────────────────────
_CALL = re.compile(r"request\(\s*(['`])(/api/[^'`]*|\$\{FR\}[^'`]*)\1(?:\s*,\s*\{([^}]*)\})?")


def _norm(path):
    """Bỏ phần query (nối bằng ?, qs(...), _qs(...), q, qsStr), thay ${enc(...)} / ${id} bằng một đoạn đường dẫn X."""
    path = re.split(r"\?|\$\{_?qs\b|\$\{q\b|\$\{qsStr", path)[0]
    return re.sub(r"\$\{[^}]*\}", "X", path)


def _ui_calls():
    with open(API_JS, encoding="utf-8") as fh:
        src = fh.read()
    fr = re.search(r"const FR = '([^']+)'", src).group(1)
    out = []
    for m in _CALL.finditer(src):
        path = m.group(2).replace("${FR}", fr)
        path = _norm(path)
        meth = re.search(r"method:\s*'(\w+)'", m.group(3) or "")
        out.append(((meth.group(1) if meth else "GET").lower(), path))
    # đường dẫn dựng bằng hàm phụ (không đi qua request('/api/...') trực tiếp) hoặc bằng chuỗi nối
    for extra in re.findall(r"`(/api/[^`?]*)", src):
        out.append((None, _norm(extra)))
    return out


def _openapi_routes():
    paths = app.openapi()["paths"]
    return [(re.compile("^" + re.sub(r"\{[^}]*\}", "[^/]+", p) + "$"), set(ms)) for p, ms in paths.items()]


def test_api_js_paths_resolve():
    routes = _openapi_routes()
    calls = _ui_calls()
    assert len(calls) >= 50, f"chỉ tách được {len(calls)} lời gọi từ api.js"
    missing = []
    for meth, path in calls:
        ok = any(rx.match(path) and (meth is None or meth in ms) for rx, ms in routes)
        if not ok:
            missing.append((meth, path))
    assert not missing, f"đường dẫn UI không có route: {missing}"


# ─── 501 NOT_READY ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    return TestClient(app)


LIVE_501 = [("get", "/api/studio/live/bot"), ("post", "/api/studio/live/bot"), ("get", "/api/studio/live/trades"), ("get", "/api/studio/live/compare"),
            ("get", "/api/studio/live/compare_events"), ("get", "/api/studio/live/positions"), ("get", "/api/studio/live/balance"),
            ("get", "/api/studio/live/status"), ("post", "/api/studio/live/order"), ("post", "/api/studio/live/cancel")]


@pytest.mark.parametrize("method,path", LIVE_501)
def test_live_endpoints_not_ready(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 501, (r.status_code, r.text[:200])
    d = r.json()["detail"]
    assert d["code"] == "NOT_READY" and d["message"] == "Live đang chuyển sang Nautilus TradingNode"
    assert "order_id" not in r.text


def test_dex_and_tick_not_ready(client):
    for method, path, body in (("post", "/api/data/ticks/crawl", {"symbols": ["AERO"], "days": 7}), ("get", "/api/data/ticks/coverage", None)):
        r = client.request(method.upper(), path, json=body)
        assert r.status_code == 501 and r.json()["detail"]["code"] == "NOT_READY", (path, r.status_code, r.text[:200])
        assert "DEX" in r.json()["detail"]["message"]
    from backend.optimize.process.process import NotReady
    from backend.routes import process as process_routes
    with pytest.raises(NotReady, match="DEX/AMM"):
        process_routes.check_backtest_symbols(["dex:AERO"])
    with pytest.raises(NotReady, match="DEX/AMM"):
        process_routes.build_job("book_backtest", {"start": "2024-01-01", "end": "2024-02-01", "data": "tick"})


def test_chart_okx_source_not_ready(client):
    r = client.post("/api/studio/chart/explain", json={"symbol": "BTC", "start": 0, "end": 1, "source": "okx"})
    assert r.status_code == 501 and r.json()["detail"]["code"] == "NOT_READY"


def test_meta_offers_no_dex_and_declares_engine(client):
    meta = client.get("/api/studio/meta").json()
    assert meta["engine"]["name"] == "nautilus_trader" and meta["engine"]["docs_url"].startswith("https://nautilustrader.io/docs")
    assert all(not a.startswith("dex:") for a in meta["universe"]["data"]["assets"])
    assert meta["live"]["modes"] == [] and meta["live"]["not_ready"]["code"] == "NOT_READY"


def test_health_reports_engine(client):
    h = client.get("/api/health").json()
    assert h["ok"] is True and h["engine"]["name"] == "nautilus_trader" and h["engine"]["version"]


def test_check_update_never_offers_install(client):
    r = client.get("/api/studio/nautilus/check_update")
    assert r.status_code == 200 and "update_command" not in r.json()
    assert "version" in client.get("/api/studio/nautilus/version").json()


def test_environments_have_no_keys_and_live_not_ready(client):
    env = client.get("/api/studio/environments").json()
    assert env["backtest"]["ready"] is True
    assert all(env[k]["ready"] is False and env[k]["not_ready"]["code"] == "NOT_READY" for k in ("paper", "testnet", "live"))


def test_test_connection_without_keys_says_not_configured(client, monkeypatch, tmp_path):
    # P15-D: không có khoá OKX -> báo thẳng "chưa cấu hình", không gọi mạng, không trả khoá (kể cả dạng che)
    from backend.nautilus import live
    monkeypatch.setattr(live, "CONFIG_ENV_PATH", str(tmp_path / "okx.env"))
    for k in ("NORA_OKX_KEY", "NORA_OKX_SECRET", "NORA_OKX_PASSPHRASE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(live.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("không được gọi mạng khi chưa có khoá")))
    out = client.post("/api/studio/live/test_connection", json={"mode": "demo"}).json()
    assert out["ok"] is False and out["has_credentials"] is False and "Chưa cấu hình" in out["message"] and "masked_key" not in out


def test_meta_unsupported_keys_are_flagged(client):
    # P15-D: tính năng Nautilus không mô phỏng được đánh dấu unsupported + help_vi thống nhất (routes/process.py::UNSUPPORTED)
    un = {u["key"]: u for u in client.get("/api/studio/meta").json()["unsupported"]}
    for k in ("slippage_rate", "limit_through_pct", "stop_fill", "intrabar_path", "maintenance_margin_rate", "liquidation", "funding"):
        assert un[k]["unsupported"] is True and "Nautilus không mô phỏng" in un[k]["help_vi"], k


def test_default_position_does_not_trigger_unsupported_warnings():
    # mặc định (slippage 0, limit_through 0, stop_fill level, intrabar ohlc) không kích cảnh báo "không mô phỏng" cho các khoá đó
    from backend.models.params import BASE_POSITION, VENUE_COSTS, StrategyParams
    assert BASE_POSITION["limit_through_pct"] == 0.0 and BASE_POSITION["stop_fill"] == "level"
    assert all(v[2] == 0.0 for k, v in VENUE_COSTS.items() if k[0] == "cex") and StrategyParams().slippage_rate == 0.0
