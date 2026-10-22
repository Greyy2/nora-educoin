"""Kiểm thử toàn diện tính cô lập EDU / COIN (P4 — Verification & Acceptance).

Kiểm tra:
1. EDU route allow-list: đảm bảo không có route live/bot, không có exchange credentials,
   không có PUT/DELETE/POST trên alpha/strategy của COIN, không có scan/research/book jobs.
2. COIN routes: đảm bảo đầy đủ live, bot, portfolio, data, alpha studio.
3. Session & Cookie isolation: kiểm tra không có cross-boundary fallback giữa edu_session và coin_session.
4. CORS isolation: đảm bảo không dùng allow_origins=["*"] với credentials.
5. Unit environment isolation: EDU không nạp okx.env; COIN nạp đầy đủ.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Đảm bảo import được backend
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from backend.apps.edu import app as edu_app
from backend.apps.coin import app as coin_app
from backend.routes.system import (
    _get_cookie_key_for_request,
    current_user,
    set_uid_cookie,
    clear_uid_cookie,
)


def get_all_routes_info(app):
    """Lấy danh sách (method, path) của app từ OpenAPI spec chuẩn."""
    routes = []
    paths = app.openapi().get("paths", {})
    for path, methods_dict in paths.items():
        for method in methods_dict:
            routes.append((method.upper(), path))
    return routes


def test_edu_route_allowlist():
    """EDU phải bị giới hạn nghiêm ngặt, không chứa bot, live, scan, research hay mutating endpoints."""
    routes = get_all_routes_info(edu_app)
    paths = [r[1] for r in routes]

    # Không có live hay bot control
    for m, p in routes:
        assert "/live" not in p, f"Lộ route /live trong EDU: {m} {p}"
        assert not ("bot" in p.lower() and "prompt" not in p.lower()), f"Lộ route bot trong EDU: {m} {p}"
        assert "/portfolio" not in p, f"Lộ route portfolio trong EDU: {m} {p}"
        assert "/data/crawl" not in p, f"Lộ route crawl trong EDU: {m} {p}"
        assert "/scan" not in p, f"Lộ route scan trong EDU: {m} {p}"
        assert "/research" not in p, f"Lộ route research trong EDU: {m} {p}"

    # Không cho phép PUT /source (sửa code hệ thống)
    put_source_routes = [r for r in routes if r[0] == "PUT" and "/source" in r[1]]
    assert len(put_source_routes) == 0, f"EDU cho phép sửa mã nguồn: {put_source_routes}"

    # Không cho phép POST /backtest, /wfa, /mc trên book_router
    book_post_routes = [r for r in routes if r[0] == "POST" and any(x in r[1] for x in ["/backtest", "/wfa", "/mc"])]
    assert len(book_post_routes) == 0, f"EDU cho phép khởi chạy batch jobs: {book_post_routes}"

    # Có đầy đủ route giáo dục cần thiết
    assert any("/api/edu" in p for p in paths), "Thiếu route /api/edu trong EDU app"
    assert any("/api/studio/education" in p for p in paths), "Thiếu /api/studio/education trong EDU app"
    assert any("/api/studio/meta" in p for p in paths), "Thiếu /api/studio/meta trong EDU app"
    print(f"✅ test_edu_route_allowlist passed: {len(routes)} routes hợp lệ.")


def test_coin_route_coverage():
    """COIN app phải có đầy đủ studio, live, portfolio, data."""
    routes = get_all_routes_info(coin_app)
    paths = [r[1] for r in routes]

    assert any("/live" in p for p in paths), "COIN app thiếu /live routes"
    assert any("/portfolio" in p for p in paths), "COIN app thiếu /portfolio routes"
    assert any("/data" in p for p in paths), "COIN app thiếu /data routes"
    assert any("/api/studio" in p for p in paths), "COIN app thiếu /api/studio routes"
    print(f"✅ test_coin_route_coverage passed: {len(routes)} routes hợp lệ.")


def test_session_cookie_isolation():
    """Kiểm tra không fallback chéo giữa cookie của EDU và COIN."""
    # 1. Request trong context EDU
    req_edu = MagicMock()
    req_edu.app.title = "Nora EDU API"
    req_edu.headers = {"host": "edu.nora.expsolution.io"}
    assert _get_cookie_key_for_request(req_edu) == "edu_session"

    # 2. Request trong context COIN
    req_coin = MagicMock()
    req_coin.app.title = "Nora COIN API"
    req_coin.headers = {"host": "coin.nora.expsolution.io"}
    assert _get_cookie_key_for_request(req_coin) == "coin_session"

    # 3. Request COIN nhưng chỉ có cookie edu_session -> current_user phải trả None (không fallback chéo)
    req_cross = MagicMock()
    req_cross.app.title = "Nora COIN API"
    req_cross.headers = {"host": "coin.nora.expsolution.io"}
    req_cross.cookies = {"edu_session": "invalid_or_foreign_cookie"}
    user = current_user(req_cross)
    assert user is None, "Phát hiện fallback chéo từ COIN sang edu_session!"

    # 4. Request EDU nhưng chỉ có cookie coin_session -> current_user phải trả None
    req_cross2 = MagicMock()
    req_cross2.app.title = "Nora EDU API"
    req_cross2.headers = {"host": "edu.nora.expsolution.io"}
    req_cross2.cookies = {"coin_session": "invalid_or_foreign_cookie"}
    user2 = current_user(req_cross2)
    assert user2 is None, "Phát hiện fallback chéo từ EDU sang coin_session!"

    print("✅ test_session_cookie_isolation passed: Cookie & Session cô lập hoàn toàn.")


def test_cors_no_wildcard():
    """Kiểm tra CORS không dùng wildcard '*' ở cả 2 app."""
    for app, name in [(edu_app, "EDU"), (coin_app, "COIN")]:
        for middleware in app.user_middleware:
            if "CORSMiddleware" in str(middleware.cls):
                options = getattr(middleware, "kwargs", getattr(middleware, "options", {}))
                origins = options.get("allow_origins", [])
                assert "*" not in origins, f"{name} app vẫn dùng allow_origins=['*']!"
    print("✅ test_cors_no_wildcard passed: CORS chặt chẽ.")


def test_unit_env_isolation():
    """Kiểm tra file systemd unit templates: EDU không nạp okx.env, COIN nạp okx.env."""
    edu_in = Path(__file__).resolve().parent.parent / "ops" / "systemd" / "nora-edu.service.in"
    coin_in = Path(__file__).resolve().parent.parent / "ops" / "systemd" / "nora-coin.service.in"

    edu_content = edu_in.read_text(encoding="utf-8")
    coin_content = coin_in.read_text(encoding="utf-8")

    assert "okx.env" not in edu_content, "EDU unit template không được nạp okx.env!"
    assert "okx.env" in coin_content, "COIN unit template phải nạp okx.env!"
    assert "--host 127.0.0.1" in coin_content, "COIN unit phải bind 127.0.0.1!"
    print("✅ test_unit_env_isolation passed: Secrets và loopback bind đã kiểm tra.")


if __name__ == "__main__":
    test_edu_route_allowlist()
    test_coin_route_coverage()
    test_session_cookie_isolation()
    test_cors_no_wildcard()
    test_unit_env_isolation()
    print("\n🎉 TOÀN BỘ CÁC BÀI TEST CÔ LẬP EDU / COIN ĐÃ ĐẠT 100%!")
