"""Tỉ trọng vốn xnoquant cho rổ TOP10 Crypto Spot (đo 06/10/2026 từ thí nghiệm E1 "luôn long position=1", hồi quy vốn ngày trên giá Binance, R² = 1,0).

xnoquant chia vốn giữa các coin theo tỉ trọng vốn hoá CỐ ĐỊNH (khớp vốn hoá ~cuối 11/2025, sai số log <= 0,12), mua MỘT lần, không cân lại.
Tổng = 1,00001 (làm tròn 5 chữ số): profile xno chuẩn hoá lại về đúng 1. Fixture đối chiếu: test/fixtures/xno/top10_weights.json (chỉ dùng cho test).
"""
TOP10_WEIGHTS = {
    "BTC": 0.69160, "ETH": 0.14653, "XRP": 0.05158, "BNB": 0.04720, "SOL": 0.02932,
    "TRX": 0.01041, "DOGE": 0.00938, "ADA": 0.00561, "BCH": 0.00472, "LINK": 0.00366,
}
TOP10 = tuple(TOP10_WEIGHTS)
