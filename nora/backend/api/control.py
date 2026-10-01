"""Điều khiển backtest — chạy, dừng, xem log, theo dõi tiến độ.

Gửi lệnh qua Redis đúng như portal cũ làm:
    publish 'lab_order'  →  lab_server  →  node EXP  →  manage.py lab_account <id>
Nhờ vậy không phải chạy tiến trình riêng, và mọi giới hạn tài nguyên
(taskset, nice) do node áp dụng vẫn giữ nguyên.
"""
import json
import os
import subprocess
import time
import uuid

import redis

from ..db import fetch_one, cursor

REDIS = dict(
    host=os.getenv("NORA_REDIS_HOST", "127.0.0.1"),
    port=int(os.getenv("NORA_REDIS_PORT", "6379")),
)
NODE = os.getenv("NORA_LAB_NODE", "EXP")
TIMEOUT = 25

# Thời điểm bấm chạy từng lần chạy. Giữa lúc gửi lệnh và lúc tiến trình thật
# hiện ra trên máy có một khoảng trống vài chục giây; nếu không nhớ mốc này thì
# tiến độ sẽ nhìn thấy số liệu cũ còn nguyên và kết luận nhầm là "đã chạy xong".
_KHOI_DONG = {}
KHOI_DONG_TOI_DA = 90  # giây


def _call(controller: str, method: str, payload: dict, timeout: int = TIMEOUT):
    """Gửi một lệnh và chờ phản hồi từ node."""
    r = redis.Redis(**REDIS)
    ps = r.pubsub()
    ps.subscribe("lab_order_result")
    time.sleep(0.3)  # chờ kênh sẵn sàng

    oid = f"nora_{uuid.uuid4().hex[:12]}"
    msg = {
        "order_socket_id": oid,
        "order_socket_server": NODE,
        "order_socket_controller": controller,
        "order_socket_method": method,
        **payload,
    }
    r.publish("lab_order", json.dumps(msg))

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            m = ps.get_message(timeout=1)
            if not m or m.get("type") != "message":
                continue
            try:
                data = json.loads(m["data"])
            except Exception:
                continue
            if data.get("order_socket_id") == oid:
                return data.get("response") or {"result": False, "message": "Không có nội dung trả về"}
    finally:
        try:
            ps.close()
            r.close()
        except Exception:
            pass
    return {"result": False, "message": f"Node không phản hồi sau {timeout} giây"}


def node_status():
    """Node xử lý backtest có sẵn sàng không."""
    row = fetch_one(
        "SELECT lab_node_name AS name, lab_node_status AS status, lab_node_ip AS ip "
        "FROM lab_node WHERE lab_node_name = %s",
        (NODE,),
    )
    ok = bool(row) and row.get("status") in ("LOCAL", "CONNECTED")
    return {"node": NODE, "ready": ok, **(row or {})}


def preflight(run_id: int):
    """Kiểm tra trước khi chạy — chặn các lỗi từng làm backtest hỏng âm thầm."""
    issues = []
    with cursor() as c:
        c.execute(
            """SELECT lab_account_id AS id, lab_account_name AS name,
                      lab_account_db AS dataset, lab_account_running AS running,
                      lab_account_server AS node, lab_account_balance AS balance
               FROM lab_account WHERE lab_account_id = %s""",
            (run_id,),
        )
        acc = c.fetchone()
        if not acc:
            return {"ok": False, "issues": [{"muc": "loi", "text": "Không tìm thấy lần chạy"}]}

        if not acc.get("node"):
            issues.append({"muc": "loi",
                           "text": "Chưa gán node xử lý — bấm chạy sẽ báo không tìm thấy máy chủ"})
        if not acc.get("dataset"):
            issues.append({"muc": "loi", "text": "Chưa chọn bộ dữ liệu nến"})

        c.execute(
            """SELECT COUNT(*) AS tong,
                      SUM(lab_campaign_active_budget IS NULL OR lab_campaign_active_budget = 0) AS thieu_von,
                      SUM(lab_campaign_strategy IS NULL) AS thieu_chien_luoc
               FROM lab_campaigns WHERE lab_campaign_account = %s""",
            (run_id,),
        )
        cp = c.fetchone() or {}
        if not cp.get("tong"):
            issues.append({"muc": "loi", "text": "Chưa có coin nào được gắn vào lần chạy"})
        if cp.get("thieu_von"):
            issues.append({"muc": "loi",
                           "text": f"{cp['thieu_von']} coin chưa đặt ngân sách hoạt động — "
                                   f"backtest sẽ dừng ngay sau vài giây mà không báo lỗi"})
        if cp.get("thieu_chien_luoc"):
            issues.append({"muc": "loi", "text": f"{cp['thieu_chien_luoc']} coin chưa gán chiến lược"})

        c.execute(
            "SELECT COUNT(*) AS n FROM lab_results WHERE lab_result_account = %s", (run_id,)
        )
        old = (c.fetchone() or {}).get("n", 0)
        if old:
            issues.append({"muc": "luu_y",
                           "text": f"Chạy lại sẽ xoá {old:,} lệnh của kết quả cũ"})
        if acc.get("running"):
            issues.append({"muc": "luu_y",
                           "text": "Lần chạy này đang chạy — bấm chạy sẽ dừng tiến trình hiện tại"})

    ns = node_status()
    if not ns["ready"]:
        issues.append({"muc": "loi",
                       "text": f"Node {ns['node']} chưa sẵn sàng (trạng thái {ns.get('status') or 'không rõ'})"})

    return {
        "ok": not any(i["muc"] == "loi" for i in issues),
        "issues": issues,
        "account": acc,
        "node": ns,
    }


def start(run_id: int):
    """Chạy backtest. Node sẽ tự dừng tiến trình cũ của cùng lần chạy."""
    pre = preflight(run_id)
    if not pre["ok"]:
        return {"result": False,
                "message": "; ".join(i["text"] for i in pre["issues"] if i["muc"] == "loi"),
                "preflight": pre}

    res = _call("account", "start", {"id": run_id})
    if res.get("result"):
        _KHOI_DONG[run_id] = time.time()
        with cursor() as c:
            c.execute("UPDATE lab_account SET lab_account_running = 1 WHERE lab_account_id = %s",
                      (run_id,))
            c.connection.commit()
    return res


def stop(run_id: int):
    _KHOI_DONG.pop(run_id, None)
    res = _call("account", "stop", {"id": run_id})
    with cursor() as c:
        c.execute("UPDATE lab_account SET lab_account_running = 0 WHERE lab_account_id = %s",
                  (run_id,))
        c.connection.commit()
    return res


def log(run_id: int, tail: int = 120):
    res = _call("account", "getLog", {"id": run_id})
    text = res.get("data") if isinstance(res, dict) else None
    if isinstance(text, str):
        lines = text.strip().split("\n")
        res["data"] = "\n".join(lines[-tail:])
        res["so_dong"] = len(lines)
    return res


def is_process_alive_pattern(mau: str) -> bool:
    """Có tiến trình nào khớp mẫu này đang chạy không."""
    try:
        r = subprocess.run(["pgrep", "-f", mau], capture_output=True, text=True, timeout=5)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def is_process_alive(run_id: int) -> bool:
    """Tiến trình backtest có thật sự đang chạy không.

    Cờ lab_account_running trong DB chỉ đáng tin khi engine kết thúc bình thường.
    Nếu tiến trình bị giết hoặc chết giữa chừng, cờ vẫn nằm ở 1 mãi mãi —
    nên phải đối chiếu với tiến trình thật trên máy.
    """
    try:
        r = subprocess.run(
            ["pgrep", "-f", f"lab_account {run_id} "],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _parse_status(raw: str):
    """Đọc chuỗi tiến độ của campaign.

    Engine ghi HAI THỨ TỰ KHÁC NHAU:
      - đang chạy : "{tổng},{đã_xử_lý}"   ví dụ 855438,100000
      - đã xong   : "{đã_xử_lý},{tổng}"   ví dụ 855438,855438
    Nên không thể tin vị trí. Lấy số nhỏ làm đã-xử-lý, số lớn làm tổng —
    đúng cho cả hai trường hợp, và bằng nhau khi đã chạy hết.
    """
    parts = str(raw or "").split(",")
    if len(parts) != 2:
        return None, None
    try:
        a, b = int(float(parts[0])), int(float(parts[1]))
    except ValueError:
        return None, None
    return min(a, b), max(a, b)


def progress(run_id: int):
    """Tiến độ thật của một lần chạy."""
    with cursor() as c:
        c.execute(
            """SELECT lab_account_running AS running, lab_account_log AS log
               FROM lab_account WHERE lab_account_id = %s""",
            (run_id,),
        )
        acc = c.fetchone() or {}
        c.execute(
            "SELECT COUNT(*) AS n FROM lab_results WHERE lab_result_account = %s", (run_id,)
        )
        trades = (c.fetchone() or {}).get("n", 0)
        c.execute(
            """SELECT lab_campaign_status AS st, lab_campaign_runtime AS rt
               FROM lab_campaigns WHERE lab_campaign_account = %s""",
            (run_id,),
        )
        rows = c.fetchall()

    # Lấy campaign đi xa nhất — các campaign chạy cùng nhịp nên đây là tiến độ chung
    done = total = 0
    runtime = None
    for row in rows:
        d, t = _parse_status(row.get("st"))
        if d is None:
            continue
        if t > total or (t == total and d > done):
            done, total = d, t
        if row.get("rt"):
            runtime = max(runtime or 0, int(row["rt"]))

    flag = bool(acc.get("running"))
    alive = is_process_alive(run_id)
    vua_bam = time.time() - _KHOI_DONG.get(run_id, 0) < KHOI_DONG_TOI_DA

    if alive:
        _KHOI_DONG.pop(run_id, None)
        state = "running"
    elif vua_bam:
        # Vừa bấm chạy, tiến trình chưa kịp hiện — chưa được kết luận điều gì
        state = "starting"
    else:
        state = "done" if done and done >= total else "stopped"
        # Cờ trong DB lệch với thực tế -> sửa lại cho đúng
        if flag:
            state = "done" if (total and done >= total) else "interrupted"
            with cursor() as c:
                c.execute(
                    "UPDATE lab_account SET lab_account_running = 0 WHERE lab_account_id = %s",
                    (run_id,),
                )
                c.connection.commit()

    return {
        "running": alive,
        "busy": alive or state == "starting",
        "state": state,          # starting | running | done | stopped | interrupted
        "db_flag": flag,
        "trades": trades,
        "processed": done,
        "total": total,
        "percent": round(100 * done / total, 2) if total else None,
        "runtime": runtime,      # mốc thời gian nến đang xử lý
        "log_line": acc.get("log"),
    }


def running_ids() -> set:
    """Tập id đang thật sự có tiến trình chạy trên máy.

    Một lần gọi pgrep cho cả danh sách, thay vì hỏi từng dòng — bảng danh sách
    có tới vài trăm lần chạy nên không thể kiểm tra riêng lẻ.
    """
    try:
        r = subprocess.run(
            ["pgrep", "-af", "lab_account "], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return set()
    ids = set()
    for dong in r.stdout.splitlines():
        phan = dong.split("lab_account ", 1)
        if len(phan) != 2:
            continue
        so = phan[1].split()[0] if phan[1].split() else ""
        if so.isdigit():
            ids.add(int(so))
    return ids


# ---------------------------------------------------------------- phiên đào alpha

def opt_start(oid: int):
    """Chạy một phiên quét tham số. Cùng đường đi Redis như chạy backtest."""
    res = _call("optimization", "start", {"id": oid})
    if res.get("result"):
        _KHOI_DONG[f"opt{oid}"] = time.time()
    return res


def opt_stop(oid: int):
    _KHOI_DONG.pop(f"opt{oid}", None)
    return _call("optimization", "stop", {"id": oid})


def opt_log(oid: int, tail: int = 120):
    res = _call("optimization", "getLog", {"id": oid})
    text = res.get("data") if isinstance(res, dict) else None
    if isinstance(text, str):
        dong = text.strip().split("\n")
        res["data"] = "\n".join(dong[-tail:])
        res["so_dong"] = len(dong)
    return res


def opt_progress(oid: int):
    """Tiến độ một phiên quét — đếm theo số tổ hợp tham số đã chạy xong."""
    with cursor() as c:
        c.execute(
            """SELECT lab_opt_processed AS pr, lab_opt_log AS log, lab_opt_thread AS workers
               FROM lab_optimization WHERE lab_opt_id = %s""",
            (oid,),
        )
        opt = c.fetchone() or {}
        c.execute(
            """SELECT COUNT(*) AS tong, SUM(lab_opt_result_done = 1) AS xong
               FROM lab_opt_result WHERE lab_opt_result_optimization = %s""",
            (oid,),
        )
        kq = c.fetchone() or {}

    done, total = _parse_status(opt.get("pr"))
    # bảng kết quả là nguồn đáng tin hơn khi có dữ liệu
    if kq.get("tong"):
        total = int(kq["tong"])
        done = int(kq.get("xong") or 0)

    alive = is_process_alive_pattern(f"lab_optimization {oid} ")
    vua_bam = time.time() - _KHOI_DONG.get(f"opt{oid}", 0) < KHOI_DONG_TOI_DA
    if alive:
        _KHOI_DONG.pop(f"opt{oid}", None)
        state = "running"
    elif vua_bam:
        state = "starting"
    elif total and done and done >= total:
        state = "done"
    else:
        state = "stopped"

    return {
        "running": alive,
        "busy": alive or state == "starting",
        "state": state,
        "processed": done or 0,
        "total": total or 0,
        "percent": round(100 * done / total, 2) if (total and done is not None) else None,
        "workers": opt.get("workers"),
        "log_line": opt.get("log"),
    }
