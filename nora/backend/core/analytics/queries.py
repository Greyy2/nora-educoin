"""Sáu tầng thống kê — mọi phép tính đều làm bằng SQL, không kéo bản ghi về Python.

Tầng 1 overview   — chiến lược lãi hay lỗ
Tầng 2 by_flow    — bộ phận nào của chiến lược tạo ra tiền   ⭐
Tầng 3 behavior   — chiến lược cư xử thế nào
Tầng 4 by_symbol  — coin nào kéo lãi, coin nào kéo lỗ
Tầng 5 timeline   — diễn biến theo thời gian
Tầng 6 insights   — nhận xét tự động rút ra từ 5 tầng trên
"""
from ...db import fetch_all, fetch_one

# Trạng thái lệnh trong hệ cũ
STATUS_LABEL = {
    1: "Chờ khớp",
    2: "Chốt lãi",
    3: "Cắt lỗ",
    4: "Huỷ",
    5: "Khớp một phần",
    6: "Đang chờ",
}


def run_info(run_id: int):
    """Thông tin cấu hình của một lần chạy."""
    row = fetch_one(
        """SELECT lab_account_id AS id, lab_account_name AS name,
                  lab_account_balance AS balance, lab_account_margin_balance AS margin_balance,
                  lab_account_db AS dataset, lab_account_running AS running,
                  lab_account_margin_type AS margin_type, lab_account_data_length AS data_length
           FROM lab_account WHERE lab_account_id = %s""",
        (run_id,),
    )
    if not row:
        return None
    row["campaigns"] = fetch_one(
        "SELECT COUNT(*) AS n FROM lab_campaigns WHERE lab_campaign_account = %s", (run_id,)
    )["n"]
    period = fetch_one(
        """SELECT MIN(lab_campaign_start) AS t1, MAX(lab_campaign_stop) AS t2
           FROM lab_campaigns WHERE lab_campaign_account = %s""",
        (run_id,),
    )
    row["period"] = period
    return row


def overview(run_id: int):
    """Tầng 1 — sáu con số quan trọng nhất."""
    r = fetch_one(
        """SELECT COUNT(*)                                              AS so_lenh,
                  ROUND(SUM(lab_result_realpnl), 2)                     AS pnl,
                  ROUND(100.0 * SUM(lab_result_realpnl > 0) / COUNT(*), 1) AS winrate,
                  COUNT(DISTINCT lab_result_symbol)                     AS so_coin,
                  MAX(lab_result_phase)                                 AS phase_max,
                  ROUND(AVG(lab_result_interval) / 3600000, 1)          AS gio_giu_tb,
                  ROUND(AVG(CASE WHEN lab_result_realpnl > 0 THEN lab_result_realpnl END), 2) AS lai_tb,
                  ROUND(AVG(CASE WHEN lab_result_realpnl < 0 THEN lab_result_realpnl END), 2) AS lo_tb,
                  ROUND(MAX(lab_result_realpnl), 2)                     AS lenh_lai_nhat,
                  ROUND(MIN(lab_result_realpnl), 2)                     AS lenh_lo_nhat
           FROM lab_results WHERE lab_result_account = %s""",
        (run_id,),
    )
    if not r or not r["so_lenh"]:
        return None

    # tỷ lệ lãi/lỗ mỗi lệnh — cho biết ăn lớn thua nhỏ hay ngược lại
    if r["lo_tb"]:
        r["ty_le_lai_lo"] = round(abs(float(r["lai_tb"] or 0) / float(r["lo_tb"])), 2)
    else:
        r["ty_le_lai_lo"] = None

    eq = fetch_one(
        """SELECT ROUND(MIN(lab_track_bl_balance), 2) AS von_thap_nhat,
                  ROUND(MAX(lab_track_bl_balance), 2) AS von_cao_nhat,
                  ROUND(MAX(lab_track_bl_invest), 2)  AS invest_cao_nhat,
                  ROUND(MIN(lab_track_bl_unrealize), 2) AS lo_chua_thuc_hien_max,
                  COUNT(*) AS so_diem
           FROM lab_track_balance WHERE lab_track_bl_account = %s""",
        (run_id,),
    )
    r.update(eq or {})
    return r


def by_flow(run_id: int):
    """Tầng 2 ⭐ — phân rã theo nhánh logic. Chỗ lộ ra bộ phận nào của chiến lược sinh lời."""
    return fetch_all(
        """SELECT lab_result_flow                                        AS flow,
                  COUNT(*)                                               AS so_lenh,
                  ROUND(100.0 * SUM(lab_result_realpnl > 0) / COUNT(*), 1) AS winrate,
                  ROUND(SUM(lab_result_realpnl), 2)                      AS pnl,
                  ROUND(AVG(lab_result_realpnl), 3)                      AS pnl_tb,
                  ROUND(AVG(lab_result_interval) / 3600000, 1)           AS gio_giu_tb,
                  COUNT(DISTINCT lab_result_symbol)                      AS so_coin
           FROM lab_results WHERE lab_result_account = %s
           GROUP BY lab_result_flow ORDER BY pnl DESC""",
        (run_id,),
    )


def behavior(run_id: int):
    """Tầng 3 — chiến lược cư xử thế nào: bậc DCA, kết cục, thời gian giữ."""
    phases = fetch_all(
        """SELECT lab_result_phase AS phase, COUNT(*) AS so_lenh,
                  ROUND(SUM(lab_result_realpnl), 2) AS pnl
           FROM lab_results WHERE lab_result_account = %s
           GROUP BY lab_result_phase ORDER BY phase""",
        (run_id,),
    )
    status = fetch_all(
        """SELECT lab_result_status AS ma, COUNT(*) AS so_lenh,
                  ROUND(SUM(lab_result_realpnl), 2) AS pnl
           FROM lab_results WHERE lab_result_account = %s
           GROUP BY lab_result_status ORDER BY so_lenh DESC""",
        (run_id,),
    )
    for s in status:
        s["ten"] = STATUS_LABEL.get(s["ma"], f"Mã {s['ma']}")

    hold = fetch_all(
        """SELECT CASE
                    WHEN lab_result_interval < 3600000      THEN '< 1 giờ'
                    WHEN lab_result_interval < 14400000     THEN '1–4 giờ'
                    WHEN lab_result_interval < 86400000     THEN '4–24 giờ'
                    WHEN lab_result_interval < 259200000    THEN '1–3 ngày'
                    ELSE '> 3 ngày' END                     AS khoang,
                  COUNT(*) AS so_lenh,
                  ROUND(SUM(lab_result_realpnl), 2) AS pnl
           FROM lab_results WHERE lab_result_account = %s
           GROUP BY khoang ORDER BY MIN(lab_result_interval)""",
        (run_id,),
    )
    side = fetch_all(
        """SELECT CASE lab_result_type WHEN 1 THEN 'LONG' WHEN 2 THEN 'SHORT' ELSE 'KHÁC' END AS huong,
                  COUNT(*) AS so_lenh,
                  ROUND(100.0 * SUM(lab_result_realpnl > 0) / COUNT(*), 1) AS winrate,
                  ROUND(SUM(lab_result_realpnl), 2) AS pnl
           FROM lab_results WHERE lab_result_account = %s
           GROUP BY lab_result_type""",
        (run_id,),
    )
    return {"phases": phases, "status": status, "hold": hold, "side": side}


def by_symbol(run_id: int, limit: int = 100):
    """Tầng 4 — coin nào kéo lãi, coin nào kéo lỗ."""
    return fetch_all(
        """SELECT lab_result_symbol                                      AS symbol,
                  COUNT(*)                                               AS so_lenh,
                  ROUND(100.0 * SUM(lab_result_realpnl > 0) / COUNT(*), 1) AS winrate,
                  ROUND(SUM(lab_result_realpnl), 2)                      AS pnl,
                  ROUND(AVG(CASE WHEN lab_result_realpnl > 0 THEN lab_result_realpnl END), 2) AS lai_tb,
                  ROUND(AVG(CASE WHEN lab_result_realpnl < 0 THEN lab_result_realpnl END), 2) AS lo_tb,
                  ROUND(AVG(lab_result_interval) / 3600000, 1)           AS gio_giu_tb
           FROM lab_results WHERE lab_result_account = %s
           GROUP BY lab_result_symbol ORDER BY pnl DESC LIMIT %s""",
        (run_id, limit),
    )


def timeline(run_id: int):
    """Tầng 5 — diễn biến theo tháng."""
    return fetch_all(
        """SELECT DATE_FORMAT(FROM_UNIXTIME(lab_result_chart / 1000), '%%Y-%%m') AS thang,
                  COUNT(*)                                               AS so_lenh,
                  ROUND(100.0 * SUM(lab_result_realpnl > 0) / COUNT(*), 1) AS winrate,
                  ROUND(SUM(lab_result_realpnl), 2)                      AS pnl
           FROM lab_results
           WHERE lab_result_account = %s AND lab_result_chart > 0
           GROUP BY thang ORDER BY thang""",
        (run_id,),
    )


def equity(run_id: int, points: int = 2000):
    """Đường vốn, lấy mẫu thưa. Bảng có 854.585 điểm nên phải giảm mẫu."""
    total = fetch_one(
        "SELECT COUNT(*) AS n FROM lab_track_balance WHERE lab_track_bl_account = %s", (run_id,)
    )["n"]
    if not total:
        return {"total": 0, "points": []}
    step = max(1, total // max(points, 1))
    rows = fetch_all(
        """SELECT lab_track_bl_time AS t,
                  ROUND(lab_track_bl_balance, 2)      AS balance,
                  ROUND(lab_track_bl_margin_bl, 2)    AS margin_balance,
                  ROUND(lab_track_bl_unrealize, 2)    AS unrealize,
                  ROUND(lab_track_bl_invest, 2)       AS invest
           FROM (SELECT *, (@r := @r + 1) AS rn
                 FROM lab_track_balance, (SELECT @r := 0) x
                 WHERE lab_track_bl_account = %s
                 ORDER BY lab_track_bl_time) t
           WHERE rn %% %s = 0""",
        (run_id, step),
    )
    return {"total": total, "step": step, "points": rows}


def trades(run_id: int, page: int = 1, size: int = 50, symbol=None, flow=None, only=None):
    """Danh sách lệnh có phân trang — không bao giờ trả cả 9.601 bản ghi."""
    where = ["lab_result_account = %s"]
    params = [run_id]
    if symbol:
        where.append("lab_result_symbol = %s")
        params.append(symbol)
    if flow:
        where.append("lab_result_flow = %s")
        params.append(flow)
    if only == "win":
        where.append("lab_result_realpnl > 0")
    elif only == "loss":
        where.append("lab_result_realpnl < 0")
    cond = " AND ".join(where)

    total = fetch_one(f"SELECT COUNT(*) AS n FROM lab_results WHERE {cond}", params)["n"]
    offset = max(0, (page - 1) * size)
    rows = fetch_all(
        f"""SELECT lab_result_id AS id, lab_result_symbol AS symbol, lab_result_flow AS flow,
                   CASE lab_result_type WHEN 1 THEN 'LONG' WHEN 2 THEN 'SHORT' ELSE '?' END AS side,
                   lab_result_phase AS phase, lab_result_status AS status,
                   lab_result_chart AS enter_time, lab_result_matched_price AS matched_price,
                   lab_result_matched_qty AS qty, lab_result_sell_price AS exit_price,
                   lab_result_sell_time AS exit_time,
                   ROUND(lab_result_realpnl, 3) AS pnl,
                   ROUND(lab_result_realprofit, 3) AS profit_pct,
                   ROUND(lab_result_interval / 3600000, 2) AS gio_giu
            FROM lab_results WHERE {cond}
            ORDER BY lab_result_chart DESC LIMIT %s OFFSET %s""",
        params + [size, offset],
    )
    for r in rows:
        r["status_ten"] = STATUS_LABEL.get(r["status"], f"Mã {r['status']}")
    return {"total": total, "page": page, "size": size, "rows": rows}


def insights(run_id: int):
    """Tầng 6 — nhận xét tự động rút ra từ các tầng trên."""
    out = []
    ov = overview(run_id)
    if not ov:
        return out

    # 1. Nhánh nào đang đốt tiền
    flows = by_flow(run_id)
    lo = [f for f in flows if (f["pnl"] or 0) < 0]
    lai = [f for f in flows if (f["pnl"] or 0) > 0]
    if lo and lai:
        f = lo[0]
        tong_lai = sum(float(x["pnl"]) for x in lai)
        out.append({
            "muc": "canh_bao",
            "tieu_de": f"Nhánh {f['flow']} đang lỗ {abs(float(f['pnl'])):,.0f} USDT",
            "chi_tiet": (f"Trên {f['so_lenh']:,} lệnh với winrate {f['winrate']}%. "
                         f"Nếu tắt nhánh này, kết quả từ {float(ov['pnl']):,.0f} thành "
                         f"{tong_lai:,.0f} USDT."),
        })

    # 2. Khai báo DCA nhưng không nhồi bậc nào
    if ov.get("phase_max") == 0:
        out.append({
            "muc": "canh_bao",
            "tieu_de": "Không có lệnh nào nhồi thêm bậc (phase sâu nhất = 0)",
            "chi_tiet": "Nếu đây là chiến lược DCA thì điều kiện nhồi lệnh chưa từng chạm — "
                        "cần xem lại ngưỡng lỗ kích hoạt bậc tiếp theo.",
        })

    # 3. Cắt lỗ chiếm đa số
    st = behavior(run_id)["status"]
    tong = sum(s["so_lenh"] for s in st) or 1
    cat_lo = next((s for s in st if s["ma"] == 3), None)
    if cat_lo and cat_lo["so_lenh"] / tong > 0.6:
        pct = round(100 * cat_lo["so_lenh"] / tong, 1)
        out.append({
            "muc": "luu_y",
            "tieu_de": f"{pct}% lệnh đóng ở trạng thái cắt lỗ",
            "chi_tiet": "Engine xếp lệnh vào nhóm cắt lỗ khi lãi không đủ bù phí — "
                        "không nhất thiết là chạm ngưỡng dừng lỗ.",
        })

    # 4. Tỷ lệ lãi/lỗ
    tl = ov.get("ty_le_lai_lo")
    if tl:
        if tl >= 2:
            out.append({
                "muc": "tot",
                "tieu_de": f"Ăn lớn thua nhỏ — tỷ lệ lãi/lỗ {tl}:1",
                "chi_tiet": f"Lãi trung bình {ov['lai_tb']} so với lỗ trung bình {ov['lo_tb']} mỗi lệnh.",
            })
        elif tl < 0.5:
            out.append({
                "muc": "canh_bao",
                "tieu_de": f"Thắng nhỏ thua lớn — tỷ lệ lãi/lỗ chỉ {tl}:1",
                "chi_tiet": f"Cần thắng {round(1/tl)} lệnh mới bù được 1 lệnh thua.",
            })

    # 5. Dùng đòn bẩy quá mức
    inv = ov.get("invest_cao_nhat")
    bal = ov.get("von_cao_nhat")
    if inv and bal and float(inv) > float(bal) * 3:
        out.append({
            "muc": "canh_bao",
            "tieu_de": "Vốn đầu tư có lúc vượt xa số dư",
            "chi_tiet": f"Cao nhất {float(inv):,.0f} USDT trong khi số dư đỉnh {float(bal):,.0f} — "
                        f"tương đương đòn bẩy khoảng {float(inv)/float(bal):.1f} lần.",
        })

    # 6. Coin kéo lỗ nặng
    syms = by_symbol(run_id, limit=200)
    xau = [s for s in syms if (s["pnl"] or 0) < 0]
    if xau and len(syms) > 3:
        w = xau[-1]
        out.append({
            "muc": "luu_y",
            "tieu_de": f"{len(xau)}/{len(syms)} coin đang lỗ, nặng nhất là {w['symbol']}",
            "chi_tiet": f"{w['symbol']} lỗ {abs(float(w['pnl'])):,.0f} USDT trên {w['so_lenh']} lệnh.",
        })
    return out
