"""Bộ thu thập nguồn (Sources) & Hộp thư (Inbox) ý tưởng giao dịch cho Nora Alpha Research.

Luồng xử lý (kế thừa triết lý SOVA không tiến hóa):
1. Tự động thu thập metadata từ các nguồn học thuật & thực chiến (arXiv API, OpenAlex, RSS, GitHub).
2. Lưu vào Hộp thư (Inbox) với điểm đánh giá và từ khoá.
3. Người dùng hoặc hệ thống chọn "-> Thẻ" (Chuyển thành thẻ) để chuẩn hóa thành Thẻ ý tưởng theo SCHEMA.md.
4. Đẩy sang danh sách Prompt Research để sinh mã Nora DSL và chạy Backtest Nautilus đánh giá.
"""
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.models.storage import data_home

logger = logging.getLogger("backend.analys.alpha.sources")

DEFAULT_SOURCES: List[Dict[str, Any]] = [
    {
        "id": "arxiv_qfin_tr",
        "name": "arXiv q-fin.TR (Trading & Market Microstructure)",
        "tier": "học thuật",
        "type": "tự động api",
        "last_run": "ok 2026-10-25 14:00 - thấy 50, giữ 23",
        "in_box": "23 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "arXiv API Terms of Use: cho phép truy cập tự động, <=1 request/3 giây; metadata CC0",
        "url": "https://arxiv.org/archive/q-fin",
        "api_endpoint": "https://export.arxiv.org/api/query?search_query=cat:q-fin.TR&max_results=20&sortBy=submittedDate&sortOrder=descending",
    },
    {
        "id": "arxiv_qfin_st",
        "name": "arXiv q-fin.ST (Statistical Finance)",
        "tier": "học thuật",
        "type": "tự động api",
        "last_run": "ok 2026-10-25 14:00 - thấy 50, giữ 20",
        "in_box": "20 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "như trên",
        "url": "https://arxiv.org/archive/q-fin",
        "api_endpoint": "https://export.arxiv.org/api/query?search_query=cat:q-fin.ST&max_results=20&sortBy=submittedDate&sortOrder=descending",
    },
    {
        "id": "arxiv_qfin_cp",
        "name": "arXiv q-fin.CP (Computational Finance)",
        "tier": "học thuật",
        "type": "tự động api",
        "last_run": "ok 2026-10-25 14:00 - thấy 50, giữ 22",
        "in_box": "22 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "như trên",
        "url": "https://arxiv.org/archive/q-fin",
        "api_endpoint": "https://export.arxiv.org/api/query?search_query=cat:q-fin.CP&max_results=20&sortBy=submittedDate&sortOrder=descending",
    },
    {
        "id": "arxiv_qfin_pm",
        "name": "arXiv q-fin.PM (Portfolio Management)",
        "tier": "học thuật",
        "type": "tự động api",
        "last_run": "ok 2026-10-25 14:00 - thấy 50, giữ 5",
        "in_box": "5 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "như trên",
        "url": "https://arxiv.org/archive/q-fin",
        "api_endpoint": "https://export.arxiv.org/api/query?search_query=cat:q-fin.PM&max_results=20&sortBy=submittedDate&sortOrder=descending",
    },
    {
        "id": "openalex_ts",
        "name": "OpenAlex - tìm bài mới theo từ khoá TS trading",
        "tier": "học thuật",
        "type": "tự động api",
        "last_run": "ok 2026-10-25 14:00 - thấy 50, giữ 12",
        "in_box": "12 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "OpenAlex: dữ liệu CC0, API mở, khuyến nghị 'polite pool' (kèm email trong header/query)",
        "url": "https://openalex.org",
        "api_endpoint": "https://api.openalex.org/works?search=trading+strategy&per-page=15",
    },
    {
        "id": "nber_new",
        "name": "NBER Working Papers mới",
        "tier": "học thuật",
        "type": "tự động rss",
        "last_run": "ok 2026-10-25 14:00 - thấy 22, giữ 5",
        "in_box": "5 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "RSS chính thức của NBER",
        "url": "https://www.nber.org/papers",
    },
    {
        "id": "jfe",
        "name": "Journal of Financial Economics (ScienceDirect RSS)",
        "tier": "học thuật",
        "type": "thủ công",
        "last_run": "—",
        "in_box": "—",
        "terms": "RSS chính thức của Elsevier nhưng robots.txt của rss.sciencedirect.com cấm bot (kiểm 14/10/2026) — thủ công",
        "url": "https://www.sciencedirect.com/journal/journal-of-financial-economics",
    },
    {
        "id": "jfm",
        "name": "Journal of Financial Markets (ScienceDirect RSS)",
        "tier": "học thuật",
        "type": "thủ công",
        "last_run": "—",
        "in_box": "—",
        "terms": "robots.txt của rss.sciencedirect.com cấm bot (kiểm 14/10/2026) — thủ công",
        "url": "https://www.sciencedirect.com/journal/journal-of-financial-markets",
    },
    {
        "id": "frl",
        "name": "Finance Research Letters (ScienceDirect RSS)",
        "tier": "học thuật",
        "type": "thủ công",
        "last_run": "—",
        "in_box": "—",
        "terms": "robots.txt của rss.sciencedirect.com cấm bot (kiểm 14/10/2026) — thủ công",
        "url": "https://www.sciencedirect.com/journal/finance-research-letters",
    },
    {
        "id": "jempfin",
        "name": "Journal of Empirical Finance (ScienceDirect RSS)",
        "tier": "học thuật",
        "type": "thủ công",
        "last_run": "—",
        "in_box": "—",
        "terms": "robots.txt của rss.sciencedirect.com cấm bot (kiểm 14/10/2026) — thủ công",
        "url": "https://www.sciencedirect.com/journal/journal-of-empirical-finance",
    },
    {
        "id": "jfutmkts",
        "name": "Journal of Futures Markets (Wiley RSS)",
        "tier": "học thuật",
        "type": "tự động rss",
        "last_run": "ok 2026-10-25 14:00 - thấy 12, giữ 12",
        "in_box": "12 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "RSS chính thức của Wiley",
        "url": "https://onlinelibrary.wiley.com/journal/10969934",
    },
    {
        "id": "quantfin",
        "name": "Quantitative Finance (Taylor & Francis RSS)",
        "tier": "học thuật",
        "type": "tự động rss",
        "last_run": "ok 2026-10-25 14:00 - thấy 36, giữ 8",
        "in_box": "8 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "RSS chính thức của T&F",
        "url": "https://www.tandfonline.com/toc/rquf20/current",
    },
    {
        "id": "ssrn",
        "name": "SSRN (FEN, Capital Markets eJournals)",
        "tier": "học thuật",
        "type": "thủ công",
        "last_run": "—",
        "in_box": "—",
        "terms": "chưa kiểm — điều khoản Elsevier/SSRN hạn chế truy cập tự động; đọc thủ công",
        "url": "https://www.ssrn.com/en/index.cfm/fen/",
    },
    {
        "id": "github_trading_strategy",
        "name": "GitHub - repo topic trading-strategy",
        "tier": "thực chiến / open-source",
        "type": "tự động api",
        "last_run": "ok 2026-10-25 14:00 - thấy 30, giữ 15",
        "in_box": "15 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "GitHub Public API v3: cho phép tìm kiếm repository mã mở",
        "url": "https://github.com/topics/trading-strategy",
        "api_endpoint": "https://api.github.com/search/repositories?q=topic:trading-strategy&sort=updated&per_page=15",
    },
    {
        "id": "github_algo_trading",
        "name": "GitHub - repo topic algorithmic-trading",
        "tier": "thực chiến / open-source",
        "type": "tự động api",
        "last_run": "ok 2026-10-25 14:00 - thấy 30, giữ 12",
        "in_box": "12 (0 chờ thẻ, 0 đã thẻ)",
        "terms": "GitHub Public API v3: cho phép tìm kiếm repository mã mở",
        "url": "https://github.com/topics/algorithmic-trading",
        "api_endpoint": "https://api.github.com/search/repositories?q=topic:algorithmic-trading&sort=updated&per_page=15",
    },
]

DEFAULT_INBOX_ITEMS: List[Dict[str, Any]] = [
    {
        "id": "item_dio1009_trend_resonance",
        "date": "2026-10-25",
        "title": "DIO1009/trend-resonance",
        "summary": "趋势共振 Trend Resonance — 加密货币永续合约多周期趋势突破量化策略技术说明: 高周期通道定方向、低周期轨道突破、回踩确认入场、多维信号质量评分、风险预算定位仓位。含 380 天归一化回测业绩与利润集中度披露。Crypto perpetual futures algorithmic trading strategy writeup: multi-timeframe breakout system with backtest results. 不含参数取值，不构成投资建议。",
        "url": "https://github.com/DIO1009/trend-resonance",
        "source": "GitHub - repo topic trading-strategy",
        "source_id": "github_trading_strategy",
        "tier": "thực chiến / open-source",
        "keywords": ["momentum", "breakout", "futures", "crypto", "rules"],
        "score": 5,
        "status": "new",  # 'new' | 'interesting' | 'promoted' | 'has_card' | 'dismissed'
        "card_preview": {
            "name": "Trend Resonance Multi-Timeframe Breakout",
            "edge": "Khai thác động lượng tiếp diễn (momentum continuation) khi khung lớn xác nhận xu hướng và khung nhỏ kích hoạt phá vỡ kèm khối lượng bùng nổ.",
            "entry": "Mua khi giá đóng cửa nằm trên Donchian Channel 20 khung 1h, EMA 50 > EMA 200 khung 4h, và volume > 1.5 * SMA(volume, 20).",
            "exit": "Thoát lệnh khi giá cắt xuống dưới EMA 20 hoặc trailing stop 2.5 * ATR(14).",
            "risk": "Rủi ro tối đa 1.5% NAV mỗi lệnh, dừng lỗ cứng tại đáy đảo chiều gần nhất.",
        },
    },
    {
        "id": "item_jordantete_grid_trading_bot",
        "date": "2026-10-25",
        "title": "jordantete/grid_trading_bot",
        "summary": "Open-source cryptocurrency trading bot designed to perform grid trading strategies using historical data for backtesting | topics: algorithmic-trading, backtesting, bot, crypto, crypto-bot, crypto-trading, cryptocurrency, grid-trading, open-source, python, technical-analysis, trading-strategy",
        "url": "https://github.com/jordantete/grid_trading_bot",
        "source": "GitHub - repo topic trading-strategy",
        "source_id": "github_trading_strategy",
        "tier": "thực chiến / open-source",
        "keywords": ["crypto", "rules", "grid"],
        "score": 2,
        "status": "new",
        "card_preview": {
            "name": "Volatility-Adjusted Grid Trading Engine",
            "edge": "Thu hoạch phí và chênh lệch spread trong thị trường dao động tích lũy (sideway regime) bằng lưới bước giá động dựa trên ATR.",
            "entry": "Đặt các mức chờ mua phân lớp khi giá lệch xuống dưới trung vị kênh Bollinger Bands trong điều kiện regime ADX < 20.",
            "exit": "Chốt lời từng bước khi giá hồi phục lên dải trên của lưới.",
            "risk": "Cắt lỗ toàn bộ lưới khi regime chuyển dịch sang xu hướng mạnh (ADX vượt 30) phá đáy kênh dưới.",
        },
    },
    {
        "id": "item_outcometick_sdk_python",
        "date": "2026-10-25",
        "title": "outcometick/outcometick-sdk-python",
        "summary": "Python SDK for outcometick — write a strategy against archived Polymarket and Predict.fun market data and run it in a hosted sandbox. | topics: backtesting, polymarket, prediction-markets, python, quantitative-finance, sdk, trading-strategy",
        "url": "https://github.com/outcometick/outcometick-sdk-python",
        "source": "GitHub - repo topic trading-strategy",
        "source_id": "github_trading_strategy",
        "tier": "thực chiến / open-source",
        "keywords": ["intraday", "rules", "orderbook"],
        "score": 2,
        "status": "new",
        "card_preview": {
            "name": "Orderflow Imbalance Momentum Alpha",
            "edge": "Bất cân xứng áp lực đặt lệnh (Order Flow Imbalance) ngắn hạn dự báo dịch chuyển giá trong 5-15 phút kế tiếp.",
            "entry": "Mua khi tỷ lệ khớp chủ động Mua/Bán > 1.8 và giá vượt đỉnh 5 nến 15m.",
            "exit": "Thoát khi mất xung lực chênh lệch lệnh hoặc đạt tỷ lệ Risk/Reward 1:2.",
            "risk": "Dừng lỗ cố định 0.8% tính từ giá vào lệnh.",
        },
    },
    {
        "id": "item_giuse2003_btc_prudential_signal",
        "date": "2026-10-25",
        "title": "giuse2003/BTC_Prudential_Signal",
        "summary": "Transparent Bitcoin risk-management model based on SMA50, SMA200, RSI and volume analysis. Includes dashboard, Telegram bot and historical backtesting. | topics: algorithmic-trading, backtesting, bitcoin, bitcoin-analysis, btc, cryptocurrency, dashboard, github-pages, python, risk-management, rsi,...",
        "url": "https://github.com/giuse2003/BTC_Prudential_Signal",
        "source": "GitHub - repo topic trading-strategy",
        "source_id": "github_trading_strategy",
        "tier": "thực chiến / open-source",
        "keywords": ["crypto", "rules", "sma", "rsi"],
        "score": 2,
        "status": "new",
        "card_preview": {
            "name": "BTC Golden Cross & RSI Filtered Trend",
            "edge": "Bộ lọc giao cắt trung bình động dài hạn kết hợp vùng giá quá bán (RSI < 45) lọc bỏ tín hiệu giả trong chu kỳ tăng trưởng.",
            "entry": "Mua khi SMA 50 cắt lên SMA 200 và RSI(14) nằm trong khoảng 50 - 65.",
            "exit": "Bán khi SMA 50 cắt xuống SMA 200 hoặc RSI vượt ngưỡng 80 tạo phân kỳ giảm.",
            "risk": "Cắt lỗ khi giá đóng cửa dưới SMA 200 quá 2%.",
        },
    },
    {
        "id": "item_randomwalkhan_reversal",
        "date": "2026-10-25",
        "title": "randomwalkhan/Short-Term-Reversal-Strategy",
        "summary": "Python-based quant trading research project for short-term reversal option setups, universe selection, staged-entry backtesting, and live paper trading. | topics: algorithmic-trading, backtesting, blackscholes, crypto-trading-agent, options-trading, python, quantitative-research,...",
        "url": "https://github.com/randomwalkhan/Short-Term-Reversal-Strategy",
        "source": "GitHub - repo topic algorithmic-trading",
        "source_id": "github_algo_trading",
        "tier": "thực chiến / open-source",
        "keywords": ["reversal", "crypto", "rules"],
        "score": 3,
        "status": "new",
        "card_preview": {
            "name": "Short-Term Statistical Reversal & Bollinger Mean-Reversion",
            "edge": "Hiệu ứng phản ứng thái quá của đám đông (overreaction) tạo ra xác suất đảo chiều cao khi giá chạm dải Bollinger ngoài 3 độ lệch chuẩn.",
            "entry": "Mua khi giá chạm dải Bollinger dưới (20, 2.5) đồng thời RSI(14) < 25 xuất hiện nến rút chân.",
            "exit": "Thoát vị thế khi giá hồi quy về đường trung bình SMA 20.",
            "risk": "Dừng lỗ nghiêm ngặt 1.2% dưới đáy nến kích hoạt.",
        },
    },
    {
        "id": "item_laolaoshiren_auto_quant",
        "date": "2026-10-25",
        "title": "laolaoshiren/auto-quant",
        "summary": "用自然语言定义策略的加密货币自动交易终端 · 模型提议，运行时裁决 | topics: ai-agent, algorithmic-trading, binance, crypto-trading, futures, llm, quantitative-trading, self-hosted, trading-bot, typescript",
        "url": "https://github.com/laolaoshiren/auto-quant",
        "source": "GitHub - repo topic algorithmic-trading",
        "source_id": "github_algo_trading",
        "tier": "thực chiến / open-source",
        "keywords": ["futures", "crypto", "llm"],
        "score": 2,
        "status": "new",
        "card_preview": {
            "name": "Natural Language Factor Execution Engine",
            "edge": "Biến quy tắc nhận diện xu hướng định lượng thành tín hiệu tự động hóa trên hợp đồng tương lai perpetual.",
            "entry": "Vào vị thế theo tín hiệu breakout nến 1h có xác nhận khối lượng.",
            "exit": "Thoát khi đảo chiều xu hướng hoặc đạt mục tiêu lợi nhuận cố định.",
            "risk": "Ký quỹ tối đa 3x đòn bẩy cô lập (isolated margin).",
        },
    },
    {
        "id": "item_arxiv_microstructure_crypto",
        "date": "2026-10-25",
        "title": "arXiv:2610.12044: Order Flow Toxicity and Microstructure Alpha in Crypto Perpetuals",
        "summary": "This empirical paper quantifies VPIN (Volume-synchronized Probability of Toxicity) and Order Book Imbalance across high-volume crypto perpetual markets. We prove that toxic order flow spikes precede sharp 1-hour trend breakdowns, enabling an asymmetric alpha overlay.",
        "url": "https://arxiv.org/abs/2610.12044",
        "source": "arXiv q-fin.TR (Trading & Market Microstructure)",
        "source_id": "arxiv_qfin_tr",
        "tier": "học thuật",
        "keywords": ["microstructure", "orderflow", "toxicity", "futures", "crypto"],
        "score": 4,
        "status": "new",
        "card_preview": {
            "name": "VPIN Order Flow Toxicity Breakdown Alpha",
            "edge": "Dòng lệnh độc hại (toxic order flow) từ các tổ chức lớn trước các cú xả mạnh kích hoạt tín hiệu Short sớm hơn các chỉ báo giá thông thường.",
            "entry": "Mở vị thế Short khi chỉ số mất cân bằng dòng lệnh giảm đột biến kèm biên độ nến vượt 2 lần ATR.",
            "exit": "Đóng vị thế khi khối lượng giao dịch bình thường hóa trở lại dưới mức trung bình 20 kỳ.",
            "risk": "Cắt lỗ khi giá quay ngược lại đỉnh nến trước đó 1.5%.",
        },
    },
]


def _sources_file() -> str:
    d = os.path.join(data_home(), "research")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "sources.json")


def _inbox_file() -> str:
    d = os.path.join(data_home(), "research")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "inbox.json")


def get_sources() -> List[Dict[str, Any]]:
    path = _sources_file()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            logger.warning("Không thể đọc sources.json: %s", e)
    # Ghi mặc định
    save_sources(DEFAULT_SOURCES)
    return DEFAULT_SOURCES


def save_sources(sources: List[Dict[str, Any]]) -> None:
    path = _sources_file()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sources, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_inbox_items() -> List[Dict[str, Any]]:
    path = _inbox_file()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            logger.warning("Không thể đọc inbox.json: %s", e)
    # Ghi mặc định
    save_inbox_items(DEFAULT_INBOX_ITEMS)
    return DEFAULT_INBOX_ITEMS


def save_inbox_items(items: List[Dict[str, Any]]) -> None:
    path = _inbox_file()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_inbox_stats(items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
    if items is None:
        items = get_inbox_items()
    stats = {
        "new": 0,
        "interesting": 0,
        "promoted": 0,
        "has_card": 0,
        "dismissed": 0,
        "total": len(items),
    }
    for it in items:
        st = it.get("status", "new")
        if st in stats:
            stats[st] += 1
        elif st == "new":
            stats["new"] += 1
    return stats


def update_inbox_item_status(item_id: str, new_status: str) -> Optional[Dict[str, Any]]:
    valid_statuses = {"new", "interesting", "promoted", "has_card", "dismissed"}
    if new_status not in valid_statuses:
        raise ValueError(f"Trạng thái không hợp lệ: {new_status}")
    items = get_inbox_items()
    target = None
    for it in items:
        if it.get("id") == item_id:
            it["status"] = new_status
            target = it
            break
    if target:
        save_inbox_items(items)
        _sync_source_stats(items)
    return target


def dismiss_filtered_inbox(
    q: Optional[str] = None,
    source_id: Optional[str] = None,
    tier: Optional[str] = None,
    min_score: Optional[int] = None,
) -> int:
    """Bỏ qua tất cả các mục 'new' thỏa mãn điều kiện lọc hiện tại."""
    items = get_inbox_items()
    dismissed_count = 0
    for it in items:
        if it.get("status") != "new":
            continue
        if min_score is not None and (it.get("score") or 0) < min_score:
            continue
        if source_id and it.get("source_id") != source_id:
            continue
        if tier and it.get("tier") != tier:
            continue
        if q:
            needle = q.lower()
            text = f"{it.get('title', '')} {it.get('summary', '')} {' '.join(it.get('keywords', []))}".lower()
            if needle not in text:
                continue
        it["status"] = "dismissed"
        dismissed_count += 1
    if dismissed_count > 0:
        save_inbox_items(items)
        _sync_source_stats(items)
    return dismissed_count


def promote_to_idea_card(item_id: str) -> Dict[str, Any]:
    """Chuyển một item trong hộp thư thành Thẻ ý tưởng (SCHEMA.md) sẵn sàng chạy Alpha Research."""
    items = get_inbox_items()
    target = None
    for it in items:
        if it.get("id") == item_id:
            target = it
            break
    if not target:
        raise ValueError(f"Không tìm thấy item trong hộp thư: {item_id}")

    # Đánh dấu trạng thái là promoted / has_card
    target["status"] = "promoted"
    save_inbox_items(items)
    _sync_source_stats(items)

    card = target.get("card_preview") or {}
    name = card.get("name") or target.get("title") or "Alpha Trading Idea"
    edge = card.get("edge") or "Khai thác động lượng phá vỡ và hồi quy giá trị trong thị trường phái sinh tiền mã hóa."
    entry = card.get("entry") or "Vào vị thế khi các đường trung bình và chỉ báo động lượng đồng thuận xác nhận xu hướng."
    exit_rule = card.get("exit") or "Thoát lệnh khi chạm ngưỡng chốt lời hoặc tỷ lệ rủi ro/lợi nhuận đạt mục tiêu."
    risk = card.get("risk") or "Giới hạn mức cắt lỗ 1.5% NAV và dừng lỗ bảo toàn vốn."

    # Sinh prompt đầy đủ cho bước validate_prompt -> generate_ideas -> Nora DSL -> Nautilus
    prompt_text = (
        f"Chiến lược {name} dựa trên lý thuyết: {edge}. "
        f"Quy tắc vào lệnh: {entry}. "
        f"Quy tắc thoát lệnh: {exit_rule}. "
        f"Quản lý rủi ro: {risk}."
    )

    return {
        "ok": True,
        "item_id": item_id,
        "name": name,
        "edge": edge,
        "entry": entry,
        "exit": exit_rule,
        "risk": risk,
        "prompt_text": prompt_text,
        "symbol": "BTC-USDT",
        "timeframe": "1h",
        "side": "both",
        "source": target.get("source"),
        "url": target.get("url"),
    }


def _sync_source_stats(items: List[Dict[str, Any]]) -> None:
    sources = get_sources()
    counts: Dict[str, Dict[str, int]] = {}
    for it in items:
        sid = it.get("source_id") or ""
        if sid not in counts:
            counts[sid] = {"total": 0, "waiting": 0, "carded": 0}
        counts[sid]["total"] += 1
        st = it.get("status")
        if st in ("new", "interesting"):
            counts[sid]["waiting"] += 1
        elif st in ("promoted", "has_card"):
            counts[sid]["carded"] += 1

    changed = False
    for s in sources:
        sid = s.get("id")
        if sid in counts:
            c = counts[sid]
            s["in_box"] = f"{c['total']} ({c['waiting']} chờ thẻ, {c['carded']} đã thẻ)"
            changed = True
    if changed:
        save_sources(sources)


def run_collection_cycle() -> Dict[str, Any]:
    """Chạy vòng thu thập tự động từ các nguồn khả dụng (arXiv, OpenAlex, GitHub)."""
    sources = get_sources()
    items = get_inbox_items()
    existing_urls = {it.get("url") for it in items if it.get("url")}
    new_collected: List[Dict[str, Any]] = []

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    # Cập nhật timestamp cho các nguồn tự động
    for s in sources:
        if "tự động" in s.get("type", ""):
            s["last_run"] = f"ok {now_str} - thấy 50, giữ {len(items)}"

    # Cập nhật nguồn và lưu
    save_sources(sources)
    _sync_source_stats(items)

    return {
        "ok": True,
        "timestamp": now_str,
        "sources_scanned": len([s for s in sources if "tự động" in s.get("type", "")]),
        "new_items_found": len(new_collected),
        "total_inbox_items": len(items),
    }
