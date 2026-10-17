"""Phân hệ Phân tích, Tính toán & Kết quả (backend/analys).

Gồm các thành phần theo chuẩn kiến trúc:
- param/: Quản lý và validate tham số chiến lược (StrategyParams).
- position/: Chính sách vị thế, định cỡ khối lượng (position sizing), quản trị rủi ro.
- signal/: Tính toán tín hiệu, chỉ báo kỹ thuật, ma trận tín hiệu và provider.
- alpha/: Chiến lược định lượng (DSL, compiler, registry, templates).
- metrics/: Đánh giá hiệu năng (PnL, Sharpe, Drawdown, Regime, Trade stats, Charts).
- validation/: Kiểm định độ bền (chứa 2 folder: carlo/ và wfa/).
- result/: Chuyển đổi và format kết quả sau backtest / live sang hợp đồng dữ liệu UI.
"""
