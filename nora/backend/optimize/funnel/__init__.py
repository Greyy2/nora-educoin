"""Phễu kiểm duyệt alpha (S0 → FINAL). Hợp đồng: nora/docs/funnel_contract.md.

Gói này CHỈ import và dùng lại: backend.core.backtest (PortfolioEngine, shared_data), backend.carlo.monte_carlo (Monte Carlo 10.000 + kịch bản cực xấu),
backend.optimize.progress (tiến độ/ETA/SIGTERM), backend.utils.parallel (pool_imap_bounded). Không sửa các module đó.
"""
