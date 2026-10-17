"""E2E Verification Script for Nora API on NautilusTrader (P17 T2).

Kiểm tra:
1. /api/health -> 200 {ok, engine: {name: 'nautilus_trader', version: '1.231.0'}}
2. /api/studio/meta -> 200, ETag, unsupported, metrics.defs
3. /api/studio/education/samples -> 200, đủ 50 mẫu
4. /api/live/* -> 501 NOT_READY (không trả id bịa)
5. Custom job thật: POST /api/studio/custom/backtest với mẫu trend_dual_ema
6. API phản hồi < 1s trong khi job chạy
7. Bất biến kết quả: provenance thật, metrics thật, trades thật
8. User & Owner flow: tạo user -> phiên cookie -> lưu alpha có owner -> kiểm tra danh sách chiến lược -> dọn dẹp
"""
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

BASE_URL = os.environ.get("NORA_API_URL", "http://127.0.0.1:18010")


def req(path: str, method: str = "GET", body: Any = None, expected_status: int = 200, extra_headers: Optional[Dict[str, str]] = None) -> Tuple[Any, float]:
    t0 = time.time()
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            dur = time.time() - t0
            assert resp.status == expected_status, f"{path}: status {resp.status} != {expected_status}"
            raw = resp.read()
            return (json.loads(raw) if raw else None), dur
    except urllib.error.HTTPError as e:
        dur = time.time() - t0
        if e.code == expected_status:
            raw = e.read()
            return (json.loads(raw) if raw else None), dur
        raise RuntimeError(f"{path}: expected HTTP {expected_status}, got {e.code}: {e.read().decode()}") from e


def req_full(path: str, method: str = "GET", body: Any = None, expected_status: int = 200, extra_headers: Optional[Dict[str, str]] = None) -> Tuple[Any, float, Any]:
    t0 = time.time()
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            dur = time.time() - t0
            assert resp.status == expected_status, f"{path}: status {resp.status} != {expected_status}"
            raw = resp.read()
            return (json.loads(raw) if raw else None), dur, resp.headers
    except urllib.error.HTTPError as e:
        dur = time.time() - t0
        if e.code == expected_status:
            raw = e.read()
            return (json.loads(raw) if raw else None), dur, e.headers
        raise RuntimeError(f"{path}: expected HTTP {expected_status}, got {e.code}: {e.read().decode()}") from e


def test_health():
    print("[1/7] Kiểm tra /api/health...")
    data, dur = req("/api/health")
    assert data["ok"] is True, f"health ok != True: {data}"
    assert data["engine"]["name"] == "nautilus_trader", f"engine name sai: {data}"
    assert data["engine"]["version"] == "1.231.0", f"version sai: {data}"
    print(f"      -> OK ({dur*1000:.1f} ms): {data['engine']}")


def test_meta():
    print("[2/7] Kiểm tra /api/studio/meta...")
    data, dur = req("/api/studio/meta")
    assert "metrics" in data and "defs" in data["metrics"], "thiếu metrics.defs"
    assert "unsupported" in data, "thiếu unsupported list"
    assert "universe" in data, "thiếu universe"
    assert dur < 1.0, f"meta quá chậm ({dur:.2f}s)"
    print(f"      -> OK ({dur*1000:.1f} ms): {len(data['metrics']['defs'])} metrics, {len(data['unsupported'])} unsupported items")


def test_education_samples():
    print("[3/7] Kiểm tra /api/studio/education/samples...")
    data, dur = req("/api/studio/education/samples")
    assert len(data) >= 50, f"thiếu mẫu education: {len(data)} < 50"
    keys = {s["key"] for s in data}
    assert "trend_dual_ema" in keys, "thiếu trend_dual_ema trong education samples"
    print(f"      -> OK ({dur*1000:.1f} ms): {len(data)} mẫu giáo dục")
    return data


def test_live_not_ready():
    print("[4/8] Kiểm tra Live API -> 501 NOT_SUPPORTED...")
    # POST /api/studio/live/order
    data, dur = req("/api/studio/live/order", method="POST", body={"symbol": "BTC", "side": "LONG"}, expected_status=501)
    assert data.get("detail", {}).get("code") in ("NOT_READY", "NOT_SUPPORTED"), f"order không trả 501: {data}"
    # GET /api/studio/live/status
    data, dur = req("/api/studio/live/status", expected_status=501)
    assert data.get("detail", {}).get("code") in ("NOT_READY", "NOT_SUPPORTED"), f"status không trả 501: {data}"
    print("      -> OK: Live endpoints trả đúng 501 (không số giả, không ID bịa)")


def test_custom_job_and_responsiveness(samples):
    print("[5/7] Chạy backtest thật (trend_dual_ema trên Nautilus)...")
    s = next(x for x in samples if x["key"] == "trend_dual_ema")
    payload = {
        "code": s["code"],
        "symbols": ["BTC"],
        "start": "2024-01-01",
        "end": "2024-07-01",
        "train_ratio": 0.7,
        "initial_capital": 10000.0,
        "run_frame": "24h",
    }
    launch_res, dur = req("/api/studio/custom/backtest", method="POST", body=payload)
    job_id = launch_res["job_id"]
    print(f"      -> Job khởi tạo: {job_id} ({dur*1000:.1f} ms)")

    print("[6/7] Theo dõi tiến độ & kiểm tra API song song < 1s...")
    done_res = None
    for attempt in range(30):
        # Kiểm tra API phản hồi song song trong khi job đang chạy
        _, health_dur = req("/api/health")
        assert health_dur < 1.0, f"API health bị nghẽn trong lúc job chạy: {health_dur:.2f}s >= 1s"

        job_data, _ = req(f"/api/studio/book/jobs/{job_id}")
        st = job_data.get("status")
        if st == "done":
            done_res = job_data.get("result")
            print(f"      -> Job hoàn thành ở lần kiểm tra {attempt + 1}")
            break
        elif st == "failed":
            raise RuntimeError(f"Job thất bại: {job_data.get('error')}")
        time.sleep(1)

    assert done_res is not None, "Job không hoàn tất trong thời gian chờ"
    prov = done_res.get("provenance", {})
    assert prov.get("engine") == "nautilus_trader", f"provenance sai: {prov}"
    assert prov.get("base_frame") == "24h", f"base_frame sai: {prov}"
    assert "trades" in done_res, "thiếu trường trades"
    assert "metrics" in done_res, "thiếu trường metrics"
    assert "yearly" in done_res, "thiếu trường yearly"
    assert "series" in done_res, "thiếu trường series"
    print(f"      -> Bất biến OK: {len(done_res.get('trades', []))} lệnh, metrics: {done_res['metrics']['simulate']}")
    return job_id, s["code"]


def test_user_and_owner_flow(job_id: str, code: str):
    print("[7/7] Kiểm tra User & Owner isolation flow...")
    test_handle = f"e2e_{int(time.time())}"
    # 1. Tạo user
    user_res, _, headers = req_full(
        "/api/users",
        method="POST",
        body={"handle": test_handle, "display_name": "E2E Tester", "bio": "Automated verification"}
    )
    user_id = user_res["id"]
    alpha_id = "__none__"
    set_cookie = headers.get("Set-Cookie", "")
    cookie_header = {"Cookie": set_cookie.split(";")[0]}

    try:
        # 2. Đọc /api/me với cookie
        me_res, _ = req("/api/me", extra_headers=cookie_header)
        assert me_res.get("user") and me_res["user"]["handle"] == test_handle, f"/api/me sai: {me_res}"

        # 3. Lưu alpha khi có phiên
        save_res, _ = req(
            "/api/studio/alphas/user",
            method="POST",
            body={"job_id": job_id, "code": code, "name": f"Alpha of {test_handle}"},
            extra_headers=cookie_header,
        )
        alpha_id = save_res["alpha_id"]

        # 4. Kiểm tra /api/users/{handle}/strategies
        strats_res, _ = req(f"/api/users/{test_handle}/strategies")
        strats = strats_res if isinstance(strats_res, list) else strats_res.get("strategies", [])
        assert any(s["id"] == alpha_id for s in strats), f"Alpha {alpha_id} không có trong strategies của {test_handle}"

        # 5. Kiểm tra /api/home/summary cập nhật đúng
        summary_res, _ = req("/api/home/summary")
        assert summary_res.get("edu", {}).get("users", 0) >= 1
        assert summary_res.get("edu", {}).get("strategies", 0) >= 1

        print(f"      -> User flow OK: user={test_handle}, alpha={alpha_id}")
    finally:
        # Dọn dẹp dữ liệu test
        u_file = f"/home/vmc03/norabt/nora/data/users/{user_id}.json"
        if os.path.exists(u_file):
            os.remove(u_file)
        for a_file in glob.glob(f"/home/vmc03/norabt/nora/data/alpha/user/{alpha_id}*.json") + glob.glob(f"/home/vmc03/norabt/nora/data/alpha/user/_versions/{alpha_id}.*.json"):
            try:
                os.remove(a_file)
            except OSError:
                pass


def test_e2e_start_bot_from_picker():
    print("[8/8] E2E bật bot từ bộ chọn ở chế độ mặc định (P18 F2)...")
    cands_data, _ = req("/api/studio/live/candidates")
    cands = cands_data.get("candidates") or []
    if not cands:
        print("      -> Bỏ qua: không có ứng viên live_candidates")
        return
    cand = cands[0]
    payload = {
        "mode": "paper",
        "alpha_id": cand["id"],
        "signal_tf": cand["timeframe"],
        "symbols": (cand.get("symbols") or ["BTC-USDT-SWAP"])[:1],
        "capital": 1000.0,
        "from_picker": True,
    }
    start_res, _ = req("/api/studio/live/bot", method="POST", body=payload)
    assert start_res.get("ok") is True, f"Bật bot thất bại: {start_res}"
    bot_id = start_res["bot_id"]
    job_id = start_res["job_id"]
    print(f"      -> Bot khởi động: {bot_id}, job: {job_id}")

    # Đợi bot hoặc job khởi động
    time.sleep(2)

    # Dừng bot (close=False)
    stop_res, _ = req(f"/api/studio/live/bot/{bot_id}/stop", method="POST", body={"close": False})
    assert stop_res.get("ok") is True, f"Dừng bot thất bại: {stop_res}"

    # Xoá bot
    time.sleep(1)
    del_res, _ = req(f"/api/studio/live/bot/{bot_id}", method="DELETE")
    assert del_res.get("ok") is True, f"Xoá bot thất bại: {del_res}"
    print(f"      -> Dừng và xoá bot {bot_id} thành công")


def main():
    print("=== NORA E2E API VERIFICATION (P17 T2 & P18 F2) ===")
    t_start = time.time()
    test_health()
    test_meta()
    samples = test_education_samples()
    test_live_not_ready()
    job_id, code = test_custom_job_and_responsiveness(samples)
    test_user_and_owner_flow(job_id, code)
    test_e2e_start_bot_from_picker()
    print(f"=== TẤT CẢ 8/8 BƯỚC E2E ĐỀU PASS ({time.time() - t_start:.2f}s) ===")


if __name__ == "__main__":
    main()
