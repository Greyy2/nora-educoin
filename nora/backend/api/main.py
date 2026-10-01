"""Nora Backtest — API thống kê.

Đọc dữ liệu backtest từ MySQL của hệ thống cũ (chỉ đọc, không ghi),
tổng hợp thành 6 tầng thống kê cho giao diện mới.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import asyncio

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.db import cursor, fetch_all, fetch_one   # noqa: E402
from backend.stats import queries as q               # noqa: E402
from backend.stats import metrics as mt              # noqa: E402
from backend import control as ctl                   # noqa: E402

app = FastAPI(title="Nora Backtest API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from backend.api.routers import engine, meta, studio, research
    app.include_router(engine.router)
    app.include_router(meta.router)
    app.include_router(studio.router)
    app.include_router(research.router)
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"Warning: Could not load V2 routers: {e}")


MONITOR_DIR = Path(os.environ.get("NORA_COIN_MONITOR_DIR") or Path(__file__).resolve().parents[3] / "coin_monitor")
CHART_DIR = MONITOR_DIR / "frontend" / "build" / "plot"
PYBIN = sys.executable


# ---------------------------------------------------------------- danh sách


def _clean_symbol(raw, fallback="SOL"):
    clean = re.sub(r"[^A-Za-z0-9]+", "", str(raw or fallback)).upper()
    for sfx in ("USDT", "USDC", "PERP", "USD"):
        if clean.endswith(sfx) and len(clean) > len(sfx):
            clean = clean[:-len(sfx)]
    clean = clean.replace("1000", "").replace("BACKTEST", "").strip()
    return clean or fallback


def _fnum(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _metric_summary_for_runs(run_ids):
    ids = [int(x) for x in run_ids if x]
    if not ids:
        return {}
    ph = ",".join(["%s"] * len(ids))
    stats_rows = fetch_all(
        f"""SELECT lab_result_account AS a,
                   COUNT(*) AS trades,
                   ROUND(SUM(lab_result_realpnl), 2) AS pnl,
                   ROUND(100.0 * SUM(lab_result_realpnl > 0) / COUNT(*), 1) AS winrate,
                   ROUND(SUM(CASE WHEN lab_result_realpnl > 0 THEN lab_result_realpnl ELSE 0 END), 2) AS gross_profit,
                   ROUND(ABS(SUM(CASE WHEN lab_result_realpnl < 0 THEN lab_result_realpnl ELSE 0 END)), 2) AS gross_loss,
                   MIN(lab_result_symbol) AS primary_symbol
            FROM lab_results
            WHERE lab_result_account IN ({ph}) GROUP BY lab_result_account""",
        ids,
    )
    out = {}
    for s in stats_rows:
        trades = int(s.get("trades") or 0)
        pnl = _fnum(s.get("pnl"))
        winrate = _fnum(s.get("winrate")) if trades else None
        gross_profit = _fnum(s.get("gross_profit"))
        gross_loss = _fnum(s.get("gross_loss"))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_profit is not None and gross_loss and gross_loss > 0 else None
        out[int(s["a"])] = {
            "trades": trades,
            "pnl": pnl,
            "net": pnl,
            "winrate": winrate,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit": gross_profit,
            "profit_factor": profit_factor,
            "symbol": _clean_symbol(s.get("primary_symbol")),
            "has_result": trades > 0,
        }
    return out


def _processing(status, progress_pct=None, message=None):
    label = {
        "running": "Đang chạy",
        "completed": "Đã chạy xong",
        "done": "Đã chạy xong",
        "failed": "Lỗi",
        "interrupted": "Dừng giữa chừng",
        "stopped": "Chưa chạy",
        "pending": "Đang chờ",
    }.get(status or "", status or "—")
    return {"status": status, "label": label, "progress_pct": progress_pct, "message": message}


@app.get("/api/runs")
def list_runs(group: str = None, q_: str = Query(None, alias="q"), limit: int = 50):
    """Danh sách lần chạy backtest. Luôn có LIMIT — không bao giờ kéo cả bảng."""
    where, params = ["1=1"], []
    if group:
        where.append("lab_account_group = %s")
        params.append(group)
    if q_:
        where.append("(lab_account_name LIKE %s OR lab_account_id = %s)")
        params += [f"%{q_}%", q_ if q_.isdigit() else -1]
    rows = fetch_all(
        f"""SELECT lab_account_id AS id, lab_account_name AS name,
                   lab_account_group AS `group`, lab_account_db AS dataset,
                   lab_account_balance AS balance, lab_account_running AS running,
                   lab_account_margin_type AS margin_type, lab_account_note AS note
            FROM lab_account WHERE {' AND '.join(where)}
            ORDER BY lab_account_id DESC LIMIT %s""",
        params + [limit],
    )
    if rows:
        stats_map = _metric_summary_for_runs([r["id"] for r in rows])
        dang_chay = ctl.running_ids()
        for r in rows:
            st = stats_map.get(int(r["id"]), {})
            running = 1 if r["id"] in dang_chay else 0
            status = "running" if running else ("done" if st.get("has_result") else "stopped")
            pnl_val = st.get("pnl")
            init_bal = _fnum(r.get("balance"))
            note = str(r.get("note") or "")
            alpha_id = note.split(":")[-1] if note.startswith("nora:alpha:") else None
            r.update({
                "result_type": "backtest",
                "run_id": r["id"],
                "params": None,
                "param_label": f"Alpha {alpha_id}" if alpha_id else (r.get("dataset") or r.get("group")),
                "trades": st.get("trades"),
                "pnl": pnl_val,
                "net": pnl_val,
                "winrate": st.get("winrate"),
                "win_rate": st.get("winrate"),
                "mdd_pct": None,
                "sharpe": None,
                "profit_factor": st.get("profit_factor"),
                "profit": st.get("profit"),
                "gross_profit": st.get("gross_profit"),
                "gross_loss": st.get("gross_loss"),
                "symbol": st.get("symbol") or _clean_symbol(r.get("name") or r.get("dataset")),
                "return_pct": round(pnl_val / init_bal * 100.0, 2) if pnl_val is not None and init_bal and init_bal > 0 else None,
                "running": running,
                "status": status,
                "processing": _processing(status),
                "has_result": bool(st.get("has_result")),
            })
    return {"rows": rows}


@app.get("/api/groups")
def list_groups():
    return {
        "rows": fetch_all(
            """SELECT lab_account_group AS name, COUNT(*) AS n FROM lab_account
               WHERE lab_account_group IS NOT NULL AND lab_account_group <> ''
               GROUP BY lab_account_group ORDER BY n DESC LIMIT 50"""
        )
    }


# ---------------------------------------------------------------- thống kê

@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    info = q.run_info(run_id)
    if not info:
        raise HTTPException(404, "Không tìm thấy lần chạy này")
    return info


@app.get("/api/runs/{run_id}/overview")
def get_overview(run_id: int):
    r = q.overview(run_id)
    if not r:
        raise HTTPException(404, "Lần chạy chưa có kết quả")
    return r


@app.get("/api/runs/{run_id}/by-flow")
def get_by_flow(run_id: int):
    return {"rows": q.by_flow(run_id)}


@app.get("/api/runs/{run_id}/behavior")
def get_behavior(run_id: int):
    return q.behavior(run_id)


@app.get("/api/runs/{run_id}/by-symbol")
def get_by_symbol(run_id: int, limit: int = 100):
    return {"rows": q.by_symbol(run_id, limit)}


@app.get("/api/runs/{run_id}/timeline")
def get_timeline(run_id: int):
    return {"rows": q.timeline(run_id)}


@app.get("/api/runs/{run_id}/equity")
def get_equity(run_id: int, points: int = 2000):
    return q.equity(run_id, points)


@app.get("/api/runs/{run_id}/trades")
def get_trades(run_id: int, page: int = 1, size: int = 50,
               symbol: str = None, flow: str = None, only: str = None):
    return q.trades(run_id, page, min(size, 200), symbol, flow, only)


@app.get("/api/runs/{run_id}/insights")
def get_insights(run_id: int):
    return {"rows": q.insights(run_id)}






# ---------------------------------------------------------------- điều khiển chạy

@app.get("/api/node")
def get_node():
    return ctl.node_status()


@app.get("/api/runs/{run_id}/preflight")
def get_preflight(run_id: int):
    """Kiểm tra cấu hình trước khi chạy."""
    return ctl.preflight(run_id)


@app.post("/api/runs/{run_id}/start")
def post_start(run_id: int):
    r = ctl.start(run_id)
    if not r.get("result"):
        raise HTTPException(400, r.get("message") or "Không chạy được")
    return r


@app.post("/api/runs/{run_id}/stop")
def post_stop(run_id: int):
    return ctl.stop(run_id)


@app.get("/api/runs/{run_id}/log")
def get_log(run_id: int, tail: int = 120):
    return ctl.log(run_id, tail)


@app.get("/api/runs/{run_id}/progress")
def get_progress(run_id: int):
    return ctl.progress(run_id)



# ---------------------------------------------------------------- kênh thời gian thực

@app.websocket("/ws/runs/{run_id}/progress")
async def ws_progress(ws: WebSocket, run_id: int):
    """Đẩy tiến độ theo thời gian thực trong lúc backtest chạy.

    Nhịp gửi tự co giãn: đang chạy thì 2 giây một lần, đã dừng thì 10 giây —
    vừa mượt khi cần, vừa không hỏi cơ sở dữ liệu vô ích khi rảnh.
    Chỉ gửi khi số liệu thay đổi, trừ nhịp giữ kết nối mỗi 30 giây.
    """
    await ws.accept()
    truoc = None
    lan_gui_cuoi = 0.0
    try:
        while True:
            # truy vấn chạy ở luồng phụ để không chặn vòng lặp sự kiện
            data = await asyncio.to_thread(ctl.progress, run_id)
            now = asyncio.get_event_loop().time()
            moc = (data["processed"], data["trades"], data["state"])

            if moc != truoc or now - lan_gui_cuoi > 30:
                await ws.send_json(data)
                truoc = moc
                lan_gui_cuoi = now

            # backtest xong thì gửi lần cuối rồi đóng
            if data["state"] in ("done", "interrupted") and not data["running"]:
                await ws.send_json({**data, "final": True})
                break

            await asyncio.sleep(2 if data.get("busy") else 10)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"error": str(e)[:200]})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.websocket("/ws/runs/{run_id}/log")
async def ws_log(ws: WebSocket, run_id: int, tail: int = 60):
    """Đẩy log chạy theo thời gian thực."""
    await ws.accept()
    truoc = None
    try:
        while True:
            r = await asyncio.to_thread(ctl.log, run_id, tail)
            text = r.get("data") if isinstance(r, dict) else None
            if text and text != truoc:
                await ws.send_json({"log": text})
                truoc = text
            p = await asyncio.to_thread(ctl.progress, run_id)
            if not p.get("busy"):
                await ws.send_json({"log": text, "final": True})
                break
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass

# ---------------------------------------------- alpha mới sinh ra từ phiên đào

def ten_khong_trung(ten: str) -> str:
    """Tên lần chạy là khoá duy nhất trong bảng — trùng là engine báo lỗi 500.

    Thêm hậu tố -2, -3… cho tới khi trống, thay vì ném lỗi vào mặt người dùng
    chỉ vì họ dựng lại đúng cái alpha đó lần thứ hai.
    """
    ten = (ten or "").strip()[:190] or "Lần chạy Nora"
    thu = ten
    for i in range(2, 60):
        if not fetch_one("SELECT 1 AS x FROM lab_account WHERE lab_account_name = %s", (thu,)):
            return thu
        thu = f"{ten}-{i}"
    return f"{ten}-{int(time.time())}"


DAU_ALPHA = "nora:alpha:"     # ghi vào lab_account_note để biết run nào dựng từ alpha nào
NHOM_ALPHA = "Nora Alpha"


def _da_dung_run():
    """Bản đồ mã kết quả -> mã lần chạy đã dựng từ nó."""
    rows = fetch_all(
        "SELECT lab_account_id AS id, lab_account_note AS note FROM lab_account "
        "WHERE lab_account_note LIKE %s", (DAU_ALPHA + "%",))
    ra = {}
    for r in rows:
        try:
            ra[int(str(r["note"]).split(":")[-1])] = r["id"]
        except ValueError:
            pass
    return ra


@app.get("/api/base/alpha-moi")
def alpha_moi(opt: int = None, limit: int = 60, sort: str = "balance"):
    """Alpha do phiên đào sinh ra — mỗi tổ hợp thắng cuộc là một chiến lược mới.

    Chúng chỉ tồn tại dưới dạng ảnh chụp trong lab_opt_result, chưa có lần chạy
    thật nào, nên trạng thái mặc định là "chưa chạy".
    """
    where, params = ["r.lab_opt_result_done = 1"], []
    if opt:
        where.append("r.lab_opt_result_optimization = %s")
        params.append(opt)
    order = ("r.lab_opt_result_id DESC" if sort == "moi"
             else "r.lab_opt_result_balance DESC")
    rows = fetch_all(
        f"""SELECT r.lab_opt_result_id              AS id,
                   r.lab_opt_result_optimization    AS opt_id,
                   o.lab_opt_name                   AS opt_name,
                   o.lab_opt_account                AS base_run,
                   ROUND(r.lab_opt_result_balance, 2)      AS balance,
                   ROUND(r.lab_opt_result_invest_max, 2)   AS invest_max,
                   ROUND(r.lab_opt_result_unrelize_max, 2) AS unrealize_max,
                   r.lab_opt_result_total_position  AS positions,
                   r.lab_opt_result_total_long      AS longs,
                   r.lab_opt_result_total_short     AS shorts,
                   r.lab_opt_result_total_takeprofit AS takeprofit,
                   r.lab_opt_result_total_stoploss   AS stoploss,
                   r.lab_opt_result_params          AS params
            FROM lab_opt_result r
            LEFT JOIN lab_optimization o ON o.lab_opt_id = r.lab_opt_result_optimization
            WHERE {' AND '.join(where)}
            ORDER BY {order} LIMIT %s""",
        params + [limit],
    )
    da = _da_dung_run()
    for r in rows:
        r["run_id"] = da.get(r["id"])
        r["state"] = "da_dung" if r["run_id"] else "chua_chay"
        r["params"] = str(r.get("params") or "")[:400]
    return {"rows": rows}


# Hai khoá này do bộ nạp chiến lược tự gắn lại khi chạy (name = khoá của luồng,
# strategy = mã chiến lược), nên phải bỏ ra khi ghi ngược vào bảng.
KHOA_TU_GAN = ("name", "strategy")

# Chín trường cấp chiến lược nằm ở cột riêng của bảng lab_strategies.
TRUONG_CHIEN_LUOC = ("takeprofit", "stoploss", "baseprofit", "step_profit", "back_profit",
                     "baseprofit_baseon", "timelife", "interval", "margin")


def _tach_alpha(st_raw):
    """Tách ảnh chụp chiến lược thành nội dung + các trường cấp chiến lược.

    Ảnh chụp có dạng {"<mã>": {"<mã>--<tên luồng>": {luồng đã dựng xong}}}, tức
    là kết quả SAU khi bộ nạp gốc (processLabChildStrategy) đã thay tham số,
    gắn name/strategy và đổ các trường cấp chiến lược xuống luồng.

    Muốn chạy lại y hệt thì phải ghi ngược sao cho bộ nạp gốc dựng ra đúng
    luồng đó. Cách chắc chắn nhất là giữ NGUYÊN mọi khoá của luồng trong nội
    dung — kể cả takeprofit/margin… — vì bộ nạp chỉ đổ giá trị từ cột xuống khi
    luồng chưa có khoá đó. Chỉ bỏ name/strategy vì bộ nạp tự gắn lại.

    Whitelist theo kiểu chỉ giữ type/match/stop là sai: dữ liệu thật còn có
    allow_negative_price_rate, max_open_trades, using_matched_price…
    """
    st = json.loads(st_raw or "{}")
    noi_dung, truong, ten = {}, {}, None
    for _, luongs in st.items():
        for khoa, luong in (luongs or {}).items():
            ten_luong = luong.get("name") or khoa.split("--", 1)[-1]
            noi_dung[ten_luong] = {k: v for k, v in luong.items() if k not in KHOA_TU_GAN}
            if not truong:
                ten = ten_luong
                truong = {k: luong.get(k) for k in TRUONG_CHIEN_LUOC}
    return noi_dung, truong, ten


def _co_bo_chua(st_raw):
    """Ảnh chụp có phải của một bộ chứa nhiều chiến lược con không."""
    try:
        st = json.loads(st_raw or "{}")
    except Exception:
        return False
    return any("container" in (f or {}) for luongs in st.values() for f in (luongs or {}).values())


@app.get("/api/datasets")
def datasets():
    """Các bộ dữ liệu nến đang được dùng, để chọn khi dựng lần chạy."""
    return {"rows": [r["name"] for r in fetch_all(
        "SELECT lab_account_db AS name, COUNT(*) AS n FROM lab_account "
        "WHERE lab_account_db IS NOT NULL AND lab_account_db <> '' "
        "GROUP BY lab_account_db ORDER BY n DESC")]}


@app.get("/api/base/alpha-moi/{rid}")
def alpha_chi_tiet(rid: int):
    """Xem trước một alpha trước khi dựng thành lần chạy."""
    r = fetch_one(
        """SELECT lab_opt_result_id AS id, lab_opt_result_optimization AS opt_id,
                  lab_opt_result_strategy AS st, lab_opt_result_account AS ac,
                  lab_opt_result_campaign AS ca, ROUND(lab_opt_result_balance, 2) AS balance
           FROM lab_opt_result WHERE lab_opt_result_id = %s""", (rid,))
    if not r:
        raise HTTPException(404, "Không tìm thấy alpha")
    noi_dung, truong, ten = _tach_alpha(r["st"])
    try:
        ac = json.loads(r["ac"] or "{}")
    except Exception:
        ac = {}
    try:
        ca = json.loads(r["ca"] or "[]")
    except Exception:
        ca = []
    goc = fetch_one("SELECT lab_account_db AS dataset FROM lab_account WHERE lab_account_id = "
                    "(SELECT lab_opt_account FROM lab_optimization WHERE lab_opt_id = %s)",
                    (r["opt_id"],)) or {}
    phien = fetch_one("SELECT lab_opt_data_leng AS dl FROM lab_optimization WHERE lab_opt_id = %s",
                      (r["opt_id"],)) or {}
    return {
        "id": rid,
        "opt_id": r["opt_id"],
        "balance": r["balance"],
        "ten_goi_y": f"ALPHA-{r['opt_id']}-{rid}" + (f"-{ten}" if ten else ""),
        "luong": list(noi_dung.keys()),
        "truong": truong,
        "so_coin": len(ca),
        "coin": [c.get("lab_campaign_symbol") for c in ca[:12]],
        "von": ac.get("lab_account_margin_balance") or ac.get("lab_account_balance"),
        "margin_type": ac.get("lab_account_margin_type") or "CROSS",
        "data_type": ac["lab_account_data_type"] if "lab_account_data_type" in ac else "1m",
        "data_len": phien.get("dl") or 1,
        "compound": ac.get("lab_account_compound"),
        "reserve": ac.get("lab_account_reserve"),
        "dataset_goi_y": goc.get("dataset") or ac.get("lab_account_db"),
        "run_id": _da_dung_run().get(rid),
    }


@app.post("/api/base/alpha-moi/{rid}/tao-run")
def tao_run_tu_alpha(rid: int, body: dict = Body(default={})):
    """Dựng một alpha thành lần chạy thật để backtest được.

    Chỉ thêm bản ghi mới (chiến lược, lần chạy, danh sách coin) — không đụng
    vào bất kỳ dòng nào của hệ thống cũ.
    """
    da = _da_dung_run()
    if rid in da and not body.get("cho_trung"):
        return {"result": True, "run_id": da[rid], "da_co": True,
                "message": f"Alpha này đã được dựng thành lần chạy {da[rid]}"}

    r = fetch_one(
        """SELECT lab_opt_result_optimization AS opt_id, lab_opt_result_strategy AS st,
                  lab_opt_result_account AS ac, lab_opt_result_campaign AS ca
           FROM lab_opt_result WHERE lab_opt_result_id = %s""", (rid,))
    if not r:
        raise HTTPException(404, "Không tìm thấy alpha")

    if _co_bo_chua(r["st"]):
        raise HTTPException(
            400, "Alpha này sinh từ bộ chứa nhiều chiến lược con — dựng lại cần tạo cả "
                 "bảng liên kết bộ chứa, chưa hỗ trợ")
    noi_dung, truong, ten_luong = _tach_alpha(r["st"])
    if not noi_dung:
        raise HTTPException(400, "Ảnh chụp chiến lược trống, không dựng được")

    ac = json.loads(r["ac"] or "{}")
    ca = json.loads(r["ca"] or "[]")
    if not ca:
        raise HTTPException(400, "Alpha này không kèm danh sách coin nào")

    ten = ten_khong_trung(body.get("name") or f"ALPHA-{r['opt_id']}-{rid}")
    dataset = (body.get("dataset") or ac.get("lab_account_db") or "").strip()
    if not dataset:
        goc = fetch_one("SELECT lab_account_db AS d FROM lab_account WHERE lab_account_id = "
                        "(SELECT lab_opt_account FROM lab_optimization WHERE lab_opt_id = %s)",
                        (r["opt_id"],)) or {}
        dataset = goc.get("d") or ""
    if not dataset:
        raise HTTPException(400, "Chưa chọn bộ dữ liệu nến")
    von = float(body.get("balance") or ac.get("lab_account_margin_balance")
                or ac.get("lab_account_balance") or 10000)

    # Khối dữ liệu phải lấy đúng của phiên đào; chạy khối khác là ra kết quả khác.
    phien = fetch_one("SELECT lab_opt_data_leng AS dl FROM lab_optimization WHERE lab_opt_id = %s",
                      (r["opt_id"],)) or {}
    data_len = int(body.get("data_len") or phien.get("dl") or 1)

    with cursor() as c:
        c.execute(
            """INSERT INTO lab_strategies
                 (lab_strategy_name, lab_strategy_content, lab_strategy_takeprofit,
                  lab_strategy_stoploss, lab_strategy_baseprofit, lab_strategy_stepprofit,
                  lab_strategy_backprofit, lab_strategy_baseprofit_baseon,
                  lab_strategy_timelife, lab_strategy_interval, lab_strategy_margin,
                  lab_strategy_note, lab_strategy_group)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (ten, json.dumps(noi_dung, ensure_ascii=False),
             truong.get("takeprofit"), truong.get("stoploss"), truong.get("baseprofit"),
             truong.get("step_profit"), truong.get("back_profit"),
             truong.get("baseprofit_baseon"), truong.get("timelife"),
             truong.get("interval"), truong.get("margin"),
             f"Sinh từ phiên đào {r['opt_id']}, kết quả {rid}", NHOM_ALPHA))
        c.connection.commit()
        c.execute("SELECT LAST_INSERT_ID() AS id")
        sid = (c.fetchone() or {}).get("id")

        # Chép nguyên các thiết lập ảnh hưởng tới cách vào lệnh (dồn lãi, vốn dự
        # phòng, kiểu ký quỹ, nhảy nến…) — sai một cái là kết quả chạy lại lệch.
        c.execute(
            """INSERT INTO lab_account
                 (lab_account_name, lab_account_balance, lab_account_margin_balance,
                  lab_account_reserve, lab_account_compound, lab_account_margin_type,
                  lab_account_track_balance, lab_account_running, lab_account_sync,
                  lab_account_leap, lab_account_db, lab_account_data_type,
                  lab_account_data_length, lab_account_server, lab_account_note,
                  lab_account_group)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (ten, von, von,
             ac.get("lab_account_reserve"), ac.get("lab_account_compound"),
             ac.get("lab_account_margin_type") or "CROSS",
             # Giữ nguyên cả giá trị rỗng: ảnh chụp ghi sao thì chạy lại phải vậy,
             # thay rỗng bằng mặc định là đã đổi cách engine tính vốn.
             ac["lab_account_track_balance"] if "lab_account_track_balance" in ac else 1,
             ac["lab_account_sync"] if "lab_account_sync" in ac else 1,
             ac["lab_account_leap"] if "lab_account_leap" in ac else 0,
             dataset,
             # Kiểu dữ liệu quyết định engine khớp lệnh theo nến 1 phút hay không.
             # Ảnh chụp cũ để rỗng thì phải giữ rỗng, ép thành "1m" là đổi cách khớp.
             body.get("data_type") if body.get("data_type") is not None
             else (ac["lab_account_data_type"] if "lab_account_data_type" in ac else "1m"),
             data_len, ctl.NODE, f"{DAU_ALPHA}{rid}", NHOM_ALPHA))
        c.connection.commit()
        c.execute("SELECT LAST_INSERT_ID() AS id")
        run_id = (c.fetchone() or {}).get("id")

        hang = []
        for cp in ca:
            sym = cp.get("lab_campaign_symbol")
            if not sym:
                continue
            hang.append((
                f"{ten}-{sym}", sym,
                cp.get("lab_campaign_start"), cp.get("lab_campaign_stop"),
                cp.get("lab_campaign_params"),
                cp.get("lab_campaign_side") or "BOTH", sid, run_id,
                cp.get("lab_campaign_budget") or von,
                cp.get("lab_campaign_reserve"),
                cp.get("lab_campaign_compound"),
                cp.get("lab_campaign_money"),
                cp.get("lab_campaign_active_budget") or 100,
                cp.get("lab_campaign_priority") or 1,
            ))
        c.executemany(
            """INSERT INTO lab_campaigns
                 (lab_campaign_name, lab_campaign_symbol, lab_campaign_start,
                  lab_campaign_stop, lab_campaign_params, lab_campaign_side,
                  lab_campaign_strategy, lab_campaign_account, lab_campaign_budget,
                  lab_campaign_reserve, lab_campaign_compound, lab_campaign_money,
                  lab_campaign_active_budget, lab_campaign_priority,
                  lab_campaign_status, lab_campaign_running)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '0,0', 0)""",
            hang)
        c.connection.commit()

    return {"result": True, "run_id": run_id, "strategy_id": sid,
            "so_coin": len(hang), "dataset": dataset,
            "message": f"Đã dựng lần chạy {run_id} với {len(hang)} coin"}


@app.get("/api/runs/{run_id}/chien-luoc")
def chien_luoc_cua_run(run_id: int):
    """Chiến lược mà lần chạy này dùng — để nhìn kết quả là biết ngay chạy cái gì."""
    rows = fetch_all(
        """SELECT lab_campaign_strategy AS sid, COUNT(*) AS so_coin
           FROM lab_campaigns
           WHERE lab_campaign_account = %s AND lab_campaign_strategy IS NOT NULL
           GROUP BY lab_campaign_strategy""", (run_id,))
    ra = []
    for r in rows:
        st = fetch_one(
            """SELECT lab_strategy_id AS id, lab_strategy_name AS name,
                      lab_strategy_group AS `group`, lab_strategy_content AS content,
                      lab_strategy_container AS is_container,
                      lab_strategy_takeprofit AS takeprofit, lab_strategy_stoploss AS stoploss,
                      lab_strategy_baseprofit AS baseprofit, lab_strategy_stepprofit AS step_profit,
                      lab_strategy_backprofit AS back_profit,
                      lab_strategy_baseprofit_baseon AS baseprofit_baseon,
                      lab_strategy_timelife AS timelife, lab_strategy_interval AS `interval`,
                      lab_strategy_margin AS margin, lab_strategy_note AS note
               FROM lab_strategies WHERE lab_strategy_id = %s""", (r["sid"],))
        if not st:
            continue
        st["so_coin"] = r["so_coin"]
        ra.append(st)
    return {"rows": ra}


# ------------------------------------------- chạy lại một backtest đã chạy xong

# Khoá thuần cấu trúc, sửa vào là hỏng chiến lược
KHOA_CAU_TRUC = {"type", "enter_price", "name", "baseprofit_baseon",
                 "symbol", "logic", "strategy"}


def _la_so(v):
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except ValueError:
            return False
    return False


def _quet_num(nut, duong, nhan, ra, nhom, khoa=None):
    """Đi khắp cây JSON, nhặt mọi thứ chỉnh được kèm đường dẫn tới nó.

    Không chỉ con số: khung thời gian và tên chỉ báo cũng là tham số người ta
    muốn quét (đổi EMA 9 sang EMA 21, đổi khung 4h sang 1h), nên lấy luôn và
    đánh dấu kiểu để giao diện hiện đúng ô chọn.
    """
    if isinstance(nut, dict):
        for k, v in nut.items():
            if k in KHOA_CAU_TRUC:
                continue
            _quet_num(v, duong + [k], f"{nhan}.{k}" if nhan else k, ra, nhom, k)
    elif isinstance(nut, list):
        for i, v in enumerate(nut):
            # phần tử giữa của phép so sánh là toán tử, bỏ qua
            if isinstance(v, str) and v in (">", "<", "=", ">=", "<=", "!="):
                continue
            _quet_num(v, duong + [i], f"{nhan}[{i}]", ra, nhom, khoa)
    elif khoa == "frame" and isinstance(nut, str):
        ra.append({"duong_dan": duong, "nhan": nhan, "gia_tri": nut, "nhom": nhom,
                   "kieu": "khung", "chon": KHUNG, "y_nghia": "khung thời gian"})
    elif khoa == "column" and isinstance(nut, str):
        ra.append({"duong_dan": duong, "nhan": nhan, "gia_tri": nut, "nhom": nhom,
                   "kieu": "chi_bao", "y_nghia": doc_chi_bao(nut) or "chỉ báo"})
    elif _la_so(nut):
        ra.append({"duong_dan": duong, "nhan": nhan, "gia_tri": nut, "nhom": nhom,
                   "kieu": "so", "y_nghia": NGHIA_KHOA.get(khoa)})


# ---------------------------------- tham số dạng dễ hiểu, gom theo khái niệm

RE_KELTNER = re.compile(r"^(k(?:up|lo))(\d+)(?:_(\d+))?$")
RE_CHU_KY = re.compile(r"^((?:price_)?(?:ema|wma|sma|rsi|atr|macd)[a-z_]*?)(\d+)$")


def _mo_ta_ve(v):
    """Mô tả một vế của phép so sánh bằng lời."""
    if isinstance(v, dict):
        if v.get("type") == "event":
            return NGHIA_KHOA.get(v.get("column"), f"lệnh.{v.get('column')}")
        if v.get("column"):
            ten = doc_chi_bao(v.get("column")) or v.get("column")
            khung = v.get("frame")
            ra = f"{ten}" + (f" khung {khung}" if khung else "")
            if v.get("percent"):
                ra += f" ×{v['percent']}%"
            if v.get("subtract"):
                ra += f" trừ {doc_chi_bao(v['subtract'].get('column')) or v['subtract'].get('column')}"
            return ra
        if v.get("type") in ("min", "max"):
            return f"{v['type']}(…)"
        if v.get("type") == "calculate":
            return "biểu thức tính"
    return str(v)


def _di_dieu_kien(nut, duong, ra, nhom):
    """Nhặt các ngưỡng số trong điều kiện, kèm mô tả vế trái để biết đang so cái gì."""
    if isinstance(nut, list):
        if (len(nut) == 3 and isinstance(nut[1], str)
                and nut[1] in (">", "<", "=", ">=", "<=", "!=")):
            trai, phep, phai = nut
            if _la_so(phai) and not isinstance(phai, bool):
                ra.append({
                    "nhan": f"{_mo_ta_ve(trai)} {phep} …",
                    "y_nghia": "ngưỡng của phép so sánh này",
                    "kieu": "so", "gia_tri": phai, "so_cho": 1,
                    "ap_dung": [{"duong_dan": duong + [2], "mau": "{}"}],
                    "nhom": nhom,
                })
            return
        for i, v in enumerate(nut):
            _di_dieu_kien(v, duong + [i], ra, nhom)


def _thu_thap_chuoi(nut, duong, khoa, ra):
    """Gom mọi vị trí của frame và column trong cây."""
    if isinstance(nut, dict):
        for k, v in nut.items():
            _thu_thap_chuoi(v, duong + [k], k, ra)
    elif isinstance(nut, list):
        for i, v in enumerate(nut):
            _thu_thap_chuoi(v, duong + [i], khoa, ra)
    elif isinstance(nut, str) and khoa in ("frame", "column"):
        ra.append((khoa, nut, duong))


def tham_so_de_hieu(sid, name, content, truong):
    """Dịch chiến lược thành một nhúm núm vặn có tên gọi con người hiểu được.

    Bảng tham số thô liệt kê từng đường dẫn JSON (condition[0][3][0].numbers[2]),
    đúng nhưng không ai biết vặn cái nào. Ở đây gom theo khái niệm: một dòng
    "chu kỳ Keltner" sửa hết 17 chỗ đang dùng kup17_05/klo17_05, một dòng
    "khung 4h" đổi cả 30 chỗ — đó mới là cách người ta nghĩ khi chỉnh chiến lược.
    """
    ra = []

    # 1. quản trị vốn và lệnh
    for k in TRUONG_CHIEN_LUOC:
        if k == "baseprofit_baseon" or truong.get(k) is None:
            continue
        ra.append({
            "nhan": NGHIA_KHOA.get(k, k), "ma": f"truong:{k}",
            "y_nghia": f"trường {k} của chiến lược", "kieu": "so",
            "gia_tri": truong[k], "so_cho": 1,
            "ap_dung": [{"duong_dan": ["__truong__", k], "mau": "{}"}],
            "nhom": "Quản trị vốn và lệnh",
        })

    # 2. chỉ báo và khung thời gian — gom theo giá trị đang dùng
    chuoi = []
    _thu_thap_chuoi(content, [], None, chuoi)

    khung = {}
    kel_ky, kel_hs, chu_ky = {}, {}, {}
    for khoa, gt, duong in chuoi:
        if khoa == "frame":
            khung.setdefault(gt, []).append(duong)
            continue
        # Chu kỳ và hệ số nằm chung một tên cột (kup17_05), hai núm cùng sửa một
        # chỗ. Nên không gửi "chuỗi thay thế sẵn" mà gửi phần cần đổi, để giao
        # diện ghép lại từ tên gốc — vặn cả hai núm vẫn ra kup21_1, không đè nhau.
        m = RE_KELTNER.match(gt)
        if m:
            ky, hs = m.group(2), m.group(3)
            kel_ky.setdefault(ky, []).append((duong, gt, "chu_ky"))
            if hs:
                kel_hs.setdefault(hs, []).append((duong, gt, "he_so"))
            continue
        m = RE_CHU_KY.match(gt)
        if m:
            chu_ky.setdefault((m.group(1), m.group(2)), []).append((duong, gt, "chu_ky"))

    for k, ds in sorted(khung.items(), key=lambda x: -len(x[1])):
        ra.append({
            "nhan": f"Khung thời gian {k}", "ma": f"khung:{k}",
            "y_nghia": f"đổi ở đây là đổi cả {len(ds)} chỗ đang dùng khung {k}",
            "kieu": "khung", "chon": KHUNG, "gia_tri": k, "so_cho": len(ds),
            "ap_dung": [{"duong_dan": d, "mau": "{}"} for d in ds],
            "nhom": "Khung thời gian",
        })

    for ky, ds in sorted(kel_ky.items(), key=lambda x: -len(x[1])):
        ra.append({
            "nhan": "Keltner · chu kỳ EMA", "ma": f"kel_ky:{ky}",
            "y_nghia": "số nến để tính đường giữa của dải Keltner",
            "kieu": "so", "gia_tri": int(ky), "so_cho": len(ds),
            "ap_dung": [{"duong_dan": d, "goc": g, "phan": p} for d, g, p in ds],
            "nhom": "Chỉ báo",
        })
    for hs, ds in sorted(kel_hs.items(), key=lambda x: -len(x[1])):
        # Tên cột viết hệ số không có dấu chấm: kup17_05 nghĩa là 0.5, kup29_1 là 1.
        # Hiện ra cho người dùng thì phải trả lại dấu chấm.
        hien = f"0.{hs[1:]}" if len(hs) > 1 and hs.startswith("0") else hs
        ra.append({
            "nhan": "Keltner · hệ số ATR", "ma": f"kel_hs:{hs}",
            "y_nghia": "dải rộng bao nhiêu lần ATR; số càng lớn dải càng xa giá",
            "kieu": "so", "bien_doi": "he_so", "gia_tri": hien, "so_cho": len(ds),
            "ap_dung": [{"duong_dan": d, "goc": g, "phan": p} for d, g, p in ds],
            "nhom": "Chỉ báo",
        })
    for (goc, ky), ds in sorted(chu_ky.items(), key=lambda x: -len(x[1])):
        ra.append({
            "nhan": f"{doc_chi_bao(goc + ky) or goc} · chu kỳ", "ma": f"ck:{goc}{ky}",
            "y_nghia": f"số nến của {goc}",
            "kieu": "so", "gia_tri": int(ky), "so_cho": len(ds),
            "ap_dung": [{"duong_dan": d, "goc": g, "phan": p} for d, g, p in ds],
            "nhom": "Chỉ báo",
        })

    # 3. từng bậc vào lệnh và các ngưỡng trong điều kiện
    for ten_luong, luong in (content or {}).items():
        if not isinstance(luong, dict) or not luong.get("type"):
            continue
        for i, bac in enumerate(luong.get("match") or []):
            nhom = f"{ten_luong} · bậc {i}"
            for k in ("enter_package", "margin", "stoploss", "baseprofit",
                      "enter_step", "enter_back"):
                v = bac.get(k)
                if _la_so(v):
                    ra.append({
                        "nhan": NGHIA_KHOA.get(k, k), "ma": f"{ten_luong}:{i}:{k}",
                        "y_nghia": f"áp cho bậc {i} của nhánh {ten_luong}",
                        "kieu": "bool" if isinstance(v, bool) else "so",
                        "gia_tri": v, "so_cho": 1,
                        "ap_dung": [{"duong_dan": [ten_luong, "match", i, k], "mau": "{}"}],
                        "nhom": nhom,
                    })
            _di_dieu_kien(bac.get("condition"), [ten_luong, "match", i, "condition"], ra, nhom)
        if luong.get("stop"):
            _di_dieu_kien(luong["stop"], [ten_luong, "stop"], ra,
                          f"{ten_luong} · điều kiện thoát")

    for i, x in enumerate(ra):
        x.setdefault("ma", f"n{i}")
        x["strategy"] = sid
    return ra


def _num_chien_luoc(sid):
    """Danh sách con số chỉnh được của một chiến lược, gom theo luồng và bậc."""
    st = fetch_one(
        """SELECT lab_strategy_id AS id, lab_strategy_name AS name, lab_strategy_group AS `group`,
                  lab_strategy_content AS content, lab_strategy_takeprofit AS takeprofit,
                  lab_strategy_stoploss AS stoploss, lab_strategy_baseprofit AS baseprofit,
                  lab_strategy_stepprofit AS step_profit, lab_strategy_backprofit AS back_profit,
                  lab_strategy_baseprofit_baseon AS baseprofit_baseon,
                  lab_strategy_timelife AS timelife, lab_strategy_interval AS `interval`,
                  lab_strategy_margin AS margin, lab_strategy_container AS container
           FROM lab_strategies WHERE lab_strategy_id = %s""", (sid,))
    if not st:
        return None

    knobs = []
    for k in TRUONG_CHIEN_LUOC:
        if st.get(k) is not None and k != "baseprofit_baseon":
            knobs.append({"duong_dan": ["__truong__", k], "nhan": k,
                          "gia_tri": st[k], "nhom": "Chiến lược",
                          "kieu": "so", "y_nghia": NGHIA_KHOA.get(k)})

    try:
        content = json.loads(st.get("content") or "{}")
    except Exception:
        content = {}

    for ten_luong, luong in content.items():
        if not isinstance(luong, dict):
            _quet_num(luong, [ten_luong], ten_luong, knobs, "Khoá dùng chung")
            continue
        for i, bac in enumerate(luong.get("match") or []):
            _quet_num(bac, [ten_luong, "match", i], "", knobs,
                      f"{ten_luong} · bậc {i}")
        if "stop" in luong:
            _quet_num(luong["stop"], [ten_luong, "stop"], "", knobs,
                      f"{ten_luong} · điều kiện thoát")
        for k, v in luong.items():
            if k in ("match", "stop", "type"):
                continue
            _quet_num(v, [ten_luong, k], k, knobs, f"{ten_luong} · khác")

    truong_cl = {k: st.get(k) for k in TRUONG_CHIEN_LUOC}
    return {"id": st["id"], "name": st["name"], "group": st["group"],
            "container": bool(st.get("container")), "tham_so": knobs,
            "de_hieu": tham_so_de_hieu(st["id"], st["name"], content, truong_cl)}


@app.get("/api/runs/{run_id}/tham-so")
def tham_so_chien_luoc(run_id: int):
    """Các con số của chiến lược mà lần chạy này đang dùng."""
    sids = [r["s"] for r in fetch_all(
        "SELECT DISTINCT lab_campaign_strategy AS s FROM lab_campaigns "
        "WHERE lab_campaign_account = %s AND lab_campaign_strategy IS NOT NULL", (run_id,))]
    acc = fetch_one(
        """SELECT lab_account_name AS name, lab_account_db AS dataset,
                  lab_account_balance AS balance, lab_account_data_length AS data_len
           FROM lab_account WHERE lab_account_id = %s""", (run_id,)) or {}
    ds = [x for x in (_num_chien_luoc(s) for s in sids) if x]
    return {"run_id": run_id, "run": acc, "chien_luoc": ds,
            "so_lenh_cu": (fetch_one(
                "SELECT COUNT(*) AS n FROM lab_results WHERE lab_result_account = %s",
                (run_id,)) or {}).get("n", 0)}


def _dat_theo_duong(goc, duong, gia_tri):
    """Ghi một giá trị vào đúng vị trí trong cây JSON theo đường dẫn."""
    nut = goc
    for b in duong[:-1]:
        nut = nut[b]
    cu = nut[duong[-1]]
    # giữ nguyên kiểu dữ liệu cũ để engine đọc y như trước
    if isinstance(cu, bool):
        moi = str(gia_tri).lower() in ("1", "true", "yes")
    elif isinstance(cu, int) and not isinstance(cu, bool):
        moi = int(float(gia_tri))
    elif isinstance(cu, float):
        moi = float(gia_tri)
    else:
        moi = str(gia_tri)
    nut[duong[-1]] = moi
    return cu, moi


@app.post("/api/runs/{run_id}/chay-lai")
def chay_lai(run_id: int, body: dict = Body(default={})):
    """Chạy lại một backtest theo hai kiểu.

      nguyen        — dùng đúng chiến lược cũ, chạy đè lên kết quả cũ
      doi_tham_so   — đổi con số rồi sinh chiến lược mới và lần chạy mới,
                      đi đúng đường sinh alpha đã đối chiếu với engine gốc,
                      nên lần chạy cũ vẫn còn nguyên để so sánh
    """
    kieu = body.get("kieu") or "nguyen"
    cu = fetch_one(
        """SELECT lab_account_id AS id, lab_account_name AS name, lab_account_balance AS balance,
                  lab_account_margin_balance AS margin_balance, lab_account_reserve AS reserve,
                  lab_account_compound AS compound, lab_account_margin_type AS margin_type,
                  lab_account_track_balance AS track_balance, lab_account_sync AS sync,
                  lab_account_leap AS leap, lab_account_db AS db,
                  lab_account_data_type AS data_type, lab_account_data_length AS data_len,
                  lab_account_group AS `group`
           FROM lab_account WHERE lab_account_id = %s""", (run_id,))
    if not cu:
        raise HTTPException(404, "Không tìm thấy lần chạy")

    if kieu == "nguyen":
        return {**ctl.start(run_id), "run_id": run_id, "kieu": "nguyen"}

    sua = body.get("thay_doi") or []
    if not sua:
        raise HTTPException(400, "Chưa đổi con số nào — chọn kiểu giữ nguyên thì hơn")

    # gom thay đổi theo từng chiến lược
    theo_cl = {}
    for x in sua:
        theo_cl.setdefault(int(x["strategy"]), []).append(x)

    ten_moi = ten_khong_trung(body.get("name") or f"{cu['name']}-v2")
    dataset = (body.get("dataset") or cu["db"] or "").strip()
    if not dataset:
        raise HTTPException(400, "Chưa chọn bộ dữ liệu nến")

    doi_ma, nhat_ky = {}, []
    with cursor() as c:
        for sid, ds in theo_cl.items():
            st = fetch_one("SELECT * FROM lab_strategies WHERE lab_strategy_id = %s", (sid,))
            if not st:
                raise HTTPException(404, f"Không tìm thấy chiến lược {sid}")
            if st.get("lab_strategy_container"):
                raise HTTPException(400, "Chiến lược dạng bộ chứa chưa hỗ trợ đổi tham số")
            content = json.loads(st.get("lab_strategy_content") or "{}")
            truong = {k: st.get("lab_strategy_" + ("stepprofit" if k == "step_profit"
                                                   else "backprofit" if k == "back_profit" else k))
                      for k in TRUONG_CHIEN_LUOC}
            for x in ds:
                duong = x["duong_dan"]
                if duong and duong[0] == "__truong__":
                    k = duong[1]
                    cu_gt, moi_gt = truong.get(k), x["gia_tri"]
                    truong[k] = moi_gt
                else:
                    try:
                        cu_gt, moi_gt = _dat_theo_duong(content, duong, x["gia_tri"])
                    except Exception:
                        raise HTTPException(400, f"Đường dẫn không hợp lệ: {'/'.join(map(str, duong))}")
                nhat_ky.append({"strategy": sid, "duong_dan": duong,
                                "cu": cu_gt, "moi": moi_gt})

            c.execute(
                """INSERT INTO lab_strategies
                     (lab_strategy_name, lab_strategy_content, lab_strategy_takeprofit,
                      lab_strategy_stoploss, lab_strategy_baseprofit, lab_strategy_stepprofit,
                      lab_strategy_backprofit, lab_strategy_baseprofit_baseon,
                      lab_strategy_timelife, lab_strategy_interval, lab_strategy_margin,
                      lab_strategy_note, lab_strategy_group)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (f"{st['lab_strategy_name']}-v2", json.dumps(content, ensure_ascii=False),
                 truong.get("takeprofit"), truong.get("stoploss"), truong.get("baseprofit"),
                 truong.get("step_profit"), truong.get("back_profit"),
                 truong.get("baseprofit_baseon"), truong.get("timelife"),
                 truong.get("interval"), truong.get("margin"),
                 f"Đổi tham số từ chiến lược {sid}, lần chạy {run_id}", NHOM_ALPHA))
            c.connection.commit()
            c.execute("SELECT LAST_INSERT_ID() AS id")
            doi_ma[sid] = (c.fetchone() or {}).get("id")

        c.execute(
            """INSERT INTO lab_account
                 (lab_account_name, lab_account_balance, lab_account_margin_balance,
                  lab_account_reserve, lab_account_compound, lab_account_margin_type,
                  lab_account_track_balance, lab_account_running, lab_account_sync,
                  lab_account_leap, lab_account_db, lab_account_data_type,
                  lab_account_data_length, lab_account_server, lab_account_note,
                  lab_account_group)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (ten_moi, cu["balance"], cu["margin_balance"], cu["reserve"], cu["compound"],
             cu["margin_type"], cu["track_balance"], cu["sync"], cu["leap"],
             dataset, cu["data_type"], cu["data_len"], ctl.NODE,
             f"nora:chaylai:{run_id}", cu["group"] or NHOM_ALPHA))
        c.connection.commit()
        c.execute("SELECT LAST_INSERT_ID() AS id")
        run_moi = (c.fetchone() or {}).get("id")

        c.execute(
            """SELECT lab_campaign_name AS name, lab_campaign_symbol AS symbol,
                      lab_campaign_start AS start, lab_campaign_stop AS stop,
                      lab_campaign_params AS params, lab_campaign_side AS side,
                      lab_campaign_strategy AS strategy, lab_campaign_budget AS budget,
                      lab_campaign_reserve AS reserve, lab_campaign_compound AS compound,
                      lab_campaign_money AS money, lab_campaign_active_budget AS active_budget,
                      lab_campaign_priority AS priority
               FROM lab_campaigns WHERE lab_campaign_account = %s""", (run_id,))
        hang = [(
            f"{ten_moi}-{cp['symbol']}", cp["symbol"], cp["start"], cp["stop"], cp["params"],
            cp["side"], doi_ma.get(cp["strategy"], cp["strategy"]), run_moi,
            cp["budget"], cp["reserve"], cp["compound"], cp["money"],
            cp["active_budget"], cp["priority"],
        ) for cp in c.fetchall()]
        c.executemany(
            """INSERT INTO lab_campaigns
                 (lab_campaign_name, lab_campaign_symbol, lab_campaign_start,
                  lab_campaign_stop, lab_campaign_params, lab_campaign_side,
                  lab_campaign_strategy, lab_campaign_account, lab_campaign_budget,
                  lab_campaign_reserve, lab_campaign_compound, lab_campaign_money,
                  lab_campaign_active_budget, lab_campaign_priority,
                  lab_campaign_status, lab_campaign_running)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '0,0', 0)""",
            hang)
        c.connection.commit()

    return {"result": True, "kieu": "doi_tham_so", "run_id": run_moi,
            "chien_luoc_moi": doi_ma, "so_coin": len(hang), "thay_doi": nhat_ky,
            "message": f"Đã sinh lần chạy {run_moi} với {len(hang)} coin từ {len(doi_ma)} chiến lược mới"}


# ---------------------------------------------------------------- chỉ số nâng cao

@app.get("/api/dashboard")
def dashboard():
    """Tổng quan toàn hệ thống."""
    return mt.dashboard_summary()


@app.get("/api/runs/{run_id}/metrics")
def get_metrics(run_id: int):
    """Bộ chỉ số đầy đủ: MDD, Sharpe, Sortino, Calmar, Profit Factor, chuỗi thắng/thua."""
    r = mt.full_metrics_cached(run_id)
    if not r or not r.get("trades"):
        raise HTTPException(404, "Lần chạy chưa có kết quả")
    return r


@app.get("/api/runs/{run_id}/metrics-brief")
def get_metrics_brief(run_id: int):
    """Bản rút gọn — không kèm đường vốn, dùng cho bảng danh sách."""
    r = mt.full_metrics_cached(run_id)
    if not r or not r.get("trades"):
        raise HTTPException(404, "Lần chạy chưa có kết quả")
    r.pop("equity_daily", None)
    return r

# ---------------------------------------------------------------- chiến thuật

@app.get("/api/strategies")
def list_strategies(group: str = None, q_: str = Query(None, alias="q"), limit: int = 200):
    where, params = ["1=1"], []
    if group:
        where.append("lab_strategy_group = %s")
        params.append(group)
    if q_:
        where.append("lab_strategy_name LIKE %s")
        params.append(f"%{q_}%")
    rows = fetch_all(
        f"""SELECT lab_strategy_id AS id, lab_strategy_name AS name,
                   lab_strategy_group AS `group`, lab_strategy_container AS is_container,
                   lab_strategy_takeprofit AS takeprofit, lab_strategy_stoploss AS stoploss,
                   lab_strategy_margin AS margin, lab_strategy_timelife AS timelife,
                   CHAR_LENGTH(lab_strategy_content) AS content_size
            FROM lab_strategies WHERE {' AND '.join(where)}
            ORDER BY lab_strategy_id DESC LIMIT %s""",
        params + [limit],
    )
    return {"rows": rows}


@app.get("/api/strategies/{sid}")
def get_strategy(sid: int):
    row = fetch_one(
        """SELECT lab_strategy_id AS id, lab_strategy_name AS name,
                  lab_strategy_group AS `group`, lab_strategy_content AS content,
                  lab_strategy_note AS note, lab_strategy_container AS is_container,
                  lab_strategy_takeprofit AS takeprofit, lab_strategy_stoploss AS stoploss,
                  lab_strategy_margin AS margin, lab_strategy_timelife AS timelife
           FROM lab_strategies WHERE lab_strategy_id = %s""",
        (sid,),
    )
    if not row:
        raise HTTPException(404, "Không tìm thấy chiến thuật")
    if row["is_container"]:
        row["children"] = fetch_all(
            """SELECT c.lab_stra_con_child AS id, s.lab_strategy_name AS name,
                      c.lab_stra_con_weight AS weight, c.lab_stra_con_slot AS slot
               FROM lab_strategy_container c
               JOIN lab_strategies s ON s.lab_strategy_id = c.lab_stra_con_child
               WHERE c.lab_stra_con_container = %s ORDER BY c.lab_stra_con_weight""",
            (sid,),
        )
    return row


@app.get("/api/strategy-groups")
def strategy_groups():
    return {
        "rows": fetch_all(
            """SELECT lab_strategy_group AS name, COUNT(*) AS n FROM lab_strategies
               WHERE lab_strategy_group IS NOT NULL AND lab_strategy_group <> ''
               GROUP BY lab_strategy_group ORDER BY n DESC"""
        )
    }




# ---------------------------------------------------------------- đào chiến lược

@app.get("/api/miner/optimizations")
def list_optimizations(limit: int = 60, q_: str = Query(None, alias="q")):
    """Các phiên đào chiến lược (grid-search tham số)."""
    where, params = ["1=1"], []
    if q_:
        where.append("lab_opt_name LIKE %s")
        params.append(f"%{q_}%")
    rows = fetch_all(
        f"""SELECT lab_opt_id AS id, lab_opt_name AS name, lab_opt_account AS base_run,
                   lab_opt_thread AS workers, lab_opt_data_leng AS data_len,
                   lab_opt_start_time AS start_time, lab_opt_stop_time AS stop_time,
                   lab_opt_server AS node, CHAR_LENGTH(lab_opt_params) AS params_size
            FROM lab_optimization WHERE {' AND '.join(where)}
            ORDER BY lab_opt_id DESC LIMIT %s""",
        params + [limit],
    )
    if rows:
        ids = tuple(r["id"] for r in rows)
        ph = ",".join(["%s"] * len(ids))
        done = {
            d["o"]: d
            for d in fetch_all(
                f"""SELECT lab_opt_result_optimization AS o, COUNT(*) AS tong,
                           SUM(lab_opt_result_done = 1) AS xong
                    FROM lab_opt_result WHERE lab_opt_result_optimization IN ({ph})
                    GROUP BY lab_opt_result_optimization""",
                list(ids),
            )
        }
        for r in rows:
            d = done.get(r["id"], {})
            r["total"] = d.get("tong", 0)
            r["done"] = d.get("xong", 0)
    return {"rows": rows}


@app.get("/api/miner/optimizations/{oid}")
def get_optimization(oid: int):
    row = fetch_one(
        """SELECT lab_opt_id AS id, lab_opt_name AS name, lab_opt_account AS base_run,
                  lab_opt_params AS params, lab_opt_thread AS workers,
                  lab_opt_log AS log, lab_opt_note AS note
           FROM lab_optimization WHERE lab_opt_id = %s""",
        (oid,),
    )
    if not row:
        raise HTTPException(404, "Không tìm thấy phiên đào")
    return row


# ------------------------------------------------- tham số quét của phiên đào

MAX_WORKERS = 6   # trần cứng của ResourceGuard, không được vượt

def _doc_bien(raw):
    """Tách chuỗi JSON tham số thành danh sách biến dễ chỉnh.

    Ba kiểu biến trong dữ liệu gốc:
      INPUT       — danh sách giá trị rời, mỗi giá trị là một nhánh quét
      SETS        — danh sách bộ giá trị (ví dụ tỷ lệ vốn từng bậc DCA)
      EXPRESSIONS — công thức tính từ biến khác, viết dạng #tên_biến#
    Chỉ INPUT và SETS mới nhân số tổ hợp lên.
    """
    try:
        arr = json.loads(raw or "[]")
    except Exception:
        return [], 0
    bien, to_hop = [], 1
    for b in arr if isinstance(arr, list) else []:
        d = b.get("data")
        kieu = b.get("type") or "INPUT"
        if isinstance(d, list):
            gia_tri = [json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else str(x)
                       for x in d]
            to_hop *= max(1, len(gia_tri))
        else:
            gia_tri = [str(d)] if d is not None else []
        bien.append({
            "id": b.get("id"),
            "name": b.get("name"),
            "type": kieu,
            "values": gia_tri,
            "quet": kieu in ("INPUT", "SETS"),
        })
    return bien, to_hop


def _viet_bien(bien):
    """Dựng lại chuỗi JSON tham số từ danh sách biến đã chỉnh."""
    ra = []
    for b in bien:
        kieu = b.get("type") or "INPUT"
        gia_tri = [str(v).strip() for v in (b.get("values") or []) if str(v).strip() != ""]
        if kieu == "EXPRESSIONS":
            data = gia_tri[0] if gia_tri else ""
        else:
            data = []
            for v in gia_tri:
                if v.startswith("[") or v.startswith("{"):
                    try:
                        data.append(json.loads(v))
                        continue
                    except Exception:
                        pass
                data.append(v)
        ra.append({"id": str(b.get("id") or ""), "name": b.get("name"),
                   "type": kieu, "data": data})
    return json.dumps(ra, ensure_ascii=False)


def _chien_luoc_cua_run(run_id: int):
    """Các mã chiến lược mà một lần chạy đang dùng."""
    rows = fetch_all(
        "SELECT DISTINCT lab_campaign_strategy AS s FROM lab_campaigns "
        "WHERE lab_campaign_account = %s AND lab_campaign_strategy IS NOT NULL",
        (run_id,),
    )
    return [r["s"] for r in rows if r["s"]]


def _phien_tot_nhat(opt_ids):
    """Trong các phiên đã cho, lấy tổ hợp cho số dư cuối cao nhất."""
    if not opt_ids:
        return None
    ph = ",".join(["%s"] * len(opt_ids))
    return fetch_one(
        f"""SELECT lab_opt_result_optimization AS opt_id,
                   lab_opt_result_params        AS params,
                   ROUND(lab_opt_result_balance, 2) AS balance
            FROM lab_opt_result
            WHERE lab_opt_result_optimization IN ({ph}) AND lab_opt_result_done = 1
            ORDER BY lab_opt_result_balance DESC LIMIT 1""",
        list(opt_ids),
    )


def _tot_nhat_cho(base_run: int = None, opt: int = None):
    """Tìm bộ tham số cho lợi tức cao nhất để làm mẫu điền sẵn.

    Ưu tiên từ gần tới xa:
      1. chính phiên đang xem
      2. các phiên quét trên đúng lần chạy này
      3. các phiên quét trên lần chạy khác nhưng dùng cùng chiến lược
    Không có gì thì thôi, không bịa số.
    """
    if opt:
        kq = _phien_tot_nhat([opt])
        if kq:
            return kq, "chính phiên này"

    if base_run:
        ids = [r["id"] for r in fetch_all(
            "SELECT lab_opt_id AS id FROM lab_optimization WHERE lab_opt_account = %s",
            (base_run,))]
        kq = _phien_tot_nhat(ids)
        if kq:
            return kq, "phiên quét khác trên cùng lần chạy"

        chien_luoc = _chien_luoc_cua_run(base_run)
        if chien_luoc:
            ph = ",".join(["%s"] * len(chien_luoc))
            ids = [r["id"] for r in fetch_all(
                f"""SELECT DISTINCT o.lab_opt_id AS id
                    FROM lab_optimization o
                    JOIN lab_campaigns c ON c.lab_campaign_account = o.lab_opt_account
                    WHERE c.lab_campaign_strategy IN ({ph})""",
                list(chien_luoc))]
            kq = _phien_tot_nhat(ids)
            if kq:
                return kq, "phiên quét của chiến lược này"

    # Không có gì gần thì lấy phiên lợi tức cao nhất toàn hệ thống làm mẫu khởi đầu,
    # và nói rõ nó không cùng chiến lược để người dùng còn biết mà sửa.
    kq = fetch_one(
        """SELECT lab_opt_result_optimization AS opt_id, lab_opt_result_params AS params,
                  ROUND(lab_opt_result_balance, 2) AS balance
           FROM lab_opt_result WHERE lab_opt_result_done = 1
           ORDER BY lab_opt_result_balance DESC LIMIT 1"""
    )
    if kq:
        return kq, "phiên lợi tức cao nhất trong hệ thống (khác chiến lược)"
    return None, None


def _gan_tot_nhat(bien, kq):
    """Gắn giá trị thắng cuộc vào từng biến để hiện làm gợi ý."""
    if not kq:
        return bien
    try:
        thang = json.loads(kq["params"] or "{}")
    except Exception:
        thang = {}
    for b in bien:
        ten = b.get("name")
        v = thang.get(f"#{ten}#")
        if v is None and b.get("type") == "SETS":
            # bộ giá trị bị trải phẳng thành #tên[0]#, #tên[1]#…
            bo, i = [], 0
            while f"#{ten}[{i}]#" in thang:
                bo.append(thang[f"#{ten}[{i}]#"])
                i += 1
            v = bo or None
        if v is not None:
            b["tot_nhat"] = (json.dumps(v, ensure_ascii=False)
                             if isinstance(v, (list, dict)) else str(v))
    return bien


@app.get("/api/miner/mau")
def mau_tham_so(base_run: int = None, opt: int = None):
    """Bộ tham số mẫu để mở sẵn khi tạo phiên đào mới.

    Lấy cấu trúc biến từ phiên quét gần nhất của lần chạy, và điền kèm giá trị
    của tổ hợp cho lợi tức cao nhất — có cái để bắt đầu thay vì màn hình trắng.
    """
    kq, nguon = _tot_nhat_cho(base_run, opt)
    goc_id = opt or (kq or {}).get("opt_id")
    if not goc_id:
        return {"bien": [], "to_hop": 0, "tot_nhat": None,
                "max_workers": MAX_WORKERS, "workers": 2, "data_len": 10,
                "node": ctl.NODE, "base_run": base_run,
                "ghi_chu": "Chưa có phiên quét nào cho lần chạy này để lấy làm mẫu"}

    goc = fetch_one(
        """SELECT lab_opt_id AS id, lab_opt_name AS name, lab_opt_params AS params,
                  lab_opt_thread AS workers, lab_opt_data_leng AS data_len,
                  lab_opt_server AS node
           FROM lab_optimization WHERE lab_opt_id = %s""",
        (goc_id,),
    ) or {}
    bien, to_hop = _doc_bien(goc.get("params"))
    bien = gan_nghia(_gan_tot_nhat(bien, kq))

    return {
        "base_run": base_run or None,
        "workers": min(goc.get("workers") or 2, MAX_WORKERS),
        "data_len": goc.get("data_len") or 10,
        "node": goc.get("node") or ctl.NODE,
        "max_workers": MAX_WORKERS,
        "bien": bien,
        "to_hop": to_hop,
        "tot_nhat": {
            "opt_id": goc.get("id"),
            "opt_name": goc.get("name"),
            "balance": (kq or {}).get("balance"),
            "nguon": nguon,
        } if kq else None,
    }


# ------------------------------------------------ đọc tên tham số cho dễ hiểu

KHUNG = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]

# Nghĩa của những khoá engine dùng cố định
NGHIA_KHOA = {
    "takeprofit": "chốt lãi", "stoploss": "cắt lỗ", "baseprofit": "lãi nền",
    "step_profit": "bước lãi", "back_profit": "lùi lãi", "stepprofit": "bước lãi",
    "backprofit": "lùi lãi", "margin": "đòn bẩy", "timelife": "thời hạn giữ lệnh",
    "interval": "giãn cách", "enter_package": "tỷ lệ vốn vào lệnh",
    "enter_step": "bước vào lệnh", "enter_back": "lùi vào lệnh",
    "percent": "phần trăm so với giá tham chiếu", "multiply": "hệ số nhân",
    "index": "lùi bao nhiêu nến", "frame": "khung thời gian", "column": "chỉ báo",
    "max_open_trades": "số lệnh mở tối đa",
    "allow_negative_price_rate": "cho phép giá âm",
    "match_price": "giá đặt khớp lệnh", "match_order": "giá đặt bậc nhồi",
    "input": "biến vào", "order": "bậc nhồi lệnh",
}


def doc_chi_bao(col: str):
    """Dịch tên cột chỉ báo sang tiếng người: ema9 -> EMA 9, kup17_05 -> Keltner trên."""
    if not col:
        return None
    c = str(col).lower()
    goc = {"close": "giá đóng", "open": "giá mở", "high": "giá cao nhất",
           "low": "giá thấp nhất", "volume": "khối lượng",
           "matched_price": "giá đã khớp", "profit": "lãi lỗ hiện tại"}
    if c in goc:
        return goc[c]

    m = re.match(r"^(price_)?(ema|wma|sma|rsi|atr|macd)_?(\d+)?", c)
    if m:
        ten = {"ema": "EMA", "wma": "WMA", "sma": "SMA", "rsi": "RSI",
               "atr": "ATR", "macd": "MACD"}[m.group(2)]
        chu_ky = m.group(3)
        nhan = f"{ten} {chu_ky}" if chu_ky else ten
        if "rsi_wma" in c:
            nhan = "RSI làm mượt bằng WMA"
        return ("giá so với " if m.group(1) else "") + nhan

    m = re.match(r"^k(up|lo)(\d+)(?:_(\d+))?", c)
    if m:
        he_so = m.group(3)
        he_so = f"{float('0.' + he_so.lstrip('0') if len(he_so) > 1 else he_so)}" if he_so else None
        return (f"Keltner biên {'trên' if m.group(1) == 'up' else 'dưới'}"
                f" · EMA {m.group(2)}" + (f" · hệ số {he_so}" if he_so else ""))
    return None


def nghia_tham_so(ten: str, bien_khac=None):
    """Đoán nghĩa một biến quét từ tên và từ chỗ nó được dùng."""
    if not ten:
        return None
    t = str(ten).lower()

    # Tên gắn khung thời gian ở đuôi (stoploss4h, match_price_1h) phải tách đuôi
    # trước, không thì "stoploss4h" chỉ ra "cắt lỗ" mà mất mất khung.
    for k in sorted(KHUNG, key=len, reverse=True):
        if t.endswith(k) and len(t) > len(k):
            goc = nghia_tham_so(t[: -len(k)].rstrip("_"), bien_khac)
            return f"{goc} · khung {k}" if goc else f"tham số khung {k}"
        if t == k:
            return f"khung thời gian {k}"

    if t in NGHIA_KHOA:
        return NGHIA_KHOA[t]
    ci = doc_chi_bao(t)
    if ci:
        return ci
    for k, v in NGHIA_KHOA.items():
        if t.startswith(k):
            duoi = t[len(k):].strip("_")
            return f"{v} {duoi}" if duoi.isdigit() else v
    # dùng ở công thức nào thì nói ra công thức đó
    for b in (bien_khac or []):
        d = b.get("values") or []
        if b.get("type") == "EXPRESSIONS" and d and f"#{ten}#" in str(d[0]):
            return f"dùng trong công thức {b.get('name')} = {d[0]}"
    return None


def _tinh_bieu_thuc(bt: str):
    """Tính một biểu thức số học đơn giản, chỉ cho phép + - * / ( ) và số."""
    import ast as _ast

    def di(n):
        if isinstance(n, _ast.Expression):
            return di(n.body)
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, _ast.UnaryOp) and isinstance(n.op, (_ast.UAdd, _ast.USub)):
            v = di(n.operand)
            return v if isinstance(n.op, _ast.UAdd) else -v
        if isinstance(n, _ast.BinOp) and isinstance(
                n.op, (_ast.Add, _ast.Sub, _ast.Mult, _ast.Div)):
            a, b = di(n.left), di(n.right)
            if isinstance(n.op, _ast.Add):
                return a + b
            if isinstance(n.op, _ast.Sub):
                return a - b
            if isinstance(n.op, _ast.Mult):
                return a * b
            return a / b if b else None
        raise ValueError("phép toán không cho phép")

    try:
        return di(_ast.parse(str(bt), mode="eval"))
    except Exception:
        return None


def _goi_so(x):
    """Số cho người đọc: bỏ đuôi thập phân vô nghĩa (98.03921569 -> 98,04)."""
    if x is None:
        return "?"
    lam_tron = round(x, 2)
    if abs(lam_tron) < 0.01 and x != 0:
        lam_tron = round(x, 6)
    ra = f"{lam_tron:.10g}"
    return ra.replace(".", ",")


def giai_thich_bien(ten, gia_tri, bien_khac):
    """Nói bằng lời một biến quét thật ra điều khiển cái gì.

    Tên biến trong chiến lược do người viết tự đặt (input4h, order2…) nên tự nó
    chẳng nói gì. Nhưng biến luôn được dùng trong một công thức, và công thức đó
    mới là ý nghĩa thật. Thay số vào rồi diễn ra thành câu là hiểu ngay:
    order2 = -3, công thức 100+#order2# = 97  ->  "nhồi bậc 2 khi giá giảm 3%".
    """
    if gia_tri in (None, ""):
        return None
    v = str(gia_tri).strip()
    so = _tinh_bieu_thuc(v)

    for b in bien_khac or []:
        if b.get("type") != "EXPRESSIONS":
            continue
        d = b.get("values") or []
        ct = str(d[0]) if d else ""
        if f"#{ten}#" not in ct:
            continue
        thay = ct.replace(f"#{ten}#", f"({v})")
        kq = _tinh_bieu_thuc(re.sub(r"#[^#]+#", "1", thay))
        kq = _tinh_bieu_thuc(thay) if "#" not in thay else kq
        ten_dung = str(b.get("name") or "")

        m = re.match(r"^match_order(\d+)", ten_dung)
        if m and kq is not None:
            lech = 100 - kq
            huong = "giảm" if lech > 0 else "tăng"
            return (f"giá nhồi bậc {m.group(1)} = {_goi_so(kq)}% giá đã khớp"
                    f" → nhồi khi giá {huong} {_goi_so(abs(lech))}%")
        if ten_dung.startswith("match_price") and kq is not None:
            lech = 100 - kq
            if abs(lech) < 1e-9:
                return "giá đặt lệnh bằng đúng giá tham chiếu"
            huong = "thấp hơn" if lech > 0 else "cao hơn"
            return (f"giá đặt lệnh = {_goi_so(kq)}% giá tham chiếu"
                    f" → đặt {huong} {_goi_so(abs(lech))}%")
        if kq is not None:
            return f"{ten_dung} = {ct.replace('#' + ten + '#', v)} = {_goi_so(kq)}"

    # không có công thức nào dùng nó thì giải nghĩa theo tên và giá trị
    goc = nghia_tham_so(ten, bien_khac)
    if goc and so is not None:
        if "cắt lỗ" in goc:
            return f"{goc}: đóng lệnh khi lỗ {_goi_so(abs(so))}%"
        if "chốt lãi" in goc or "lãi nền" in goc:
            return f"{goc}: chốt khi lãi {_goi_so(so)}%"
        if "đòn bẩy" in goc:
            return f"{goc} {_goi_so(so)} lần"
        if "thời hạn" in goc:
            return f"{goc}: giữ tối đa {_goi_so(so)}"
    return goc


def gan_giai_thich(bien):
    """Viết lại ý nghĩa của từng biến quét cho ra tiếng người."""
    for b in bien:
        gt = (b.get("values") or [None])[0]
        if b.get("type") == "SETS" and gt:
            try:
                bo = json.loads(gt)
                if isinstance(bo, list):
                    b["y_nghia"] = ("tỷ lệ vốn " + str(len(bo)) + " bậc: "
                                    + " / ".join(f"{x}%" for x in bo))
                    continue
            except Exception:
                pass
        if b.get("type") == "EXPRESSIONS":
            # thay số của các biến được tham chiếu vào rồi tính ra kết quả thật
            ct = str(gt or "")
            thay = ct
            for x in bien:
                v = (x.get("values") or [None])[0]
                if v is not None and x.get("type") != "EXPRESSIONS":
                    thay = thay.replace(f"#{x.get('name')}#", f"({v})")
            kq = _tinh_bieu_thuc(thay) if "#" not in thay else None
            goc = nghia_tham_so(b.get("name"), bien)
            b["y_nghia"] = (f"{goc} = {_goi_so(kq)}" if (goc and kq is not None)
                            else goc)
            continue
        b["y_nghia"] = giai_thich_bien(b.get("name"), gt, bien) or nghia_tham_so(b.get("name"), bien)
    return bien


def gan_nghia(bien):
    return gan_giai_thich(bien)


# ------------------------------------------- kiểm biến quét theo luật của engine

RE_TEN_BIEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _so_hop_le(v):
    """Giá trị có qua nổi str2num của engine không.

    Engine chạy str2num: chỉ nhận [số + - * / ( ) khoảng trắng] rồi eval. Nên
    "4h" bị coi là chuỗi nguy hiểm, còn "05" thì Python 3 báo lỗi cú pháp
    (số nguyên không được bắt đầu bằng 0). Cả hai đều làm sập cả phiên quét
    giữa chừng, nên phải chặn ngay lúc tạo.
    """
    st = str(v).strip()
    if not st:
        return "để trống"
    if not re.match(r"^[\d+\-*/(). ]+$", st):
        return f"“{st}” không phải số — bộ tối ưu chỉ nhận số và phép + - * / ( )"
    if _tinh_bieu_thuc(st) is None:
        return f"“{st}” không tính được (số nguyên không được bắt đầu bằng 0, ví dụ viết 0.5 thay cho 05)"
    return None


def kiem_bien_quet(bien):
    """Soi bộ biến quét trước khi ghi, trả về danh sách lỗi bằng tiếng Việt."""
    loi = []
    da_khai = set()
    for i, b in enumerate(bien):
        ten = str(b.get("name") or "").strip()
        vt = f"dòng {i + 1}"
        if not RE_TEN_BIEN.match(ten):
            loi.append(f"{vt}: tên biến “{ten}” không hợp lệ — chỉ dùng chữ, số và gạch dưới, "
                       f"không bắt đầu bằng số")
            continue
        if ten in da_khai:
            loi.append(f"{vt}: trùng tên biến “{ten}”")
        kieu = b.get("type") or "INPUT"
        gt = [x for x in (b.get("values") or []) if str(x).strip() != ""]

        if kieu == "EXPRESSIONS":
            ct = str(gt[0]) if gt else ""
            if not ct:
                loi.append(f"{vt}: công thức “{ten}” đang trống")
            for ref in re.findall(r"#([^#]+)#", ct):
                goc = ref.split("[")[0]
                if goc not in da_khai:
                    loi.append(f"{vt}: công thức “{ten}” dùng #{ref}# nhưng biến đó chưa khai "
                               f"phía trên — kéo “{goc}” lên trước “{ten}”")
        elif kieu == "SETS":
            if not gt:
                loi.append(f"{vt}: “{ten}” chưa có bộ giá trị nào")
            do_dai = set()
            for v in gt:
                try:
                    bo = json.loads(v) if isinstance(v, str) else v
                except Exception:
                    loi.append(f"{vt}: “{ten}” có bộ không đọc được: {v}")
                    continue
                if not isinstance(bo, list):
                    loi.append(f"{vt}: “{ten}” kiểu SETS thì mỗi dòng phải là một bộ, ví dụ [15,30,30,25]")
                    continue
                do_dai.add(len(bo))
                for x in bo:
                    ly_do = _so_hop_le(x)
                    if ly_do:
                        loi.append(f"{vt}: “{ten}” — {ly_do}")
            if len(do_dai) > 1:
                loi.append(f"{vt}: “{ten}” có các bộ dài ngắn khác nhau ({sorted(do_dai)}) — "
                           f"chiến lược sẽ thiếu #{ten}[n]# ở bộ ngắn")
        else:
            if not gt:
                loi.append(f"{vt}: “{ten}” chưa có giá trị nào để quét")
            for v in gt:
                ly_do = _so_hop_le(v)
                if ly_do:
                    loi.append(f"{vt}: “{ten}” — {ly_do}")

        da_khai.add(ten)
    return loi


def _sinh_id_bien(bien):
    """Gắn id cho biến chưa có, giữ đúng dạng bản ghi mà portal cũ sinh ra."""
    moc = int(time.time() * 1_000_000)
    for i, b in enumerate(bien):
        if not str(b.get("id") or "").strip():
            b["id"] = str(moc + i)
    return bien


@app.get("/api/miner/optimizations/{oid}/params")
def optimization_params(oid: int):
    """Tham số quét của một phiên, đã tách sẵn để chỉnh trên giao diện."""
    row = fetch_one(
        """SELECT lab_opt_id AS id, lab_opt_name AS name, lab_opt_account AS base_run,
                  lab_opt_params AS params, lab_opt_thread AS workers,
                  lab_opt_data_leng AS data_len, lab_opt_server AS node
           FROM lab_optimization WHERE lab_opt_id = %s""",
        (oid,),
    )
    if not row:
        raise HTTPException(404, "Không tìm thấy phiên đào")
    bien, to_hop = _doc_bien(row.pop("params"))
    kq, nguon = _tot_nhat_cho(row.get("base_run"), oid)
    bien = gan_nghia(_gan_tot_nhat(bien, kq))
    return {
        **row, "bien": bien, "to_hop": to_hop, "max_workers": MAX_WORKERS,
        "tot_nhat": {"opt_id": (kq or {}).get("opt_id"), "balance": (kq or {}).get("balance"),
                     "nguon": nguon} if kq else None,
    }


@app.post("/api/miner/optimizations")
def create_optimization(body: dict = Body(...)):
    """Lưu bộ tham số đã tinh chỉnh thành một phiên quét MỚI.

    Cố ý không ghi đè phiên cũ: bảng này dùng chung với hệ thống thật, sửa
    thẳng vào một phiên đang có kết quả là xoá mất lịch sử của người khác.
    """
    ten = (body.get("name") or "").strip()
    base_run = body.get("base_run")
    bien = body.get("bien") or []
    if not ten:
        raise HTTPException(400, "Chưa đặt tên phiên")
    if not base_run:
        raise HTTPException(400, "Chưa chọn lần chạy gốc")
    if not bien:
        raise HTTPException(400, "Chưa có biến nào để quét")

    loi = kiem_bien_quet(bien)
    if loi:
        raise HTTPException(400, " · ".join(loi[:6]))

    workers = max(1, min(int(body.get("workers") or 2), MAX_WORKERS))
    data_len = max(1, int(body.get("data_len") or 10))
    node = body.get("node") or ctl.NODE
    params = _viet_bien(_sinh_id_bien(bien))
    _, to_hop = _doc_bien(params)

    with cursor() as c:
        c.execute(
            """INSERT INTO lab_optimization
                 (lab_opt_name, lab_opt_account, lab_opt_params, lab_opt_thread,
                  lab_opt_data_leng, lab_opt_server, lab_opt_note)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (ten, int(base_run), params, workers, data_len, node,
             "Tạo từ giao diện Nora"),
        )
        c.connection.commit()
        c.execute("SELECT LAST_INSERT_ID() AS id")
        moi_id = (c.fetchone() or {}).get("id")

    return {"id": moi_id, "to_hop": to_hop, "workers": workers}


@app.get("/api/miner/optimizations/{oid}/progress")
def optimization_progress(oid: int):
    return ctl.opt_progress(oid)


@app.post("/api/miner/optimizations/{oid}/start")
def optimization_start(oid: int):
    r = ctl.opt_start(oid)
    if not r.get("result"):
        raise HTTPException(400, r.get("message") or "Không chạy được phiên quét")
    return r


@app.post("/api/miner/optimizations/{oid}/stop")
def optimization_stop(oid: int):
    return ctl.opt_stop(oid)


@app.get("/api/miner/optimizations/{oid}/log")
def optimization_log(oid: int, tail: int = 120):
    return ctl.opt_log(oid, tail)


# Bộ xử lý dữ liệu nến tính sẵn một lưới cột chỉ báo; quét ra ngoài lưới đó là
# engine đọc phải cột không tồn tại và lặng lẽ ra kết quả rỗng.
FILE_XU_LY = MONITOR_DIR / "Backtest" / "Processors" / "klineProcessorCustom.py"
_luoi_cache = {}


def luoi_chi_bao():
    """Đọc cấu hình bộ xử lý để biết chỉ báo nào quét được, trong dải nào."""
    if _luoi_cache:
        return _luoi_cache
    kel_ky, kel_hs, ema_ky, co_dinh = set(), set(), set(), {}
    try:
        noi_dung = FILE_XU_LY.read_text(encoding="utf-8")
    except Exception:
        noi_dung = ""
    for dong in noi_dung.splitlines():
        d = dong.strip()
        if not d.startswith("['"):
            continue
        if "'keltner'" in d:
            m = re.search(r"\[(\d+),\s*(\d+),\s*([\d.]+)\]", d)
            if m:
                kel_ky.add(int(m.group(1)))
                kel_hs.add(m.group(3))
        if "'ema'" in d:
            for c in re.findall(r"'price_ema(\d+)'", d):
                ema_ky.add(int(c))
        m = re.match(r"\['all',\s*'(rsi|atr)',[^,]*,\s*(\d+)", d)
        if m:
            co_dinh[m.group(1)] = int(m.group(2))
    _luoi_cache.update({
        "keltner_chu_ky": sorted(kel_ky), "keltner_he_so": sorted(kel_hs),
        "ema_chu_ky": sorted(ema_ky), "co_dinh": co_dinh,
        "nguon": str(FILE_XU_LY),
    })
    return _luoi_cache


@app.get("/api/miner/luoi-chi-bao")
def api_luoi_chi_bao():
    """Dải giá trị chỉ báo mà bộ dữ liệu đã tính sẵn."""
    return luoi_chi_bao()


def _gioi_han_cho(t):
    """Núm chỉ báo này quét được những giá trị nào."""
    lu = luoi_chi_bao()
    goc = (t.get("ap_dung") or [{}])[0].get("goc") or ""
    phan = (t.get("ap_dung") or [{}])[0].get("phan")
    if re.match(r"^k(?:up|lo)", goc):
        if phan == "he_so":
            # Tên cột viết hệ số không dấu chấm (kup17_05), mà bộ tối ưu chạy
            # str2num trên giá trị biến — "05" là cú pháp số không hợp lệ nên
            # cả phiên quét sẽ sập. Đổi hệ số thì dùng "Đổi tham số" ở lần chạy.
            return {"co_dinh": True,
                    "ghi_chu": "hệ số ghi trong tên cột dạng 05/1 nên không quét được "
                               "(bộ tối ưu chỉ nhận số thuần) — đổi hệ số bằng "
                               "“Chạy backtest → Đổi tham số” ở lần chạy"}
        return {"tu": min(lu["keltner_chu_ky"] or [0]), "den": max(lu["keltner_chu_ky"] or [0]),
                "ghi_chu": "bộ dữ liệu tính sẵn Keltner chu kỳ "
                           f"{min(lu['keltner_chu_ky'] or [0])}–{max(lu['keltner_chu_ky'] or [0])}"}
    if re.match(r"^price_ema", goc):
        return {"tu": min(lu["ema_chu_ky"] or [0]), "den": max(lu["ema_chu_ky"] or [0]),
                "ghi_chu": f"bộ dữ liệu tính sẵn EMA chu kỳ "
                           f"{min(lu['ema_chu_ky'] or [0])}–{max(lu['ema_chu_ky'] or [0])}"}
    if re.match(r"^(rsi|atr)", goc):
        n = luoi_chi_bao()["co_dinh"].get(goc[:3])
        return {"co_dinh": True,
                "ghi_chu": f"bộ dữ liệu chỉ có một cột {goc[:3].upper()} chu kỳ {n} — "
                           "muốn quét phải xử lý lại dữ liệu nến"}
    return {}


@app.get("/api/miner/chi-bao")
def chi_bao_quet_duoc(base_run: int):
    """Các chỉ báo trong chiến lược của một lần chạy mà có thể đem đi quét.

    Bộ nạp của engine thay #biến# vào nội dung chiến lược ở dạng CHUỖI rồi mới
    đọc JSON (processLabChildStrategy), nên "kup#ky#_05" là hợp lệ — tức là chu
    kỳ chỉ báo hoàn toàn quét được, chỉ là từ trước tới nay chưa ai làm.
    """
    sids = [r["s"] for r in fetch_all(
        "SELECT DISTINCT lab_campaign_strategy AS s FROM lab_campaigns "
        "WHERE lab_campaign_account = %s AND lab_campaign_strategy IS NOT NULL", (base_run,))]
    ra = []
    for sid in sids:
        d = _num_chien_luoc(sid)
        if not d:
            continue
        for t in d["de_hieu"]:
            if t["nhom"] != "Chỉ báo":
                continue
            ra.append({**t, "strategy": sid, "chien_luoc": d["name"],
                       "ten_bien_goi_y": _ten_bien_goi_y(t),
                       "gioi_han": _gioi_han_cho(t)})
    return {"rows": ra, "base_run": base_run}


def _ten_bien_goi_y(t):
    """Tên biến gợi ý cho một chỉ báo, chỉ gồm chữ thường và gạch dưới."""
    goc = (t.get("ap_dung") or [{}])[0].get("goc") or t.get("ma") or "bien"
    phan = t.get("phan") or (t.get("ap_dung") or [{}])[0].get("phan") or ""
    ten = re.sub(r"[^a-z0-9]+", "_", str(goc).lower()).strip("_")
    ten = re.sub(r"\d+", "", ten).strip("_") or "chi_bao"
    return f"{ten}_{'he_so' if phan == 'he_so' else 'chu_ky'}"


@app.post("/api/miner/quet-chi-bao")
def tao_phien_quet_chi_bao(body: dict = Body(...)):
    """Tạo phiên đào có quét cả chu kỳ chỉ báo.

    Muốn quét chu kỳ EMA thì nội dung chiến lược phải mang #biến# ở đúng chỗ đó,
    mà chiến lược gốc thì dùng chung với lần chạy khác — nên ở đây nhân bản
    thành chiến lược mới có tham số, kèm một lần chạy mới trỏ vào nó, rồi mới
    tạo phiên đào trên lần chạy đó. Không đụng gì tới bản gốc.
    """
    base_run = body.get("base_run")
    chi_bao = body.get("chi_bao") or []
    if not base_run:
        raise HTTPException(400, "Chưa chọn lần chạy gốc")
    if not chi_bao:
        raise HTTPException(400, "Chưa chọn chỉ báo nào để quét")

    ten = (body.get("name") or f"Quét chỉ báo từ lần chạy {base_run}").strip()
    workers = max(1, min(int(body.get("workers") or 2), MAX_WORKERS))
    data_len = max(1, int(body.get("data_len") or 10))

    cu = fetch_one(
        """SELECT lab_account_name AS name, lab_account_balance AS balance,
                  lab_account_margin_balance AS margin_balance, lab_account_reserve AS reserve,
                  lab_account_compound AS compound, lab_account_margin_type AS margin_type,
                  lab_account_track_balance AS track_balance, lab_account_sync AS sync,
                  lab_account_leap AS leap, lab_account_db AS db,
                  lab_account_data_type AS data_type, lab_account_data_length AS data_len,
                  lab_account_group AS `group`
           FROM lab_account WHERE lab_account_id = %s""", (base_run,))
    if not cu:
        raise HTTPException(404, "Không tìm thấy lần chạy gốc")

    # gom thay đổi theo chiến lược: đặt #biến# vào đúng phần cần quét
    theo_cl = {}
    for c in chi_bao:
        sid = int(c["strategy"])
        ten_bien = re.sub(r"[^A-Za-z0-9_]", "", str(c.get("ten_bien") or ""))
        if not ten_bien:
            raise HTTPException(400, "Biến quét phải có tên")
        gia_tri = [str(x).strip() for x in (c.get("values") or []) if str(x).strip()]
        if not gia_tri:
            raise HTTPException(400, f"Biến {ten_bien} chưa có dải giá trị")

        # Quét ra ngoài lưới cột đã tính sẵn thì engine đọc phải cột trống và
        # trả về kết quả rỗng mà không báo gì — chặn ngay từ đây.
        gh = _gioi_han_cho(c)
        if gh.get("co_dinh"):
            raise HTTPException(400, gh.get("ghi_chu") or "Chỉ báo này chưa quét được")
        if gh.get("chon"):
            xau = [v for v in gia_tri if v not in gh["chon"]
                   and (f"0.{v[1:]}" if len(v) > 1 and v.startswith("0") else v) not in gh["chon"]]
            if xau:
                raise HTTPException(400, f"Giá trị {', '.join(xau)} không có trong bộ dữ liệu. "
                                         f"{gh.get('ghi_chu', '')}")
        if gh.get("tu") is not None:
            xau = [v for v in gia_tri
                   if not v.lstrip("-").isdigit() or not (gh["tu"] <= int(v) <= gh["den"])]
            if xau:
                raise HTTPException(400, f"Giá trị {', '.join(xau)} nằm ngoài dải đã tính sẵn. "
                                         f"{gh.get('ghi_chu', '')}")
        theo_cl.setdefault(sid, []).append((ten_bien, gia_tri, c.get("ap_dung") or []))

    doi_ma = {}
    with cursor() as c:
        for sid, ds in theo_cl.items():
            st = fetch_one("SELECT * FROM lab_strategies WHERE lab_strategy_id = %s", (sid,))
            if not st:
                raise HTTPException(404, f"Không tìm thấy chiến lược {sid}")
            content = json.loads(st.get("lab_strategy_content") or "{}")
            for ten_bien, _gt, ap in ds:
                for a in ap:
                    goc = str(a.get("goc") or "")
                    phan = a.get("phan")
                    m = re.match(r"^(k(?:up|lo))(\d+)(?:_(\d+))?$", goc)
                    if m:
                        moi = (f"{m.group(1)}#{ten_bien}#" + (f"_{m.group(3)}" if m.group(3) else "")
                               if phan == "chu_ky"
                               else f"{m.group(1)}{m.group(2)}_#{ten_bien}#")
                    else:
                        m2 = re.match(r"^(.*?)(\d+)$", goc)
                        if not m2:
                            continue
                        moi = f"{m2.group(1)}#{ten_bien}#"
                    _dat_theo_duong(content, a["duong_dan"], moi)

            c.execute(
                """INSERT INTO lab_strategies
                     (lab_strategy_name, lab_strategy_content, lab_strategy_takeprofit,
                      lab_strategy_stoploss, lab_strategy_baseprofit, lab_strategy_stepprofit,
                      lab_strategy_backprofit, lab_strategy_baseprofit_baseon,
                      lab_strategy_timelife, lab_strategy_interval, lab_strategy_margin,
                      lab_strategy_note, lab_strategy_group)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (f"{st['lab_strategy_name']}-quet", json.dumps(content, ensure_ascii=False),
                 st["lab_strategy_takeprofit"], st["lab_strategy_stoploss"],
                 st["lab_strategy_baseprofit"], st["lab_strategy_stepprofit"],
                 st["lab_strategy_backprofit"], st["lab_strategy_baseprofit_baseon"],
                 st["lab_strategy_timelife"], st["lab_strategy_interval"],
                 st["lab_strategy_margin"],
                 f"Tham số hoá chỉ báo từ chiến lược {sid} để quét", NHOM_ALPHA))
            c.connection.commit()
            c.execute("SELECT LAST_INSERT_ID() AS id")
            doi_ma[sid] = (c.fetchone() or {}).get("id")

        c.execute(
            """INSERT INTO lab_account
                 (lab_account_name, lab_account_balance, lab_account_margin_balance,
                  lab_account_reserve, lab_account_compound, lab_account_margin_type,
                  lab_account_track_balance, lab_account_running, lab_account_sync,
                  lab_account_leap, lab_account_db, lab_account_data_type,
                  lab_account_data_length, lab_account_server, lab_account_note,
                  lab_account_group)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (ten_khong_trung(f"{ten} · nền"), cu["balance"], cu["margin_balance"], cu["reserve"],
             cu["compound"], cu["margin_type"], cu["track_balance"], cu["sync"], cu["leap"],
             cu["db"], cu["data_type"], cu["data_len"], ctl.NODE,
             f"nora:quet:{base_run}", cu["group"] or NHOM_ALPHA))
        c.connection.commit()
        c.execute("SELECT LAST_INSERT_ID() AS id")
        run_moi = (c.fetchone() or {}).get("id")

        c.execute(
            """SELECT lab_campaign_symbol AS symbol, lab_campaign_start AS start,
                      lab_campaign_stop AS stop, lab_campaign_params AS params,
                      lab_campaign_side AS side, lab_campaign_strategy AS strategy,
                      lab_campaign_budget AS budget, lab_campaign_reserve AS reserve,
                      lab_campaign_compound AS compound, lab_campaign_money AS money,
                      lab_campaign_active_budget AS active_budget,
                      lab_campaign_priority AS priority
               FROM lab_campaigns WHERE lab_campaign_account = %s""", (base_run,))
        hang = [(
            f"{ten}-{cp['symbol']}", cp["symbol"], cp["start"], cp["stop"], cp["params"],
            cp["side"], doi_ma.get(cp["strategy"], cp["strategy"]), run_moi,
            cp["budget"], cp["reserve"], cp["compound"], cp["money"],
            cp["active_budget"], cp["priority"],
        ) for cp in c.fetchall()]
        c.executemany(
            """INSERT INTO lab_campaigns
                 (lab_campaign_name, lab_campaign_symbol, lab_campaign_start,
                  lab_campaign_stop, lab_campaign_params, lab_campaign_side,
                  lab_campaign_strategy, lab_campaign_account, lab_campaign_budget,
                  lab_campaign_reserve, lab_campaign_compound, lab_campaign_money,
                  lab_campaign_active_budget, lab_campaign_priority,
                  lab_campaign_status, lab_campaign_running)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '0,0', 0)""",
            hang)
        c.connection.commit()

        bien = list(body.get("bien") or [])
        for ds in theo_cl.values():
            for ten_bien, gia_tri, _ap in ds:
                bien.append({"id": "", "name": ten_bien, "type": "INPUT", "values": gia_tri})
        loi = kiem_bien_quet(bien)
        if loi:
            raise HTTPException(400, " · ".join(loi[:6]))
        params = _viet_bien(_sinh_id_bien(bien))
        _, to_hop = _doc_bien(params)

        c.execute(
            """INSERT INTO lab_optimization
                 (lab_opt_name, lab_opt_account, lab_opt_params, lab_opt_thread,
                  lab_opt_data_leng, lab_opt_server, lab_opt_note)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (ten, run_moi, params, workers, data_len, ctl.NODE,
             f"Quét chỉ báo, nền từ lần chạy {base_run}"))
        c.connection.commit()
        c.execute("SELECT LAST_INSERT_ID() AS id")
        opt_id = (c.fetchone() or {}).get("id")

    return {"result": True, "opt_id": opt_id, "run_id": run_moi,
            "chien_luoc_moi": doi_ma, "so_coin": len(hang), "to_hop": to_hop,
            "message": f"Đã tạo phiên đào {opt_id} trên lần chạy nền {run_moi}"
                       f" · {to_hop} tổ hợp · {len(hang)} coin"}


@app.get("/api/miner/optimizations/{oid}/results")
def optimization_results(oid: int, limit: int = 100, sort: str = "balance"):
    """Bảng xếp hạng các tổ hợp tham số. LUÔN lọc theo phiên — bảng có 102.860 dòng."""
    order = {
        "balance": "lab_opt_result_balance DESC",
        "position": "lab_opt_result_total_position DESC",
        "invest": "lab_opt_result_invest_max ASC",
        "unrealize": "lab_opt_result_unrelize_max ASC",
    }.get(sort, "lab_opt_result_balance DESC")
    rows = fetch_all(
        f"""SELECT lab_opt_result_id AS id, lab_opt_result_params AS params,
                   ROUND(lab_opt_result_balance, 2)        AS balance,
                   ROUND(lab_opt_result_margin_balance, 2) AS margin_balance,
                   ROUND(lab_opt_result_unrelize_max, 2)   AS unrealize_max,
                   ROUND(lab_opt_result_invest_max, 2)     AS invest_max,
                   lab_opt_result_total_position           AS positions,
                   lab_opt_result_total_long               AS longs,
                   lab_opt_result_total_short              AS shorts,
                   lab_opt_result_total_takeprofit         AS takeprofit,
                   lab_opt_result_total_stoploss           AS stoploss,
                   lab_opt_result_interval_avg             AS interval_avg,
                   lab_opt_result_done                     AS done
            FROM lab_opt_result WHERE lab_opt_result_optimization = %s
            ORDER BY {order} LIMIT %s""",
        (oid, limit),
    )
    for r in rows:
        tp = r["takeprofit"] or 0
        sl = r["stoploss"] or 0
        tot = tp + sl
        r["winrate"] = round(100 * tp / tot, 1) if tot else None
    return {"rows": rows}

# ---------------------------------------------------------------- biểu đồ

@app.get("/api/runs/{run_id}/chart-options")
def chart_options(run_id: int):
    """Coin và ngày có nhiều lệnh nhất — để giao diện gợi ý sẵn."""
    return {
        "symbols": fetch_all(
            """SELECT lab_result_symbol AS symbol, COUNT(*) AS n FROM lab_results
               WHERE lab_result_account = %s GROUP BY lab_result_symbol ORDER BY n DESC""",
            (run_id,),
        ),
        "presets": [
            {"id": "keltner9", "name": "Biên độ — dải Keltner"},
            {"id": "macross", "name": "Bám xu hướng — EMA × WMA"},
            {"id": "dca", "name": "DCA — RSI"},
            {"id": "all", "name": "Tất cả"},
        ],
    }


@app.get("/api/runs/{run_id}/chart-days")
def chart_days(run_id: int, symbol: str, limit: int = 20):
    return {
        "rows": fetch_all(
            """SELECT DATE(FROM_UNIXTIME(lab_result_chart / 1000)) AS ngay, COUNT(*) AS n
               FROM lab_results
               WHERE lab_result_account = %s AND lab_result_symbol = %s AND lab_result_chart > 0
               GROUP BY ngay ORDER BY n DESC, ngay DESC LIMIT %s""",
            (run_id, symbol, limit),
        )
    }


@app.post("/api/runs/{run_id}/chart")
def make_chart(run_id: int, symbol: str, day: str, frame: str = "4h", indicator: str = "keltner9"):
    """Sinh biểu đồ nến kèm chỉ báo và điểm vào lệnh."""
    fname = f"backtest_{run_id}_{symbol}_{day}.html"
    cmd = [
        "taskset", "-c", "8-11", "nice", "-n", "10",
        PYBIN, "manage.py", "backtest_chart",
        "-a", str(run_id), "-s", symbol, "-d", day,
        "--indicator", indicator, "--frame", frame,
    ]
    try:
        p = subprocess.run(cmd, cwd=MONITOR_DIR, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Sinh biểu đồ quá lâu (>180 giây)")
    path = CHART_DIR / fname
    if not path.exists():
        tail = (p.stdout or p.stderr or "")[-400:]
        raise HTTPException(500, f"Không sinh được biểu đồ. {tail}")
    return {"file": fname, "url": f"/charts/{fname}", "log": (p.stdout or "")[-600:]}


if CHART_DIR.exists():
    app.mount("/charts", StaticFiles(directory=str(CHART_DIR)), name="charts")


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- giao diện

WEB = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")

    def trang_chu():
        return FileResponse(WEB / "index.html",
                            headers={"Cache-Control": "no-cache, must-revalidate"})

    @app.get("/")
    def index():
        return trang_chu()

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, detail="API endpoint not found")
        f = WEB / path
        if f.is_file():
            return FileResponse(f)
        return trang_chu()
