"""Phân hệ Routes tinh gọn (backend/routes):

Chỉ còn 4 nhóm router chính:
- studio: Phục vụ Studio (Process, Book backtest/wfa/mc, Alphas, Research, Scan)
- live:   Quản lý Bot giao dịch trực tiếp (Live, Testnet, Paper)
- data:   Quản lý dữ liệu thị trường (Crawl, Promote, Ticks)
- system: Quản lý hệ thống, người dùng, tổng quan, giáo dục (Health, Users, Overview, Edu)
"""
from backend.routes import data, live, studio, system

ROUTERS = studio.ROUTERS + live.ROUTERS + data.ROUTERS + system.ROUTERS

# Shims cho mã cũ hoặc test import trực tiếp
process = studio
book = studio
alpha = studio
research = studio
scan = studio
home = system
engine = system
overview = system
users = system
edu = system

__all__ = [
    "studio",
    "live",
    "data",
    "system",
    "ROUTERS",
    "process",
    "book",
    "alpha",
    "research",
    "scan",
    "home",
    "engine",
    "overview",
    "users",
    "edu",
]
