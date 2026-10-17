"""E2E Verification Script for Education Flow (P17 T3).

Luồng kiểm tra trọn vẹn:
1. Khách (chưa đăng nhập) -> GET /api/edu/samples/visible -> show_samples = True (1 mẫu).
2. Tạo user mới -> set cookie nora_uid -> GET /api/edu/samples/visible -> show_samples = True (0 chiến lược).
3. Chạy backtest cho mẫu -> lưu alpha -> GET /api/edu/samples/visible -> show_samples = False.
4. GET /api/edu/market -> user mới xuất hiện trong danh sách và n_strategies = 1.
5. Fork chiến lược của trend_hunter -> POST /api/edu/strategies/{alpha_id}/fork -> draft hợp lệ.
6. Dọn dẹp sạch sẽ dữ liệu test (alpha file, user file).
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


def req_full(path: str, method: str = "GET", body: Any = None, expected_status: int = 200, extra_headers: Optional[Dict[str, str]] = None) -> Tuple[Any, float, Any]:
    t0 = time.time()
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
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


def req(path: str, method: str = "GET", body: Any = None, expected_status: int = 200, extra_headers: Optional[Dict[str, str]] = None) -> Any:
    body_res, _, _ = req_full(path, method, body, expected_status, extra_headers)
    return body_res


def main():
    print("=== BẮT ĐẦU E2E TEST CHO EDUCATION (T3) ===")

    # 1. Khách xem samples visible
    res_guest = req("/api/edu/samples/visible")
    assert res_guest.get("show_samples") is True, f"Khách phải thấy mẫu: {res_guest}"
    assert len(res_guest.get("samples", [])) == 1, f"Khách phải thấy đúng 1 mẫu: {res_guest}"
    print("1. [PASS] Khách xem visible samples thành công (show_samples = True, 1 mẫu)")

    # 2. Tạo user mới và kiểm tra cookie
    test_handle = f"e2e_edu_{os.urandom(3).hex()}"
    res_user, _, headers = req_full("/api/users", method="POST", body={"handle": test_handle, "display_name": "E2E Học Viên", "bio": "Test User"}, expected_status=200)
    new_user = res_user
    assert new_user and new_user.get("id"), f"Không tạo được user: {res_user}"
    user_id = new_user["id"]
    
    # Lấy cookie nora_uid
    cookie_str = headers.get("Set-Cookie", "")
    nora_cookie = ""
    for part in cookie_str.split(";"):
        if "nora_uid=" in part:
            nora_cookie = part.strip()
            break
    assert nora_cookie, f"Thiếu cookie nora_uid trong Set-Cookie: {cookie_str}"
    auth_header = {"Cookie": nora_cookie}
    print(f"2. [PASS] Tạo user mới @{test_handle} và lấy cookie: {nora_cookie}")

    # Kiểm tra visible samples khi vừa tạo (chưa có chiến lược) -> vẫn True
    res_new_user = req("/api/edu/samples/visible", extra_headers=auth_header)
    assert res_new_user.get("show_samples") is True, f"User mới chưa lưu chiến lược phải thấy mẫu: {res_new_user}"
    print("2b. [PASS] User mới chưa có chiến lược vẫn thấy mẫu (show_samples = True)")

    # 3. Chạy backtest cho mẫu trend_dual_ema
    samples_res = req("/api/studio/education/samples")
    sample_item = samples_res[0] if isinstance(samples_res, list) else samples_res["samples"][0]
    sample_code = sample_item["code"]
    sample_name = sample_item["name"]

    job_req_body = {
        "code": sample_code,
        "symbols": ["BTC@perp"],
        "start": "2024-01-01",
        "end": "2024-01-15",
        "train_ratio": 0.7,
        "initial_capital": 10000.0,
    }
    job_submit = req("/api/studio/custom/backtest", method="POST", body=job_req_body)
    job_id = job_submit.get("job_id") or job_submit.get("id")
    assert job_id, f"Không nhận được job_id: {job_submit}"

    # Đợi job hoàn thành
    t_start = time.time()
    job_done = None
    while time.time() - t_start < 60:
        st = req(f"/api/studio/book/jobs/{job_id}?lite=1")
        if st.get("status") in ("done", "failed"):
            job_done = st
            break
        time.sleep(1)

    assert job_done and job_done.get("status") == "done", f"Job chạy thất bại: {job_done}"
    print(f"3. [PASS] Backtest mẫu thành công ({time.time() - t_start:.1f}s)")

    # 4. Lưu alpha vào tài khoản user mới
    save_body = {
        "job_id": job_id,
        "code": sample_code,
        "name": f"Chiến lược đầu tay của {test_handle}",
        "note": "E2E Test Note",
        "source": "education",
    }
    save_res = req("/api/studio/alphas/user", method="POST", body=save_body, extra_headers=auth_header)
    alpha_id = save_res.get("alpha_id")
    assert alpha_id, f"Không lưu được alpha: {save_res}"
    print(f"4. [PASS] Lưu chiến lược đầu tay thành công (alpha_id: {alpha_id})")

    # 5. Kiểm tra luật ẩn mẫu sau khi đã lưu
    res_after_save = req("/api/edu/samples/visible", extra_headers=auth_header)
    assert res_after_save.get("show_samples") is False, f"Đã lưu alpha thì mẫu phải bị ẩn: {res_after_save}"
    assert res_after_save.get("samples") == [], f"Danh sách mẫu phải rỗng: {res_after_save}"
    print("5. [PASS] Mẫu đã được ẩn tự động ngay sau khi lưu chiến lược đầu tay")

    # 6. Kiểm tra Market có user mới
    market_res = req("/api/edu/market")
    user_row = next((u for u in market_res.get("users", []) if u.get("handle") == test_handle), None)
    assert user_row is not None, f"Không tìm thấy @{test_handle} trên market"
    assert user_row.get("n_strategies") == 1, f"Số chiến lược phải là 1: {user_row}"
    print(f"6. [PASS] User mới hiển thị trên Market với 1 chiến lược")

    # 7. Fork chiến lược của trend_hunter
    th_strategies = req("/api/edu/users/trend_hunter")
    th_alphas = th_strategies.get("strategies", [])
    assert th_alphas, "Không tìm thấy chiến lược của trend_hunter"
    target_alpha_id = th_alphas[0]["id"]

    fork_res = req(f"/api/edu/strategies/{target_alpha_id}/fork", method="POST", extra_headers=auth_header)
    assert fork_res.get("ok") is True, f"Fork thất bại: {fork_res}"
    draft = fork_res.get("draft", {})
    assert draft.get("code"), "Draft fork phải có code"
    assert draft.get("forked_from", {}).get("alpha_id") == target_alpha_id
    assert draft.get("forked_from", {}).get("owner_handle") == "trend_hunter"
    print(f"7. [PASS] Fork chiến lược của @trend_hunter thành công vào draft")

    # 8. Dọn dẹp dữ liệu test
    print("8. Dọn dẹp dữ liệu test...")
    # Xoá alpha file
    alpha_file = os.path.join("data", "alpha", "user", f"{alpha_id}.json")
    if os.path.isfile(alpha_file):
        os.remove(alpha_file)
    for vf in glob.glob(os.path.join("data", "alpha", "user", "_versions", f"{alpha_id}.*")):
        try:
            os.remove(vf)
        except OSError:
            pass

    # Xoá user file
    user_file = os.path.join("data", "users", f"{user_id}.json")
    if os.path.isfile(user_file):
        os.remove(user_file)

    print("=== TẤT CẢ CÁC BƯỚC E2E EDUCATION (T3) ĐÃ THÀNH CÔNG RỰC RỠ! ===")


if __name__ == "__main__":
    main()
