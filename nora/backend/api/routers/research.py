"""Research Platform API Router
Endpoints for DEX Market Research Desk:
- Market scan & leaderboard (GET /api/research/markets/scan)
- Detailed single asset analysis (GET /api/research/markets/{symbol}/analysis)
- On-demand single asset refresh (POST /api/research/markets/{symbol}/analyze)
- Why-Not-Trade diagnostics (GET /api/research/markets/why-not-trade)
- Research universe registry (GET /api/research/universe)
- Backward-compatible legacy endpoints (/scan/latest, /scan/run, /assets/overview, /analysis/{symbol})
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query

try:
    from backend.core.research.market_analyzer import (
        analyze_market,
        scan_all_markets,
        get_why_not_trade_summary,
        list_known_symbols,
    )
    from backend.core.research.event_behavior import fetch_recent_pool_trades
    from backend.core.research.discovery_engine import (
        compute_discoveries,
        get_discovery_by_id,
        get_dataset_summary,
        compute_method_comparison,
    )
except ImportError:
    from nora.backend.core.research.market_analyzer import (
        analyze_market,
        scan_all_markets,
        get_why_not_trade_summary,
        list_known_symbols,
    )
    from nora.backend.core.research.event_behavior import fetch_recent_pool_trades
    from nora.backend.core.research.discovery_engine import (
        compute_discoveries,
        get_discovery_by_id,
        get_dataset_summary,
        compute_method_comparison,
    )


router = APIRouter(prefix="/api/research", tags=["research"])


# ==========================================
# NEW QUANTITATIVE RESEARCH DESK ENDPOINTS
# ==========================================

@router.get("/markets/scan")
def get_markets_scan(
    symbols: Optional[str] = Query(None, description="Comma-separated list of symbols e.g. SOL,ETH,FONE"),
    timeframe: str = Query("1h", description="Khung thời gian phân tích"),
    force_refresh: bool = Query(False, description="Bắt buộc quét mới không dùng cache"),
):
    """
    Quét và xếp hạng toàn diện tất cả các thị trường DEX theo độ sạch dữ liệu,
    cấu trúc sóng Directional Change, trạng thái Regime và Playbook đề xuất.
    """
    try:
        sym_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
        res = scan_all_markets(symbols=sym_list, timeframe=timeframe, force_refresh=force_refresh)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi thực hiện Market Research Scan: {str(e)}")


@router.get("/markets/{symbol}/analysis")
def get_single_market_analysis(
    symbol: str,
    timeframe: str = Query("1h", description="Khung thời gian phân tích"),
    force_refresh: bool = Query(False, description="Chạy phân tích mới không dùng cache"),
):
    """
    Báo cáo phân tích chuyên sâu cho một cặp tài sản DEX:
    - Data Quality Gate report
    - Directional Change Multi-Theta Sweep & Best θ*
    - Empirical Scaling Law regression fit
    - Market Health Score & Tradeability Score
    - Intrinsic Regime Classification & drivers
    - Strategy Playbook recommendation
    - Narrative Report (WHAT / WHY / SO-WHAT)
    """
    clean_sym = symbol.strip().upper()
    try:
        res = analyze_market(clean_sym, timeframe=timeframe, force_refresh=force_refresh)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi phân tích chuyên sâu tài sản {clean_sym}: {str(e)}")


@router.post("/markets/{symbol}/analyze")
def trigger_single_market_analysis(
    symbol: str,
    timeframe: str = Query("1h", description="Khung thời gian phân tích"),
):
    """Kích hoạt tính toán lại toàn bộ pipeline cho một tài sản."""
    clean_sym = symbol.strip().upper()
    try:
        res = analyze_market(clean_sym, timeframe=timeframe, force_refresh=True)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi chạy mới phân tích cho {clean_sym}: {str(e)}")


@router.get("/markets/{symbol}/trades")
def get_recent_market_trades(
    symbol: str,
    limit: int = Query(40, ge=1, le=100, description="Số trade gần nhất cần lấy từ DEX pool"),
):
    """Recent on-chain pool trades from GeckoTerminal, cached briefly per asset."""
    clean_sym = symbol.strip().upper()
    try:
        return fetch_recent_pool_trades(clean_sym, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi kéo recent trades cho {clean_sym}: {str(e)}")


@router.get("/markets/why-not-trade")
def get_why_not_trade_endpoint():
    """Báo cáo bóc tách danh mục các thị trường bị loại bỏ hoặc hạn chế giao dịch (Why-Not-Trade)."""
    try:
        return get_why_not_trade_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi lấy danh sách Why-Not-Trade: {str(e)}")


@router.get("/universe")
def get_research_universe():
    """Danh sách các tài sản DEX hiện có trong research universe."""
    try:
        symbols = list_known_symbols()
        return {
            "total_symbols": len(symbols),
            "symbols": symbols,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi lấy danh mục universe: {str(e)}")


# ==========================================
# DISCOVERIES (cross-asset statistical findings)
# ==========================================

@router.get("/discoveries")
def get_discoveries(
    timeframe: str = Query("1h", description="Khung thời gian phân tích"),
    force_refresh: bool = Query(False, description="Bắt buộc tính lại không dùng cache"),
):
    """Danh sách các phát hiện thống kê cross-asset (Discoveries), sắp xếp theo mức độ mạnh."""
    try:
        summary = get_dataset_summary(timeframe=timeframe, force_refresh=force_refresh)
        discoveries = compute_discoveries(timeframe=timeframe, force_refresh=force_refresh)
        return {
            "generated_at": summary.get("n_assets") is not None and __import__("time").time() or None,
            "timeframe": timeframe,
            "dataset_summary": summary,
            "discoveries": discoveries,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi tính toán Discoveries: {str(e)}")


@router.get("/discoveries/{discovery_id}")
def get_discovery_detail(
    discovery_id: str,
    timeframe: str = Query("1h", description="Khung thời gian phân tích"),
    force_refresh: bool = Query(False, description="Bắt buộc tính lại không dùng cache"),
):
    """Chi tiết một Discovery: hypothesis, global stats, distribution, cross-asset, cross-dex, robustness."""
    try:
        discovery = get_discovery_by_id(discovery_id, timeframe=timeframe, force_refresh=force_refresh)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi tính toán Discovery {discovery_id}: {str(e)}")
    if discovery is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy Discovery: {discovery_id}")
    return discovery


@router.get("/methods/compare")
def get_methods_compare(
    timeframe: str = Query("1h", description="Khung thời gian phân tích"),
    force_refresh: bool = Query(False, description="Bắt buộc tính lại không dùng cache"),
):
    """So sánh các phương pháp lấy mẫu phân tích: Time / Volume / Directional Change / DC+OS."""
    try:
        return compute_method_comparison(timeframe=timeframe, force_refresh=force_refresh)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi so sánh phương pháp: {str(e)}")


# ==========================================
# BACKWARD COMPATIBILITY ENDPOINTS
# ==========================================

@router.get("/scan/latest")
def get_latest_scan(timeframe: str = Query("1h")):
    """Legacy endpoint for batch scan results."""
    try:
        # Route to new scan format
        scan = scan_all_markets(timeframe=timeframe, force_refresh=False)
        return scan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi đọc kết quả scan: {str(e)}")


@router.post("/scan/run")
def trigger_batch_scan(timeframe: str = Query("1h")):
    """Legacy endpoint to trigger batch scan."""
    try:
        scan = scan_all_markets(timeframe=timeframe, force_refresh=True)
        return scan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi thực thi batch scan: {str(e)}")


@router.get("/assets/overview")
def get_assets_overview(timeframe: str = Query("1h")):
    """Legacy endpoint for assets overview."""
    try:
        scan = scan_all_markets(timeframe=timeframe, force_refresh=False)
        return {
            "summary": scan.get("summary", {}),
            "assets": scan.get("rows", []),
            "strategy_leaderboard": [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi lấy danh sách tổng quan: {str(e)}")


@router.get("/analysis/{symbol}")
def get_asset_analysis_legacy(
    symbol: str,
    timeframe: str = Query("1h"),
):
    """Legacy endpoint for single asset analysis."""
    clean_sym = symbol.strip().upper()
    try:
        res = analyze_market(clean_sym, timeframe=timeframe, force_refresh=False)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi phân tích chuyên sâu tài sản {clean_sym}: {str(e)}")
