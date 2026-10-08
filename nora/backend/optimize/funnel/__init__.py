"""Phễu kiểm duyệt alpha (S0 → FINAL). Hợp đồng: nora/docs/funnel_contract.md.

Gói này CHỈ import và dùng lại: backend.core.backtest (PortfolioEngine, shared_data), backend.carlo.carlo (Monte Carlo 10.000 + kịch bản cực xấu),
backend.optimize.process.process (tiến độ/ETA/SIGTERM), backend.optimize.process.workers (pool_imap_bounded). Không sửa các module đó.
"""
