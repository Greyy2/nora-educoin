"""Chỉ số đánh giá hiệu quả — MDD, Sharpe, Sortino, Calmar, Profit Factor…

Tính từ đường vốn (lab_track_balance) và danh sách lệnh (lab_results).
Đường vốn có tới 854 nghìn điểm nên lấy mẫu theo ngày trước khi tính,
vừa nhanh vừa đúng chuẩn ngành (chỉ số rủi ro tính trên lợi suất ngày).
"""
import math
import time

import datetime

from ...db import fetch_all, fetch_one, stream_rows as stream

# Bộ nhớ đệm cho các truy vấn nặng (quét toàn bảng 9 triệu dòng).
# Dashboard không cần số liệu tức thời nên đệm 10 phút là hợp lý.
_cache = {}


def _cached(key: str, ttl: int, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def quet_duong_von(run_id: int):
    """Duyệt đường vốn đúng MỘT lần, lấy ra cả ba thứ cần cho mọi chỉ số.

      - vốn ban đầu: điểm đầu tiên của đường vốn.
        Engine lấy vốn khởi điểm từ lab_account_balance rồi cộng dồn lãi lỗ vào
        chính cột đó (AccountImp: originBalance = lab_account_balance, sau đó
        lab_account_balance += profit), nên chạy xong là không đọc ngược ra vốn
        ban đầu được nữa. Điểm đầu đường vốn là mốc trung thực nhất còn lại.
        Lấy số dư cuối NGÀY đầu làm gốc như trước là lệch hẳn một phiên: với lần
        chạy 3379 nó biến 137% thành 164%.

      - số dư cuối mỗi ngày, cắt ngày theo UTC (time // 86400000). Không dùng
        FROM_UNIXTIME vì hàm đó cắt theo múi giờ máy chủ MySQL (ở đây +07) —
        dời máy chủ là Sharpe/CAGR/MDD đổi số mà không ai biết vì sao.

      - sụt giảm tối đa trên ĐÚNG đường vốn đầy đủ. Tính trên số dư cuối ngày sẽ
        bỏ lọt các cú tụt trong ngày rồi hồi lại trước khi đóng cửa, tức là luôn
        báo rủi ro nhẹ hơn thực tế.

    Đường vốn có gần một triệu điểm nên đọc theo luồng, và gộp cả ba phép tính
    vào một lượt thay vì quét ba lần.
    """
    # Engine cập nhật lab_account_balance trong khi chạy, còn margin_balance
    # giữ vốn cấu hình ban đầu. Dùng nó làm mốc nếu có; chỉ fallback về tick
    # đầu cho các account cũ thiếu margin_balance.
    account = fetch_one(
        "SELECT lab_account_margin_balance AS initial_margin FROM lab_account "
        "WHERE lab_account_id = %s", (run_id,)) or {}
    von_dau = account.get("initial_margin")
    if von_dau is not None:
        von_dau = float(von_dau)
    ngay_hien_tai = None
    dong_cua = None
    theo_ngay = []

    dinh = None
    mdd = mdd_abs = 0.0
    dinh_t = day_t = dinh_hien_tai = None

    for t, b in stream(
        """SELECT lab_track_bl_time, lab_track_bl_balance FROM lab_track_balance
           WHERE lab_track_bl_account = %s ORDER BY lab_track_bl_time""",
        (run_id,),
    ):
        v = float(b or 0)
        if von_dau is None:
            von_dau = v

        ngay = int(t) // 86400000
        if ngay_hien_tai is None:
            ngay_hien_tai = ngay
        elif ngay != ngay_hien_tai:
            theo_ngay.append((ngay_hien_tai, dong_cua))
            ngay_hien_tai = ngay
        dong_cua = v

        if dinh is None or v > dinh:
            dinh, dinh_hien_tai = v, t
        elif dinh > 0:
            d = (dinh - v) / dinh * 100
            if d > mdd:
                mdd, mdd_abs = d, dinh - v
                dinh_t, day_t = dinh_hien_tai, t

    if ngay_hien_tai is not None:
        theo_ngay.append((ngay_hien_tai, dong_cua))

    eq = [{"ngay": datetime.datetime.utcfromtimestamp(n * 86400).date(), "balance": v}
          for n, v in theo_ngay]

    def ngay_cua(ms):
        return (datetime.datetime.utcfromtimestamp(int(ms) / 1000).date().isoformat()
                if ms else None)

    # Không có điểm nào thì mọi risk metric đều unavailable. Vốn cấu hình
    # vẫn có thể trả về cho phần đầu/cuối, nhưng không được biến thiếu equity
    # thành "sụt giảm 0%".
    if not eq:
        return von_dau, [], {"mdd_pct": None, "mdd_abs": None,
                             "peak_at": None, "trough_at": None}

    dd = {"mdd_pct": round(mdd, 2), "mdd_abs": round(mdd_abs, 2),
          "peak_at": ngay_cua(dinh_t), "trough_at": ngay_cua(day_t)}
    return von_dau, eq, dd


def drawdown(equity):
    """Sụt giảm tối đa: khoảng rơi sâu nhất từ đỉnh đã đạt.

    Trả về phần trăm, giá trị tuyệt đối, đỉnh, đáy và ngày xảy ra.
    """
    peak = None
    max_dd = 0.0
    max_dd_abs = 0.0
    peak_at = trough_at = None
    cur_peak_at = None

    for row in equity:
        v = float(row["balance"])
        if peak is None or v > peak:
            peak = v
            cur_peak_at = row["ngay"]
            continue
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
                max_dd_abs = peak - v
                peak_at = cur_peak_at
                trough_at = row["ngay"]

    return {
        "mdd_pct": round(max_dd, 2),
        "mdd_abs": round(max_dd_abs, 2),
        "peak_at": str(peak_at) if peak_at else None,
        "trough_at": str(trough_at) if trough_at else None,
    }


def _returns(equity, von_dau=None):
    """Lợi suất ngày, bỏ qua các ngày số dư bằng 0.

    Ngày đầu tiên phải được đo từ vốn ban đầu, không phải từ chính nó — bỏ qua
    ngày đó là mất luôn phiên giao dịch đầu, thường là phiên biến động nhất.
    """
    out = []
    prev = float(von_dau) if von_dau is not None else None
    for row in equity:
        v = float(row["balance"])
        if prev is not None and prev > 0:
            out.append((v - prev) / prev)
        prev = v
    return out


def risk_ratios(equity, rf_annual: float = 0.0, von_dau: float = None, mdd_pct: float = None):
    """Sharpe, Sortino, Calmar — quy đổi theo năm (365 ngày giao dịch crypto)."""
    rets = _returns(equity, von_dau)
    n = len(rets)
    if n < 2:
        return {"sharpe": None, "sortino": None, "calmar": None,
                "volatility_pct": None, "cagr_pct": None, "so_ngay": n,
                "du_dai_de_quy_nam": False}

    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    sd = math.sqrt(var)
    P = 365  # crypto giao dịch mọi ngày
    rf_daily = rf_annual / P

    sharpe = ((mean - rf_daily) / sd) * math.sqrt(P) if sd > 0 else None

    downs = [r for r in rets if r < 0]
    if downs:
        dsd = math.sqrt(sum(r ** 2 for r in downs) / len(downs))
        sortino = ((mean - rf_daily) / dsd) * math.sqrt(P) if dsd > 0 else None
    else:
        sortino = None

    # Tăng trưởng kép quy năm. Dưới 30 ngày thì phép quy đổi này vô nghĩa:
    # lãi một tuần nâng lũy thừa 52 lần cho ra những con số hàng nghìn tỷ phần
    # trăm, và Calmar ăn theo cũng hỏng. Thà không có số còn hơn có số sai.
    du_dai = n >= 30
    first = float(von_dau if von_dau is not None else equity[0]["balance"])
    last = float(equity[-1]["balance"])
    years = n / P
    if du_dai and first > 0 and last > 0 and years > 0:
        cagr = ((last / first) ** (1 / years) - 1) * 100
    else:
        cagr = None

    # Calmar phải chia cho sụt giảm của ĐÚNG đường vốn đầy đủ; lấy theo số dư
    # cuối ngày thì mẫu số nhỏ đi, Calmar đẹp lên một cách giả tạo.
    sut = mdd_pct if mdd_pct is not None else drawdown(equity)["mdd_pct"]
    calmar = (cagr / sut) if (cagr is not None and sut and sut > 0) else None

    return {
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "sortino": round(sortino, 2) if sortino is not None else None,
        "calmar": round(calmar, 2) if calmar is not None else None,
        "volatility_pct": round(sd * math.sqrt(P) * 100, 2),
        "cagr_pct": round(cagr, 2) if cagr is not None else None,
        "so_ngay": n,
        "du_dai_de_quy_nam": du_dai,
    }


def trade_metrics(run_id: int):
    """Chỉ số tính từ danh sách lệnh: profit factor, expectancy, chuỗi thắng/thua."""
    r = fetch_one(
        """SELECT COUNT(*) AS trades,
                  SUM(lab_result_realpnl > 0)                       AS wins,
                  SUM(lab_result_realpnl < 0)                       AS losses,
                  ROUND(SUM(CASE WHEN lab_result_realpnl > 0 THEN lab_result_realpnl ELSE 0 END), 2) AS gross_profit,
                  ROUND(ABS(SUM(CASE WHEN lab_result_realpnl < 0 THEN lab_result_realpnl ELSE 0 END)), 2) AS gross_loss,
                  ROUND(SUM(lab_result_realpnl), 2)                 AS net,
                  ROUND(AVG(lab_result_realpnl), 3)                 AS expectancy,
                  ROUND(MAX(lab_result_realpnl), 2)                 AS best,
                  ROUND(MIN(lab_result_realpnl), 2)                 AS worst,
                  ROUND(STDDEV(lab_result_realpnl), 3)              AS pnl_sd
           FROM lab_results WHERE lab_result_account = %s""",
        (run_id,),
    )
    if not r or not r["trades"]:
        return None

    gp = float(r["gross_profit"] or 0)
    gl = float(r["gross_loss"] or 0)
    r["profit_factor"] = round(gp / gl, 2) if gl > 0 else None
    r["winrate"] = round(100 * (r["wins"] or 0) / r["trades"], 1)

    # chuỗi thắng / thua dài nhất — duyệt theo thứ tự thời gian
    rows = fetch_all(
        """SELECT lab_result_realpnl > 0 AS win FROM lab_results
           WHERE lab_result_account = %s ORDER BY lab_result_chart""",
        (run_id,),
    )
    best_w = best_l = cur_w = cur_l = 0
    for row in rows:
        if row["win"]:
            cur_w += 1
            cur_l = 0
            best_w = max(best_w, cur_w)
        else:
            cur_l += 1
            cur_w = 0
            best_l = max(best_l, cur_l)
    r["max_win_streak"] = best_w
    r["max_loss_streak"] = best_l
    return r


def full_metrics(run_id: int):
    """Bộ chỉ số đầy đủ cho một lần chạy — dùng cho bảng chi tiết khi bấm vào."""
    von_dau, eq, dd = quet_duong_von(run_id)
    tm = trade_metrics(run_id) or {}
    rr = risk_ratios(eq, von_dau=von_dau, mdd_pct=dd.get("mdd_pct")) if eq else {}

    # `von_dau` là điểm đầu tiên của đường vốn đầy đủ; phải dùng is not None
    # để không biến một vốn hợp lệ bằng 0 thành giá trị thiếu.
    start_bal = von_dau if von_dau is not None else (float(eq[0]["balance"]) if eq else None)
    end_bal = float(eq[-1]["balance"]) if eq else None
    roi = ((end_bal - start_bal) / start_bal * 100) if (start_bal is not None and start_bal > 0) else None

    return {
        **tm, **dd, **rr,
        # Lần chạy không bật theo dõi số dư thì mọi chỉ số rủi ro đều vô nghĩa —
        # nói rõ ra để giao diện giải thích, thay vì hiện một bảng toàn dấu gạch.
        "co_duong_von": bool(eq),
        "start_balance": round(start_bal, 2) if start_bal is not None else None,
        "end_balance": round(end_bal, 2) if end_bal is not None else None,
        "roi_pct": round(roi, 2) if roi is not None else None,
        # Chèn vốn ban đầu làm điểm mở đầu để đường vốn và các con số cùng một gốc
        "equity_daily": (
            ([{"ngay": str(eq[0]["ngay"] - datetime.timedelta(days=1)),
               "balance": round(start_bal, 2)}] if (eq and start_bal is not None) else [])
            + [{"ngay": str(e["ngay"]), "balance": round(float(e["balance"]), 2)} for e in eq]
        ),
    }


def _dashboard_raw():
    acc = fetch_one("SELECT COUNT(*) AS n FROM lab_account")
    stg = fetch_one(
        """SELECT COUNT(*) AS tong,
                  SUM(lab_strategy_container = 1) AS container
           FROM lab_strategies"""
    )
    opt = fetch_one("SELECT COUNT(*) AS n FROM lab_optimization")
    groups = fetch_all(
        """SELECT lab_strategy_group AS ten, COUNT(*) AS n FROM lab_strategies
           WHERE lab_strategy_group IS NOT NULL AND lab_strategy_group <> ''
           GROUP BY lab_strategy_group ORDER BY n DESC LIMIT 8"""
    )
    # Chỉ lấy các lần chạy gần đây — tránh gộp toàn bộ 9 triệu lệnh
    recent = fetch_all(
        """SELECT a.lab_account_id AS run_id, a.lab_account_name AS name,
                  a.lab_account_group AS `group`, a.lab_account_balance AS balance,
                  a.lab_account_running AS running
           FROM lab_account a
           ORDER BY a.lab_account_id DESC LIMIT 12"""
    )
    if recent:
        ids = tuple(r["run_id"] for r in recent)
        ph = ",".join(["%s"] * len(ids))
        agg = {
            x["a"]: x
            for x in fetch_all(
                f"""SELECT lab_result_account AS a, COUNT(*) AS trades,
                           ROUND(SUM(lab_result_realpnl), 2) AS pnl,
                           ROUND(100.0 * SUM(lab_result_realpnl > 0) / COUNT(*), 1) AS winrate
                    FROM lab_results WHERE lab_result_account IN ({ph})
                    GROUP BY lab_result_account""",
                list(ids),
            )
        }
        for r in recent:
            a = agg.get(r["run_id"], {})
            r["trades"] = a.get("trades", 0)
            r["pnl"] = a.get("pnl")
            r["winrate"] = a.get("winrate")

    co_kq = fetch_one(
        """SELECT COUNT(*) AS n FROM lab_account a
           WHERE EXISTS (SELECT 1 FROM lab_results r
                         WHERE r.lab_result_account = a.lab_account_id LIMIT 1)"""
    )
    # Đường tăng trưởng lấy từ lần chạy mới nhất có kết quả — gộp cả 9 triệu
    # lệnh của mọi lần chạy thì dashboard đứng hình, mà cũng chẳng nói lên gì.
    moi_nhat = fetch_one(
        """SELECT lab_result_account AS run_id, COUNT(*) AS n
           FROM lab_results
           WHERE lab_result_account = (SELECT MAX(lab_result_account) FROM lab_results)
           GROUP BY lab_result_account"""
    )
    tang_truong, run_tt = [], None
    if moi_nhat:
        run_tt = fetch_one(
            "SELECT lab_account_id AS id, lab_account_name AS name FROM lab_account "
            "WHERE lab_account_id = %s", (moi_nhat["run_id"],))
        thang = fetch_all(
            """SELECT DATE_FORMAT(FROM_UNIXTIME(lab_result_chart / 1000), '%%Y-%%m') AS thang,
                      ROUND(SUM(lab_result_realpnl), 2) AS pnl,
                      COUNT(*) AS so_lenh
               FROM lab_results
               WHERE lab_result_account = %s AND lab_result_chart > 0
               GROUP BY thang ORDER BY thang""",
            (moi_nhat["run_id"],))
        cong_don = 0.0
        for t in thang:
            cong_don += float(t["pnl"] or 0)
            tang_truong.append({"thang": t["thang"], "pnl": t["pnl"],
                                "so_lenh": t["so_lenh"], "cong_don": round(cong_don, 2)})

    return {
        "runs": acc["n"] if acc else 0,
        "runs_co_ket_qua": co_kq["n"] if co_kq else 0,
        "strategies": stg["tong"] if stg else 0,
        "containers": stg["container"] if stg else 0,
        "optimizations": opt["n"] if opt else 0,
        "groups": groups,
        "recent_runs": recent,
        "tang_truong": tang_truong,
        "tang_truong_run": run_tt,
    }


def dashboard_summary():
    """Tổng quan hệ thống — đệm 10 phút vì có truy vấn nặng."""
    return _cached("dashboard", 600, _dashboard_raw)


def full_metrics_cached(run_id: int):
    """Chỉ số đầy đủ, đệm 5 phút — mỗi lần tính mất khoảng 4 giây."""
    return _cached(f"metrics:{run_id}", 300, lambda: full_metrics(run_id))
