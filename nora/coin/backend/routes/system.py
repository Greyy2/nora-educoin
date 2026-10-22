"""Phân hệ Routes Hệ thống (backend/routes/system.py):
Gộp các endpoint hệ thống, người dùng, tổng quan và giáo dục:
- Engine / Health / Version (/api/studio/nautilus)
- Home Summary (/api/home/summary)
- Studio Overview (/api/studio/overview)
- Users & Auth (/api/users, /api/me)
- Market Education (/api/edu)
"""
"""Phiên bản engine Nautilus (/api/studio/nautilus): chỉ BÁO cáo, không bao giờ tự cài/nâng cấp."""
from typing import Any, Dict

from fastapi import APIRouter

from backend.core import check_for_updates, get_version_info

router = APIRouter(prefix="/api/studio/nautilus", tags=["engine"])


@router.get("/version")
def get_nautilus_version() -> Dict[str, Any]:
    return get_version_info()


@router.get("/check_update")
def get_nautilus_check_update() -> Dict[str, Any]:
    """Hỏi PyPI bản mới nhất. Không trả lệnh cài: nâng cấp là thao tác thủ công có kiểm thử."""
    return check_for_updates()


engine_router = router


"""Router tóm tắt số liệu trang chủ Home (P17 T2 B4).

Endpoint GET /api/home/summary phục vụ số liệu thật cho trang Home (2 thẻ Education và Coin).
Số liệu lấy hoàn toàn từ nguồn thật, cache theo thời gian 1s để giảm tải I/O.
"""
import os
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter

from backend import users
from backend.analys.alpha import strategies as store, strategies
from backend.data.data import default_universe, read_manifest
from backend.analys.param import iso_date
from backend.models.storage import alpha_dir, alpha_education_samples, read_json

home_router = APIRouter(tags=["home"])


_SUMMARY_CACHE: Optional[Dict[str, Any]] = None
_CACHE_TIME: float = 0.0


@home_router.get("/api/home/summary")
def get_home_summary() -> Dict[str, Any]:
    """Số liệu thật cho trang Home."""
    global _SUMMARY_CACHE, _CACHE_TIME
    now = time.time()
    if _SUMMARY_CACHE is not None and (now - _CACHE_TIME) < 1.0:
        return _SUMMARY_CACHE

    # 1. Education
    n_users = len(users.list_users())
    all_alphas = store.list_user_alphas()
    n_strategies = sum(1 for a in all_alphas if a.get("owner_id") and a.get("status") != "ARCHIVED")

    samples_file = alpha_education_samples()
    samples_list = read_json(samples_file) if os.path.isfile(samples_file) else []
    n_samples = len(samples_list) if isinstance(samples_list, list) else 0

    res_dir = alpha_dir("education", "results")
    if os.path.isdir(res_dir):
        n_ready = len([f for f in os.listdir(res_dir) if f.endswith(".json") and not f.endswith(".tmp")])
    else:
        n_ready = 0

    edu_data = {
        "users": n_users,
        "strategies": n_strategies,
        "samples": n_samples,
        "samples_ready": n_ready,
    }

    # 2. Coin
    # Đếm số chiến lược hệ thống (theo catalog STRATEGIES)
    n_system = len(strategies.STRATEGIES)
    symbols = default_universe()
    n_symbols = len(symbols)

    lasts = []
    for sym in default_universe():
        m = read_manifest(sym)
        if m and m.get("end_ts"):
            try:
                lasts.append(int(m["end_ts"]))
            except (ValueError, TypeError):
                pass
    data_end = iso_date(min(lasts)) if lasts else None

    coin_data = {
        "system_strategies": n_system,
        "symbols": n_symbols,
        "data_end": data_end,
    }

    res = {"edu": edu_data, "coin": coin_data}
    _SUMMARY_CACHE = res
    _CACHE_TIME = now
    return res


"""GET /api/studio/overview — số liệu tổng hợp chung cho Backtest + Paper + Live (chỉ đọc, tính từ dữ liệu đã có)."""
import json
import os
from typing import Any, Dict, Optional

import time

import numpy as np
import pandas as pd
from fastapi import APIRouter

from backend.jobs import runner as batch_jobs
from backend.data.data import daily_close
from backend.adapter import exchange as led
from backend.analys.metrics import stats as nstats
from backend.adapter.exchange import find_bot_dir, get_bot_trades, list_bots
from backend.routes.studio import _bt_row

overview_router = APIRouter(prefix="/api/studio", tags=["overview"])
_TR_CACHE: Dict[str, Any] = {}


def _bt_trades(job_id: str) -> Optional[Dict[str, float]]:
    """Lệnh đã đóng của 1 backtest: số lệnh, số thắng, tổng lãi, tổng lỗ (đệm theo mtime)."""
    path = os.path.join(batch_jobs.job_dir(job_id), "result.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _TR_CACHE.get(job_id)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            tl = json.load(fh).get("trade_list") or []
    except (OSError, ValueError):
        return None
    p = [t["pnl"] for t in tl if isinstance(t.get("pnl"), (int, float))]
    agg = {"n": len(p), "wins": sum(1 for x in p if x > 0), "gain": sum(x for x in p if x > 0), "loss": -sum(x for x in p if x < 0)}
    _TR_CACHE[job_id] = (mt, agg)
    return agg


def _group(bots, mode_paper: bool) -> Dict[str, Any]:
    g = {"bots": 0, "running": 0, "pnl_usd": 0.0, "capital": 0.0, "closed": 0, "wins": 0, "gain": 0.0, "loss": 0.0, "mdd_pct": None}
    for b in bots:
        if (b.get("mode") == "paper") != mode_paper:
            continue
        g["bots"] += 1
        g["running"] += b.get("status") == "running"
        g["pnl_usd"] += float(b.get("pnl_usd") or 0.0)
        g["capital"] += float(b.get("capital") or 0.0)
        if isinstance(b.get("mdd_pct"), (int, float)):
            g["mdd_pct"] = b["mdd_pct"] if g["mdd_pct"] is None else max(g["mdd_pct"], b["mdd_pct"])
        for t in get_bot_trades(b["bot_id"]):
            if isinstance(t.get("pnl"), (int, float)):
                g["closed"] += 1
                g["wins"] += t["pnl"] > 0
                g["gain"] += max(t["pnl"], 0.0)
                g["loss"] += max(-t["pnl"], 0.0)
    g["pnl_usd"] = round(g["pnl_usd"], 4)
    g["pnl_pct"] = round(g["pnl_usd"] / g["capital"] * 100, 4) if g["capital"] else None
    return g


@overview_router.get("/overview")
def get_overview() -> Dict[str, Any]:
    rows = [x for x in (_bt_row(j) for j in batch_jobs.list_jobs(500, "book_backtest") if j.get("status") == "done") if x]
    bt = {"runs": len(rows), "closed": 0, "wins": 0, "gain": 0.0, "loss": 0.0}
    for r in rows:
        a = _bt_trades(r["id"])
        if a:
            bt["closed"] += a["n"]; bt["wins"] += a["wins"]; bt["gain"] += a["gain"]; bt["loss"] += a["loss"]
    rets = [r["ret_pct"] for r in rows if isinstance(r.get("ret_pct"), (int, float))]
    mdds = [r["mdd_pct"] for r in rows if isinstance(r.get("mdd_pct"), (int, float))]
    bt["avg_ret_pct"] = round(sum(rets) / len(rets), 4) if rets else None
    bt["mdd_pct"] = max(mdds) if mdds else None
    pnl = [r["pnl_usd"] for r in rows if isinstance(r.get("pnl_usd"), (int, float))]
    bt["pnl_usd"] = round(sum(pnl), 2) if pnl else None
    bots = list_bots()
    paper, live = _group(bots, True), _group(bots, False)
    parts = (bt, paper, live)
    closed = sum(p["closed"] for p in parts)
    gain, loss = sum(p["gain"] for p in parts), sum(p["loss"] for p in parts)
    all_mdd = [m for m in (bt["mdd_pct"], paper["mdd_pct"], live["mdd_pct"]) if m is not None]
    for p in parts:
        p["win_pct"] = round(p["wins"] / p["closed"] * 100, 2) if p["closed"] else None
        p["gain"], p["loss"] = round(p["gain"], 4), round(p["loss"], 4)
    bot_n = paper["bots"] + live["bots"]
    total = {"active_bots": paper["running"] + live["running"], "runs": bt["runs"] + bot_n, "trades": closed,
             "win_pct": round(sum(p["wins"] for p in parts) / closed * 100, 2) if closed else None,
             "profit_factor": round(gain / loss, 3) if loss > 0 else None,
             "bot_pnl_usd": round(paper["pnl_usd"] + live["pnl_usd"], 4) if bot_n else None,
             "avg_bt_ret_pct": bt["avg_ret_pct"], "max_mdd_pct": max(all_mdd) if all_mdd else None}
    return {"total": total, "backtest": bt, "paper": paper, "live": live}


# ─── Đánh giá tổng hợp: mỗi lần backtest và mỗi bot là một chuỗi lợi suất ngày, gộp đều theo ngày ───
_DAY = 86_400_000
_SRC_CACHE: Dict[str, Any] = {}     # khoá nguồn -> (mtime, chuỗi lợi suất ngày | None)
_SERIES_CACHE: Dict[str, Any] = {}


def _daily_returns(times, equity, base: float) -> Optional[pd.Series]:
    """Đường vốn (ms, equity) -> lợi suất ngày (đóng cuối ngày UTC; ngày thiếu giữ nguyên = lợi suất 0). `base`: vốn đầu để tính ngày đầu."""
    if len(times) < 2 or not base or base <= 0:
        return None
    df = pd.Series(np.asarray(equity, dtype=float), index=(np.asarray(times, dtype=np.int64) // _DAY)).groupby(level=0).last()
    df = df.reindex(range(int(df.index[0]), int(df.index[-1]) + 1)).ffill()
    prev = df.shift(1)
    prev.iloc[0] = base
    r = (df / prev - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    return r if len(r) else None


def _src_backtest(job_id: str) -> Optional[pd.Series]:
    path = os.path.join(batch_jobs.job_dir(job_id), "result.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _SRC_CACHE.get("bt:" + job_id)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            eq = json.load(fh).get("equity_curve") or []
    except (OSError, ValueError):
        return None
    r = _daily_returns([e["time"] for e in eq], [e["equity"] for e in eq], eq[0]["equity"]) if len(eq) > 1 else None
    _SRC_CACHE["bt:" + job_id] = (mt, r)
    return r


def _src_bot(bot_id: str) -> Optional[pd.Series]:
    b_dir = find_bot_dir(bot_id)
    if not b_dir:
        return None
    try:
        mt = os.path.getmtime(os.path.join(b_dir, "equity.jsonl"))
    except OSError:
        return None
    hit = _SRC_CACHE.get("bot:" + bot_id)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(os.path.join(b_dir, "bot.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        snap = led.snapshot(b_dir, meta)       # chỉ đọc
    except (OSError, ValueError):
        return None
    ser = snap.get("series") or []
    r = _daily_returns([x["time"] for x in ser], [x["equity"] for x in ser], snap.get("capital")) if ser else None
    _SRC_CACHE["bot:" + bot_id] = (mt, r)
    return r


def _rolling_sharpe(r: np.ndarray, w: int):
    out = []
    for i in range(len(r)):
        v = nstats.returns_stats(r[i - w + 1:i + 1], keys=("sharpe",))["sharpe"] if i >= w - 1 else None
        out.append(round(v, 4) if v is not None else None)
    return out


def _monthly(dates: pd.DatetimeIndex, nav: np.ndarray) -> list:
    s = pd.Series(nav, index=dates)
    ym = s.groupby([s.index.year, s.index.month]).last()
    out, prev = [], 10000.0
    for (y, m), v in ym.items():
        out.append({"y": int(y), "m": int(m), "ret": round((float(v) / prev - 1.0) * 100.0, 4)})
        prev = float(v)
    return out


@overview_router.get("/overview/series")
def get_overview_series() -> Dict[str, Any]:
    """Đường NAV tổng hợp: trung bình đều lợi suất ngày của mọi nguồn (backtest xong + bot Paper/Live) có dữ liệu ngày đó."""
    srcs, n_bt, n_paper, n_live = [], 0, 0, 0
    for j in batch_jobs.list_jobs(500, "book_backtest"):
        if j.get("status") == "done":
            r = _src_backtest(j["id"])
            if r is not None:
                srcs.append(r); n_bt += 1
    for b in list_bots():
        r = _src_bot(b["bot_id"])
        if r is not None:
            srcs.append(r)
            if b.get("mode") == "paper":
                n_paper += 1
            else:
                n_live += 1
    key = f"{len(srcs)}:{sum(len(x) for x in srcs)}:{sum(float(x.iloc[-1]) for x in srcs):.10f}"
    hit = _SERIES_CACHE.get("v")
    if hit and hit[0] == key:
        return hit[1]
    meta = {"sources": {"backtest": n_bt, "paper": n_paper, "live": n_live, "total": len(srcs)}}
    if not srcs:
        return {**meta, "dates": [], "available": False}
    df = pd.concat(srcs, axis=1)
    cnt = df.notna().sum(axis=1)
    r = df.mean(axis=1, skipna=True).dropna().sort_index()
    cnt = cnt.reindex(r.index)
    idx = pd.to_datetime(r.index.to_numpy() * _DAY, unit="ms")
    nav = 10000.0 * np.cumprod(1.0 + r.to_numpy())
    peak = np.maximum.accumulate(np.r_[10000.0, nav])[1:]
    dd = (nav / peak - 1.0) * 100.0
    bench = None
    bc = daily_close("BTC@perp", int(time.time() * 1000))
    if bc is not None:
        lab = pd.Series(bc[1], index=(bc[0] - _DAY) // _DAY)
        lab = lab[~lab.index.duplicated(keep="last")]
        b = lab.reindex(r.index).ffill()
        if b.notna().any() and float(b.dropna().iloc[0]) > 0:
            b = b.bfill()
            bench = [round(float(x), 2) for x in 10000.0 * b.to_numpy() / float(b.iloc[0])]
    ra = r.to_numpy()
    st = nstats.returns_stats(ra, keys=("sharpe", "sortino", "cagr"))
    pct = lambda v: round(v * 100.0, 4) if v is not None else None
    rnd = lambda v: round(v, 4) if v is not None else None
    out = {**meta, "available": True, "dates": [f"{d:%Y-%m-%d}" for d in idx], "nav": [round(float(x), 2) for x in nav],
           "drawdown": [round(float(x), 4) for x in dd], "benchmark_nav": bench, "benchmark": "BTC",
           "monthly": _monthly(idx, nav), "rolling_sharpe": {"d30": _rolling_sharpe(ra, 30), "d90": _rolling_sharpe(ra, 90)},
           "active_sources": [int(x) for x in cnt.to_numpy()],
           "kpi": {"ret_pct": round(float(nav[-1] / 10000.0 - 1.0) * 100.0, 4), "cagr_pct": pct(st["cagr"]), "mdd_pct": round(float(dd.min()), 4),
                   "sharpe": rnd(st["sharpe"]), "sortino": rnd(st["sortino"]), "win_days_pct": round(float((ra > 0).mean()) * 100.0, 2),
                   "bench_ret_pct": round(bench[-1] / 10000.0 * 100.0 - 100.0, 4) if bench else None}}
    _SERIES_CACHE["v"] = (key, out)
    return out



"""Routes quản lý người dùng và phiên đăng nhập (P17 T2 B2).

Endpoints:
- GET /api/users: danh sách công khai kèm số chiến lược n_strategies
- POST /api/users: tạo người dùng mới, tự động đăng nhập (set cookie)
- GET /api/users/{handle}: thông tin một người dùng
- GET /api/users/{handle}/strategies: danh sách chiến lược của người dùng
- GET /api/me: thông tin người dùng hiện tại (trả {user: null} nếu chưa đăng nhập)
- POST /api/me/enter: chỉ nhập tên, có thì vào, chưa có thì tạo
- POST /api/me/login: đăng nhập không mật khẩu bằng handle
- POST /api/me/logout: đăng xuất, xóa cookie
- PUT /api/me: cập nhật hồ sơ cá nhân (yêu cầu đăng nhập)
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend import users
from backend.analys.alpha import strategies as store

users_router = APIRouter(tags=["users"])



def _get_cookie_key_for_request(request: Request) -> str:
    """Xác định đúng key cookie theo ứng dụng và host: cô lập hoàn toàn giữa edu và coin."""
    app_title = str(getattr(getattr(request, "app", None), "title", ""))
    host = (request.headers.get("host") or "").lower()
    if "EDU" in app_title or "edu." in host:
        return "edu_session"
    if "COIN" in app_title or "coin." in host:
        return "coin_session"
    return "nora_uid"


def current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Dependency lấy thông tin người dùng từ cookie phiên cô lập theo product.
    Tuyệt đối không fallback chéo giữa edu_session và coin_session.
    """
    cookie_key = _get_cookie_key_for_request(request)
    cookie_val = request.cookies.get(cookie_key)
    if not cookie_val and cookie_key == "nora_uid":
        # Chỉ trong monolith cũ mới fallback
        cookie_val = request.cookies.get("nora_uid")
    if not cookie_val:
        return None
    uid = users.verify_uid(cookie_val)
    if not uid:
        return None
    return users.get_user(uid)


def set_uid_cookie(response: Response, user_id: str, request: Request) -> None:
    """Ghi cookie phiên có chữ ký HMAC (host-only, HttpOnly, SameSite lax), cô lập theo product."""
    cookie_val = users.sign_uid(user_id)
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    cookie_key = _get_cookie_key_for_request(request)

    response.set_cookie(
        key=cookie_key,
        value=cookie_val,
        max_age=31536000,
        httponly=True,
        samesite="lax",
        path="/",
        secure=is_https,
    )


def clear_uid_cookie(response: Response) -> None:
    """Xóa cookie phiên tương ứng (xóa cả 3 để dọn dẹp sạch)."""
    for key in ["nora_uid", "edu_session", "coin_session"]:
        response.delete_cookie(key=key, path="/")


# ─── Schema Pydantic ─────────────────────────────────────────────────────────

class CreateUserReq(BaseModel):
    handle: Optional[str] = Field(None, min_length=3, max_length=20)
    display_name: str = Field(..., min_length=1, max_length=40)
    bio: str = Field("", max_length=200)
    avatar: Optional[Dict[str, str]] = None


class EnterReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)


class LoginReq(BaseModel):
    handle: str


class UpdateProfileReq(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=40)
    avatar: Optional[Dict[str, str]] = None
    bio: Optional[str] = Field(None, max_length=200)


# ─── Endpoints ──────────────────────────────────────────────────────────────

@users_router.get("/api/users")
def get_users_list() -> List[Dict[str, Any]]:
    """Danh sách người dùng công khai kèm số chiến lược đã lưu."""
    raw_users = users.list_users()
    counts = store.count_by_owner()
    out = []
    for u in raw_users:
        out.append({
            "id": u.get("id"),
            "handle": u.get("handle"),
            "display_name": u.get("display_name"),
            "avatar": u.get("avatar"),
            "bio": u.get("bio", ""),
            "role": u.get("role", "learner"),
            "n_strategies": counts.get(u.get("id", ""), 0),
            "created_at": u.get("created_at"),
        })
    return out


@users_router.post("/api/users")
def create_new_user(req: CreateUserReq, request: Request, response: Response) -> Dict[str, Any]:
    """Tạo người dùng mới và tự động đăng nhập."""
    try:
        u = users.create_user(
            handle=req.handle or users.unique_handle(req.display_name),
            display_name=req.display_name,
            avatar=req.avatar,
            bio=req.bio,
        )
    except ValueError as err:
        msg = str(err)
        if "đã tồn tại" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    set_uid_cookie(response, u["id"], request)
    return u


@users_router.get("/api/users/{handle}")
def get_user_profile(handle: str) -> Dict[str, Any]:
    """Thông tin hồ sơ một người dùng theo handle."""
    u = users.get_by_handle(handle)
    if not u:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    counts = store.count_by_owner()
    return {
        "id": u.get("id"),
        "handle": u.get("handle"),
        "display_name": u.get("display_name"),
        "avatar": u.get("avatar"),
        "bio": u.get("bio", ""),
        "role": u.get("role", "learner"),
        "n_strategies": counts.get(u.get("id", ""), 0),
        "created_at": u.get("created_at"),
    }


@users_router.get("/api/users/{handle}/strategies")
def get_user_strategies(handle: str) -> List[Dict[str, Any]]:
    """Chiến lược người dùng đã lưu (chỉ lấy các bản ghi có owner khớp)."""
    u = users.get_by_handle(handle)
    if not u:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    return store.list_user_alphas(owner_id=u["id"])


@users_router.get("/api/me")
def get_current_me(request: Request) -> Dict[str, Any]:
    """Thông tin phiên người dùng hiện tại (trả {user: null} nếu chưa đăng nhập)."""
    me = current_user(request)
    return {"user": me}


@users_router.post("/api/me/login")
def login_with_handle(req: LoginReq, request: Request, response: Response) -> Dict[str, Any]:
    """Đăng nhập không mật khẩu bằng handle."""
    u = users.get_by_handle(req.handle)
    if not u:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy người dùng @{req.handle}")
    set_uid_cookie(response, u["id"], request)
    return {"user": u}


@users_router.post("/api/me/enter")
def enter_with_name(req: EnterReq, request: Request, response: Response) -> Dict[str, Any]:
    """Chỉ cần tên: có người dùng trùng tên thì vào luôn, chưa có thì tạo mới."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Vui lòng nhập tên")
    u = users.get_by_display_name(name)
    if not u:
        try:
            u = users.create_user(handle=users.unique_handle(name), display_name=name)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err))
    set_uid_cookie(response, u["id"], request)
    return {"user": u}


@users_router.post("/api/me/logout")
def logout_current_me(response: Response) -> Dict[str, Any]:
    """Đăng xuất, xóa cookie phiên."""
    clear_uid_cookie(response)
    return {"ok": True}


@users_router.put("/api/me")
def update_current_me(
    req: UpdateProfileReq,
    request: Request,
    me: Optional[Dict[str, Any]] = Depends(current_user),
) -> Dict[str, Any]:
    """Cập nhật thông tin tài khoản đang đăng nhập."""
    if not me:
        raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập để cập nhật hồ sơ")

    fields = {}
    if req.display_name is not None:
        fields["display_name"] = req.display_name
    if req.avatar is not None:
        fields["avatar"] = req.avatar
    if req.bio is not None:
        fields["bio"] = req.bio

    try:
        updated = users.update_user(me["id"], **fields)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))

    return updated


"""Routes Market Education (P17 T3): lưới user, chiến lược theo user, chi tiết công khai, mẫu hướng dẫn.

Mọi số liệu tính từ kết quả Nautilus đã lưu trong alpha người dùng — không số giả.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from backend import users
from backend.analys.alpha import store


edu_router = APIRouter(prefix="/api/edu", tags=["edu"])



def _public_user(u: Dict[str, Any]) -> Dict[str, Any]:
    return {k: u.get(k) for k in ("id", "handle", "display_name", "avatar", "bio", "role", "created_at")}


_MARKET: Dict[str, Any] = {"sig": None, "rows": []}


def _market_rows() -> list:
    """Hàng user + tổng hợp, cache theo chữ ký thư mục alpha/user và users."""
    sig = store.dir_signature(store.get_user_alphas_dir(), users.users_dir())
    if _MARKET["sig"] != sig:
        idx = store.card_index()
        rows = []
        for u in users.list_users():
            user_cards = idx.get(u["id"], [])
            rows.append({**_public_user(u), **store.aggregate_cards(user_cards)})
        _MARKET["rows"] = rows
        _MARKET["sig"] = sig
    return _MARKET["rows"]


@edu_router.on_event("startup")
def _warm() -> None:
    import threading
    threading.Thread(target=_market_rows, daemon=True).start()


@edu_router.get("/market")
def market(request: Request, sort: str = "pnl") -> Dict[str, Any]:
    """Lưới user kèm tổng hợp: số chiến lược, tổng PnL, MDD lớn nhất, chiến lược tốt nhất. sort: pnl | new | name."""
    rows = list(_market_rows())
    me = current_user(request) if request else None
    if me:
        rows = [r for r in rows if r.get("id") != me.get("id") and r.get("handle") != me.get("handle")]
    if sort == "name":
        rows.sort(key=lambda r: (r.get("display_name") or "").lower())
    elif sort == "new":
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    else:
        rows.sort(key=lambda r: (r["total_pnl_usd"] is None, -(r["total_pnl_usd"] or 0)))
    return {"users": rows}


@edu_router.get("/users/{handle}")
def user_strategies(handle: str, request: Request) -> Dict[str, Any]:
    u = users.get_by_handle(handle)
    if not u:
        raise HTTPException(404, "Không tìm thấy người dùng")
    cards = store.owner_strategy_cards(u["id"])
    cards.sort(key=lambda c: (c["ret_pct"] is None, -(c["ret_pct"] or 0)))
    return {"user": _public_user(u), "summary": store.aggregate_cards(cards), "strategies": cards}


@edu_router.get("/strategies/{alpha_id}")
def strategy_detail(alpha_id: str) -> Dict[str, Any]:
    """Chi tiết công khai (chỉ đọc): code + kết quả + chủ sở hữu."""
    rec = store.get_user_alpha(alpha_id)
    if not rec or rec.get("status") == "ARCHIVED" or not rec.get("owner_id"):
        raise HTTPException(404, "Không tìm thấy chiến lược")
    owner = users.get_user(rec["owner_id"])
    card = store.strategy_card(rec, store._sample_meta())
    return {
        "id": rec["id"], "name": rec.get("name"), "code": rec.get("code"),
        "result": rec.get("result"), "card": card,
        "owner": _public_user(owner) if owner else None,
    }


@edu_router.post("/strategies/{alpha_id}/fork")
def fork_strategy(alpha_id: str, request: Request) -> Dict[str, Any]:
    """(Đăng nhập) sao chép code về user hiện tại: tạo bản nháp (chưa có kết quả) để mở Studio."""
    me = current_user(request)
    if not me:
        raise HTTPException(401, "Cần đăng nhập để sao chép chiến lược")
    rec = store.get_user_alpha(alpha_id)
    if not rec or rec.get("status") == "ARCHIVED" or not rec.get("owner_id"):
        raise HTTPException(404, "Không tìm thấy chiến lược")
    owner = users.get_user(rec["owner_id"])
    owner_tag = f"@{owner.get('handle')}" if (owner and owner.get("handle")) else (owner.get("display_name") if owner else "")
    suffix = f" (bản sao từ {owner_tag})" if owner_tag else " (bản sao)"
    return {
        "ok": True,
        "draft": {
            "name": f"{rec.get('name', 'Chiến lược')}{suffix}",
            "code": rec.get("code", ""),
            "forked_from": {
                "alpha_id": rec["id"],
                "owner_handle": owner.get("handle") if owner else None,
                "owner_name": owner.get("display_name") if owner else None,
            },
        },
    }


@edu_router.get("/samples/visible")
def samples_visible(request: Request) -> Dict[str, Any]:
    """Khách hoặc user chưa lưu chiến lược nào -> đúng 1 mẫu hướng dẫn; user đã có >= 1 chiến lược -> không mẫu."""
    me: Optional[Dict[str, Any]] = current_user(request)
    show = me is None or store.count_by_owner().get(me["id"], 0) == 0
    sample = store.guide_sample() if show else None
    return {"show_samples": bool(show and sample), "samples": [sample] if show and sample else []}


ROUTERS = [engine_router, home_router, overview_router, users_router, edu_router]
