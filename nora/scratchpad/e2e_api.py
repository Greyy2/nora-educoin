"""E2E Verification Script for Nora API on NautilusTrader (P15 R6).

Kiểm tra:
1. /api/health -> 200 {ok, engine: {name: 'nautilus_trader', version: '1.231.0'}}
2. /api/studio/meta -> 200, ETag, unsupported, metrics.defs
3. /api/studio/education/samples -> 200, đủ 50 mẫu
4. /api/live/* -> 501 NOT_READY (không trả id bịa)
5. Custom job thật: POST /api/studio/custom/backtest với mẫu trend_dual_ema
6. API phản hồi < 1s trong khi job chạy
7. Bất biến kết quả: provenance thật, metrics thật, trades thật
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("NORA_API_URL", "http://127.0.0.1:18010")


def req(path, method="GET", body=None, expected_status=200):
    t0 = time.time()
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
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


def test_health():
    print("[1/6] Kiểm tra /api/health...")
    data, dur = req("/api/health")
    assert data["ok"] is True, f"health ok != True: {data}"
    assert data["engine"]["name"] == "nautilus_trader", f"engine name sai: {data}"
    assert data["engine"]["version"] == "1.231.0", f"version sai: {data}"
    print(f"      -> OK ({dur*1000:.1f} ms): {data['engine']}")


def test_meta():
    print("[2/6] Kiểm tra /api/studio/meta...")
    data, dur = req("/api/studio/meta")
    assert "metrics" in data and "defs" in data["metrics"], "thiếu metrics.defs"
    assert "unsupported" in data, "thiếu unsupported list"
    assert "universe" in data, "thiếu universe"
    assert dur < 1.0, f"meta quá chậm ({dur:.2f}s)"
    print(f"      -> OK ({dur*1000:.1f} ms): {len(data['metrics']['defs'])} metrics, {len(data['unsupported'])} unsupported items")


def test_education_samples():
    print("[3/6] Kiểm tra /api/studio/education/samples...")
    data, dur = req("/api/studio/education/samples")
    assert len(data) >= 50, f"thiếu mẫu education: {len(data)} < 50"
    keys = {s["key"] for s in data}
    assert "trend_dual_ema" in keys, "thiếu trend_dual_ema trong education samples"
    print(f"      -> OK ({dur*1000:.1f} ms): {len(data)} mẫu giáo dục")
    return data


def test_live_not_ready():
    print("[4/6] Kiểm tra Live API -> 501 NOT_READY...")
    # POST /api/studio/live/order
    data, dur = req("/api/studio/live/order", method="POST", body={"symbol": "BTC", "side": "LONG"}, expected_status=501)
    assert data.get("detail", {}).get("code") == "NOT_READY", f"order không trả NOT_READY: {data}"
    # GET /api/studio/live/bot
    data, dur = req("/api/studio/live/bot", expected_status=501)
    assert data.get("detail", {}).get("code") == "NOT_READY", f"bot không trả NOT_READY: {data}"
    print("      -> OK: Live endpoints trả đúng 501 NOT_READY (không số giả, không ID bịa)")


def test_custom_job_and_responsiveness(samples):
    print("[5/6] Chạy backtest thật (trend_dual_ema trên Nautilus)...")
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

    print("[6/6] Theo dõi tiến độ & kiểm tra API song song < 1s...")
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


def main():
    print("=== NORA E2E API VERIFICATION (P15 R6) ===")
    t_start = time.time()
    test_health()
    test_meta()
    samples = test_education_samples()
    test_live_not_ready()
    test_custom_job_and_responsiveness(samples)
    print(f"=== TẤT CẢ 6/6 BƯỚC E2E ĐỀU PASS ({time.time() - t_start:.2f}s) ===")


if __name__ == "__main__":
    main()
