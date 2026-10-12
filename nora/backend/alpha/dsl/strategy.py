"""Logic KHÔNG thuộc engine, tách nguyên văn từ test/backend-no/core/backtest.py (P15-A): tín hiệu trên nến đã đóng (evaluate_signals, signal_snapshot,
check_signals), dựng kế hoạch (build_plan, Plan), RiskConfig, hằng số/tiện ích dùng chung, Order/Venue (định nghĩa dữ liệu).
KHÔNG có mô phỏng khớp lệnh: engine = backend/nautilus/. SignalEngine / SignalPortfolio = đúng các phương thức nạp dữ liệu + dựng ma trận cột của
BacktestEngine / PortfolioEngine cũ (không có run/kernel/sổ vốn mô phỏng)."""

import itertools
import os
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any, Callable, Deque, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple, Set, Union

import numpy as np
import pandas as pd

from backend.models.models import CapitalLedger, Fill, OrderRejected, PositionType
from backend.models.models import DataSource, data_source
from backend.alpha.dsl.signal import lag_key, VectorEvaluator, Program
from backend.alpha.dsl.signal import CODE as REGIME_CODE, LABEL_VI as REGIME_LABEL_VI, NAMES as REGIME_NAMES, REFS as REGIME_REFS
from backend.alpha.dsl.signal import classify, masks_for, profile_cfg, raw_states
from backend.alpha.dsl.signal import (DEFAULT_LOOKBACK_MIN, HORIZONS_MIN, MINUTE, _explain, _forward_bps, _num, _since, _stats, _thin,
                                 _verdict)
from backend.models.position_size import SlotSpec
from backend.models.params import BASE_POSITION, config_from_dict, DATA_COLUMNS, DEFAULT_CAPITAL, DAY_MS as DAY, FRAME_MS, FRAME_ORDER, FRAMES, NORA_DEFAULTS, RISK, RUN_FRAME, StrategyParams, resolve_position_auto
from backend.alpha.dsl import indicator as kernels


KEY = "__bar_open_time"  # cột khoá nội bộ (tránh trùng với cột "open_time" mà AST có thể dùng)


def collect_field_refs(tree) -> Set[Tuple[str, str, int]]:
    """Mọi (frame, column, lag) mà một cây điều kiện tham chiếu."""
    refs: Set[Tuple[str, str, int]] = set()

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "frame" in node and "column" in node:
                refs.add((str(node["frame"]), str(node["column"]), int(node.get("index", 0) or 0)))
            for key in ("number_1", "number_2", "add", "subtract", "divide"):
                if key in node:
                    walk(node[key])
            for item in node.get("numbers", []) if isinstance(node.get("numbers"), list) else []:
                walk(item)

    walk(tree)
    return refs


SIGNAL_MODES = ("event", "level")      # "event" (mặc định) | "level" (hành vi cũ — tái tạo kết quả lịch sử)
SIGNAL_MODE_DEFAULT = "event"
FRESH = "__fresh"                      # cột tổng hợp "khung|__fresh": nến khung vừa ĐÓNG ở nến chạy này (xem frame_fresh)


def slot_signal_mode(slot: Any) -> str:
    """signal_mode của một slot (SlotSpec / tracker tham chiếu): thuộc tính riêng, hoặc StrategyParams.signal_mode, mặc định "event"."""
    mode = getattr(slot, "signal_mode", None) or getattr(getattr(slot, "params", None), "signal_mode", None) or SIGNAL_MODE_DEFAULT
    mode = str(mode).lower()
    if mode not in SIGNAL_MODES:
        raise ValueError(f"signal_mode phải là một trong {SIGNAL_MODES}, nhận '{mode}'")
    return mode


def entry_signal_frame(tree: Any, base: str) -> Optional[str]:
    """Khung tín hiệu của một cây điều kiện VÀO = khung LỚN NHẤT trong các lá của cây; None nếu <= khung chạy (không đổi gì)."""
    frames = [fr for fr, _, _ in collect_field_refs(tree) if fr in FRAME_MS]
    top = max(frames, key=FRAME_MS.__getitem__, default=None)
    return top if top is not None and FRAME_MS[top] > FRAME_MS[base] else None


def slot_fresh_frames(slots: Iterable[Any], base: str) -> Set[str]:
    """Các khung cần cột "khung|__fresh" để dựng mặt nạ vào theo sự kiện (slot signal_mode="event" có cây vào khung > khung chạy)."""
    return {fr for tr in slots if slot_signal_mode(tr) == "event" for fr in [entry_signal_frame(tr.match_tree, base)] if fr}


def frame_fresh(idx: np.ndarray, real: Optional[np.ndarray] = None) -> np.ndarray:
    """Cột sự kiện của một khung lớn: True ở nến chạy THỰC đầu tiên mà nến khung (chỉ số `idx`, từ align_index) khác nến khung của nến thực liền trước
    (= nến khung vừa đóng; nến điền is_filled bỏ qua nên sự kiện rơi vào phút điền được chuyển sang nến thực kế tiếp). Nến đầu chuỗi: False
    (vùng khởi động). `real`: mặt nạ nến thực trên chuỗi idx (None = mọi nến đều thực). Điểm duy nhất định nghĩa "sự kiện" — mọi đường dùng chung."""
    idx = np.asarray(idx)
    r = np.arange(len(idx)) if real is None else np.flatnonzero(real)
    out = np.zeros(len(idx), dtype=bool)
    if len(r) > 1:
        out[r[1:]] = idx[r[1:]] != idx[r[:-1]]
    return out


def entry_event_mask(vec: VectorEvaluator, cols: Mapping[str, np.ndarray], slot: Any, base: str) -> np.ndarray:
    """Mặt nạ tín hiệu VÀO của một slot — MỘT định nghĩa cho batch (load_data / run_backtest), NoraSlotStrategy (nautilus/engine.py; qua evaluate_signals),
    signal_snapshot.

    signal_mode="level" (hoặc khung tín hiệu == khung chạy): mặt nạ trạng thái như cũ, `vec.tree(match_tree)` nguyên vẹn (bit-identical).
    signal_mode="event" (mặc định) và khung tín hiệu F > khung chạy (F = khung lớn nhất trong lá của cây): tín hiệu chỉ kích ở nến chạy ĐẦU TIÊN
    sau khi nến F đóng (cột `F|__fresh`), như NautilusTrader on_bar / Sova — không phải trạng thái lặp lại ở mọi nến chạy trong suốt nến F.
    Hệ quả (chủ ý): lệnh vào bị chặn đúng phút đó (cooldown / đủ vị thế / rủi ro / đang giữ vị thế / vừa đóng vị thế trong nến) thì MẤT, không
    thử lại ở các nến chạy sau cho tới khi nến F kế tiếp đóng. Cây THOÁT / STOP / DCA là trạng thái, không qua hàm này."""
    mask = vec.tree(slot.match_tree)
    if slot_signal_mode(slot) != "event":
        return mask
    frame = entry_signal_frame(slot.match_tree, base)
    if frame is None:
        return mask
    fresh = cols.get(f"{frame}|{FRESH}")
    if fresh is None:
        raise ValueError(f"thiếu cột {frame}|{FRESH} (sự kiện nến khung) cho tín hiệu vào khung {frame} > {base}")
    return mask & fresh


def frame_features(df: pd.DataFrame, refs: Set[Tuple[str, int]]) -> pd.DataFrame:
    """Tính các cột (kernel/base/legacy) + cột trễ cho một khung. df đã sắp theo open_time."""
    out = pd.DataFrame({KEY: df["open_time"].to_numpy()})
    cache: Dict[str, pd.Series] = {}
    for column, lag in sorted(refs):
        if column not in cache:
            if column in df.columns:
                cache[column] = pd.to_numeric(df[column], errors="coerce").reset_index(drop=True)
            elif kernels.is_kernel_column(column):
                cache[column] = kernels.compute(df.reset_index(drop=True), column)
            else:
                cache[column] = pd.Series(np.nan, index=range(len(df)))
        series = cache[column]
        out[lag_key(column, lag)] = (series.shift(lag) if lag else series).to_numpy()
    return out


HISTORY_START = 0   # chỉ báo tính từ đầu lịch sử dữ liệu (gốc cố định)


def needs_minute_path(eng) -> bool:
    """Có cần đường giá 1m trong nến chạy không: khung chạy > 1m và có chiến lược khớp SL "extreme". Hàm tự do để engine tham chiếu
    (test/reference_engine.py) đi qua cùng đường dữ liệu dùng chung."""
    return getattr(eng, "base_frame", "1m") != "1m" and any(getattr(tr, "stop_fill", "level") == "extreme" for tr in getattr(eng, "slots", []))


@dataclass
class RiskConfig:
    max_positions: int = 8
    max_per_symbol: int = 1
    max_gross_exposure: float = 3.0
    kill_switch_dd_pct: float = 30.0   # 0 = tắt
    max_open_risk_pct: float = 0.0     # trần Σ rủi ro tới SL (cả rổ DCA) của mọi vị thế đang mở, % vốn; lệnh mới bị thu nhỏ / chặn. 0 = tắt
    dd_throttle_pct: float = 0.0       # vốn đã chốt sụt d% so với đỉnh -> rủi ro lệnh mới × max(sàn, 1 − d / mức này). 0 = tắt
    dd_throttle_floor: float = 0.25    # hệ số rủi ro tối thiểu khi đang giảm theo mức sụt

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "RiskConfig":
        return config_from_dict(cls, d)


def data_cache_clear(data: Optional[DataSource] = None) -> None:
    """Xóa bộ nhớ đệm mảng (DataSource.memo) — gọi giữa các chiến lược ứng viên để giải phóng RAM."""
    data_source(data).memo.clear()


def aggregate_positions(positions) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
    """Lệnh đã đóng -> (by_strategy, by_symbol): {pnl_usd, trades, wins, fees_usd, funding_usd} — dùng chung cho engine danh mục và backtest tick."""
    by_strategy: Dict[str, Dict[str, float]] = {}
    by_symbol: Dict[str, Dict[str, float]] = {}
    for p in positions:
        for key, bucket in ((p.strategy_id, by_strategy), (p.symbol, by_symbol)):
            agg = bucket.setdefault(key, {"pnl_usd": 0.0, "trades": 0, "wins": 0, "fees_usd": 0.0, "funding_usd": 0.0})
            agg["pnl_usd"] += p.real_pnl
            agg["trades"] += 1
            agg["wins"] += int(p.real_pnl > 0)
            agg["fees_usd"] += p.fees_usd or 0.0
            agg["funding_usd"] += p.funding_usd or 0.0
    return by_strategy, by_symbol


def _strategy_flow(strategy: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": strategy["side"], "match": [{"condition": strategy["tree"]}], "stop": strategy.get("stop") or [],
            "dca": strategy.get("dca") or []}


SPOT_POSITION = {"market": "spot", "leverage": 1}    # ghi đè vị thế của chiến lược khi chạy trên DEX
POOL_TYPES = ("aerodrome_v2", "uniswap_v2")          # pool AMM có dự trữ trong tick (Sync): volatile x*y=k hoặc stable x³y+xy³=k


# is_dex_symbol / classify_symbols / require_perp (đọc thư mục dữ liệu): ở backend/crawl/store.py (engine-API pass — core không I/O).


def display_name(symbol: str) -> str:
    return symbol.split("@")[0].split(":")[-1]


def require_long_legs(strategy_ids: List[str], by_id: Mapping[str, Dict[str, Any]]) -> None:
    """by_id: {id chiến lược: định nghĩa} (optimize/book/build.BY_ID) — core không import sổ chiến lược."""
    short = [i for i in strategy_ids if by_id[i]["side"] != "LONG"]
    if short:
        raise ValueError(f"DEX là spot AMM — không bán khống được nên chỉ chạy chân LONG; bỏ chân SHORT / \"Cả hai chiều\": {short}")


def check_amm_pool(info: Dict[str, Any]) -> None:
    """Pool phải có dự trữ trong tick (loại v2 nhận diện được) và có mạng — nếu không thì không mô hình hoá được AMM."""
    if info["pool_type"] not in POOL_TYPES:
        raise ValueError(f"{info['symbol']}: loại pool {info['pool_type']!r} chưa hỗ trợ — chỉ pool có dự trữ (Aerodrome/Uniswap v2): {POOL_TYPES}")
    if not info["network"]:
        raise ValueError(f"{info['symbol']}: manifest thiếu network")


def tick_window(infos: List[Dict[str, Any]], start: Optional[int], end: Optional[int], frame_ms: int) -> Tuple[int, int]:
    """Cửa sổ chạy tick [W, E] (ms) = [start, end] cắt theo độ phủ tick chung của các tài sản: W làm tròn LÊN mốc nến cơ sở kế tiếp (nến tín hiệu đầu tiên
    phủ trọn bằng tick), E = min(end, tick cuối). Ngắn hơn một nến cơ sở -> ValueError."""
    for i in infos:
        if not i["ticks"]:
            raise ValueError(f"{i['symbol']}: chưa có tick — crawl tick (data_crawl_ticks) trước khi chạy backtest tick")
    lo, hi = max(int(i["ticks"]["start_ts"]) for i in infos), min(int(i["ticks"]["end_ts"]) for i in infos)
    w = max(int(start or 0), lo)
    w = -(-w // frame_ms) * frame_ms
    e = min(int(end) if end else hi, hi)
    if e - w < frame_ms:
        raise ValueError(f"cửa sổ tick sau khi cắt theo độ phủ tick ({lo}..{hi} ms) ngắn hơn một nến cơ sở ({frame_ms // 60_000} phút)")
    return w, e


KLINE_COLS = ["open_time", *DATA_COLUMNS, "close_time"]


def klines_frame(rows: List[List[Any]], now_ms: int) -> pd.DataFrame:
    """Nến sàn -> DataFrame engine; bỏ nến CHƯA đóng (close_time >= now)."""
    df = pd.DataFrame([r[:7] for r in rows], columns=KLINE_COLS)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["open_time"] = df["open_time"].astype("int64")
    df = df[df["close_time"].astype("int64") < now_ms].drop(columns=["close_time"]).reset_index(drop=True)
    df["is_filled"] = 0
    return df


def required_frames(symbol: str, strategies: List[Dict[str, Any]], base_frame: str) -> List[str]:
    """Các khung engine cần cho sổ (gồm khung chạy và 4h — engine luôn nạp 4h)."""
    eng, _ = _engine_slots(symbol, strategies, base_frame, 0, DAY)
    return sorted(set(eng._refs_by_frame()) | {base_frame, "4h"})



def _portfolio(symbol: str, strategies: List[Dict[str, Any]], base_frame: str, start: int, end: int):
    end = max(int(end), int(start) + DAY)
    start = max(int(start), end - 1000 * DAY)
    return SignalPortfolio([symbol], strategies, start, end, trade_start_ts=start, use_cache=False, base_frame=base_frame)


def _engine_slots(symbol: str, strategies: List[Dict[str, Any]], base_frame: str, start: int, end: int):
    """Engine của tài sản (chưa nạp dữ liệu) + [(chiến lược, SlotSpec)]. start/end chỉ để engine kiểm giới hạn độ dài — dữ liệu do evaluate gán trực tiếp."""
    pe = _portfolio(symbol, strategies, base_frame, start, end)
    return pe._make_slots(symbol, pe.ledger)


def matrix_evaluator(cols: Dict[str, np.ndarray], n: int) -> VectorEvaluator:
    """VectorEvaluator trên ma trận cột "khung|cột[__lagN]" (_build_matrix / kho dùng chung); cột thiếu = NaN. Một đường cho backtest, danh mục,
    tín hiệu sổ (evaluate_signals), ảnh chụp tín hiệu và kiểm tra tín hiệu."""
    return VectorEvaluator(n, lambda fr, c, lag: cols.get(f"{fr}|{lag_key(c, lag)}", np.full(n, np.nan)))


def _regime_labels(pairs: List[Tuple[Dict[str, Any], Any]], cols: Dict[str, np.ndarray], n: int, t: np.ndarray) -> Optional[Any]:
    """Nhãn regime của tài sản (None khi không chiến lược nào bật regime) — dùng chung cho PortfolioEngine.load_data và evaluate_signals."""
    if not any(st.get("regime") for st, _ in pairs):
        return None
    cfg = profile_cfg(next((st["regime"].get("classifier") for st, _ in pairs if st.get("regime")), None))
    return classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), t, cfg)


def _regime_gate(st: Dict[str, Any], labels: Optional[Any], match: np.ndarray, stop: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Lọc tín hiệu vào theo regime + cầu chì thoát khi sốc ngược chiều (chiến lược không bật regime / không có nhãn: giữ nguyên)."""
    if labels is not None and st.get("regime"):
        allowed, fuse = masks_for(st, st["side"], labels)
        match = match & allowed
        if fuse is not None:
            stop = stop | fuse
    return match, stop


def evaluate_signals(symbol: str, strategies: List[Dict[str, Any]], frames: Dict[str, pd.DataFrame], base_frame: str,
             with_vec: bool = False) -> Dict[str, Any]:
    """frames = {khung: DataFrame nến đã đóng từ đầu dữ liệu}. -> {"t": open_time nến chạy, "close", "high", "low",
    "entries": [{"strategy", "side", "match": bool[], "stop": bool[], "vol": float[] | None, "slot" (SlotSpec; "tracker" = tên cũ, cùng đối tượng)}]} (mảng theo nến chạy).
    with_vec: thêm "vec" (VectorEvaluator trên cùng ma trận) để giải thích từng điều kiện (metrics/charts.py::explain)."""
    base = frames[base_frame]
    eng, pairs = _engine_slots(symbol, strategies, base_frame, int(base["open_time"].iloc[0]), int(base["open_time"].iloc[-1]))
    base = eng._prepare_candles(base)
    eng.df_base, eng.df_base_hist = base, base
    eng.frames = {fr: (eng._enrich_4h(eng._prepare_candles(df)) if fr == "4h" else eng._prepare_candles(df))
                  for fr, df in frames.items() if fr != base_frame}
    eng.df_4h = eng.frames.get("4h")
    df1, cols = eng._build_matrix()
    n = len(df1)
    vec = matrix_evaluator(cols, n)
    out = {"t": df1["open_time"].to_numpy(dtype="int64"), "open": df1["open"].to_numpy(dtype=float), "close": df1["close"].to_numpy(dtype=float),
           "high": df1["high"].to_numpy(dtype=float), "low": df1["low"].to_numpy(dtype=float), "entries": []}
    labels = _regime_labels(pairs, cols, n, out["t"])
    for st, tr in pairs:
        match, stop = entry_event_mask(vec, cols, tr, eng.base_frame), vec.tree(tr.stop_tree)
        match, stop = _regime_gate(st, labels, match, stop)
        vcol = eng.vol_column(tr)
        out["entries"].append({"strategy": st["id"], "side": st["side"], "match": match, "stop": stop,
                               "vol": cols.get(vcol) if vcol else None, "slot": tr, "tracker": tr,
                               "dca": vec.tree(tr.dca_tree) if tr.dca_tree else None})
    if with_vec:
        out["vec"] = vec
    return out


def _bar_sig(v: Dict[str, Any], i: int) -> List[Dict[str, Any]]:
    return [{"match": bool(e["match"][i]), "stop": bool(e["stop"][i]), "vol": (float(e["vol"][i]) if e["vol"] is not None else None),
             "dca": bool(e["dca"][i]) if e.get("dca") is not None else True}
            for e in v["entries"]]


# ══════════════════════════════════════════════════════════════════════════
# Ảnh chụp tín hiệu (signal_snapshot) + kiểm tra tín hiệu (check_signals) — engine-API pass: chuyển từ core/signal.py (cần PortfolioEngine /
# BacktestEngine + nguồn dữ liệu). Phần giải thích/thống kê thuần (_explain, _since, _thin, _forward_bps, _stats, _verdict) vẫn ở core/signal.py.
# Chú thích đầy đủ: core/signal.py, các mục ảnh chụp tín hiệu (snapshot) và kiểm tra tín hiệu (diagnostics).
# ══════════════════════════════════════════════════════════════════════════

def signal_snapshot(symbol: str, strategies: List[Dict[str, Any]], end_ts: int, lookback_minutes: int = DEFAULT_LOOKBACK_MIN,
                    venue: str = "cex", data: Optional[DataSource] = None) -> Dict[str, Any]:
    """Tín hiệu của `strategies` (dạng chiến lược của PortfolioEngine) trên `symbol` tại nến 1m đã đóng cuối cùng <= end_ts.
    data: nguồn dữ liệu (None = mặc định của tiến trình)."""
    start = int(end_ts) - int(lookback_minutes) * MINUTE
    pe = SignalPortfolio([symbol], strategies, start, int(end_ts), trade_start_ts=start, venue=venue, use_cache=True, data=data)
    eng, pairs = pe._make_slots(symbol, pe.ledger)
    out: Dict[str, Any] = {"symbol": symbol, "bar_open_time": None, "as_of": None, "close": None, "regime": None, "strategies": []}
    if not pairs:
        return out
    eng.extra_refs = REGIME_REFS                     # regime luôn hiển thị, cùng cột đặc trưng với backtest bật regime
    eng.load_data()
    if eng.df_base is None or eng.df_base.empty:
        return out
    df1, cols = eng._build_matrix()
    n = len(df1)
    real = np.flatnonzero(df1["is_filled"].to_numpy() == 0)
    t_all = df1["open_time"].to_numpy(dtype="int64")
    real = real[t_all[real] < int(end_ts)]          # chỉ nến đã ĐÓNG trước end_ts
    if real.size == 0:
        return out
    i = int(real[-1])
    vec = matrix_evaluator(cols, n)
    t_real = t_all[real]
    out.update(bar_open_time=int(t_all[i]), as_of=int(t_all[i]) + MINUTE, close=_num(df1["close"].to_numpy()[i]))
    labels = classify(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), t_all)   # ngưỡng mặc định (hiển thị), không theo hồ sơ chiến lược
    raw = raw_states(lambda fr, c: cols.get(f"{fr}|{c}", np.full(n, np.nan)), n)
    name = REGIME_NAMES[int(labels[i])]
    out["regime"] = {"state": name, "label": REGIME_LABEL_VI[name], "raw": REGIME_NAMES[int(raw[i])],
                     "since": _since(labels[real], t_real, len(real) - 1),
                     "features": {f"{fr} {c}": _num(cols.get(f"{fr}|{c}", np.full(n, np.nan))[i])
                                  for fr, refs in sorted(REGIME_REFS.items()) for c, _ in sorted(refs)}}
    for st, tr in pairs:
        match, stop = vec.tree(tr.match_tree), vec.tree(tr.stop_tree)      # TRẠNG THÁI điều kiện (khớp entry_blocks); "entry_fires" mới là sự kiện bot dùng
        entry_raw = bool(match[i])
        fires = _regime_gate(st, labels, entry_event_mask(vec, cols, tr, eng.base_frame), stop)[0]   # cùng mặt nạ với PortfolioEngine.load_data
        match, stop = _regime_gate(st, labels, match, stop)
        m_real = match[real]
        out["strategies"].append({
            "id": st["id"], "side": st["side"], "entry": bool(match[i]), "entry_fires": bool(fires[i]), "exit": bool(stop[i]), "entry_raw": entry_raw,
            "entry_since": _since(m_real, t_real, len(real) - 1),
            "entry_minutes_in_window": int(m_real.sum()),
            "entry_blocks": _explain(vec, tr.match_tree, i), "exit_blocks": _explain(vec, tr.stop_tree, i),
            "regime_allowed": (st.get("regime") or {}).get("allowed"),
            "regime_ok": bool(not st.get("regime") or labels[i] in [REGIME_CODE[x] for x in st["regime"].get("allowed") or REGIME_NAMES]),
        })
    return out


def check_signals(symbol: str, signals: Dict[str, Dict[str, Any]], start_ts: Optional[int] = None,
                  end_ts: Optional[int] = None, horizons_min: Iterable[int] = HORIZONS_MIN,
                  baseline_step: int = 7, data: Optional[DataSource] = None) -> Dict[str, Any]:
    """Kiểm tra nhiều tín hiệu trên một tài sản (nạp dữ liệu + tính kernel một lần). data: nguồn dữ liệu (None = mặc định)."""
    from backend.models.params import VENUE_COSTS, build_params, manifest_venue

    manifest = data_source(data).manifest(symbol) or {}
    venue = manifest_venue(manifest)
    start_ts = int(start_ts or manifest.get("start_ts"))
    end_ts = int(end_ts or manifest.get("end_ts"))

    engine = SignalEngine(0, 0, symbol, start_ts, end_ts, data=data)
    names = list(signals)
    for name in names:  # flow LONG giả chỉ để engine biết cần tính kernel nào
        engine.add_strategy_flow(f"LONG_{name}", build_params(
            f"LONG_{name}", {"match": [{"condition": signals[name]["tree"]}], "stop": []}, "LONG", {}, venue))
    engine.load_data()
    df1, cols = engine._build_matrix()
    n = len(df1)
    vec = matrix_evaluator(cols, n)

    real = df1["is_filled"].to_numpy() == 0
    in_range = df1["open_time"].to_numpy() >= start_ts
    times = df1["open_time"].to_numpy(dtype="int64")[real]
    opens = df1["open"].to_numpy(dtype="float64")[real]
    closes = df1["close"].to_numpy(dtype="float64")[real]
    pos_of_row = np.cumsum(real) - 1  # vị trí trong mảng phút-thật của mỗi dòng
    base_idx = np.arange(0, len(times) - 1, baseline_step)
    base_idx = base_idx[times[base_idx] >= start_ts]

    results: Dict[str, Any] = {}
    for name in names:
        sig = signals[name]
        sign = 1.0 if sig.get("side", "LONG") == "LONG" else -1.0
        fire = vec.tree(sig["tree"]) & real & in_range
        entry = pos_of_row[np.nonzero(fire)[0]] + 1           # vào ở phút thật kế tiếp
        entry = np.unique(entry[entry < len(times)])
        costs = VENUE_COSTS[(venue, "spot" if sign > 0 else ("perp" if venue == "cex" else "spot"))]
        cost_bps = 2 * (costs[0] + costs[2]) * 1e4  # taker + trượt, hai chiều
        by_h = {}
        for h in horizons_min:
            ev_idx = entry[_thin(times[entry], h * 60_000)] if len(entry) else entry
            ev = _forward_bps(times, opens, closes, ev_idx, h * 60_000, sign) if len(ev_idx) else np.array([])
            base = _forward_bps(times, opens, closes, base_idx, h * 60_000, sign)
            by_h[h] = _stats(ev, base, cost_bps)
        results[name] = {
            "side": sig.get("side", "LONG"),
            "family": sig.get("family"),
            "raw_signal_minutes": int(fire.sum()),
            "cost_bps_round_trip": round(cost_bps, 1),
            "horizons": by_h,
            **_verdict(by_h),
        }
    return {"symbol": symbol, "venue": venue, "start_ts": start_ts, "end_ts": end_ts, "signals": results}


# ══════════════════════════════════════════════════════════════════════════
# Dựng kế hoạch chạy (hằng số profile ở core/params.py)
#
# Thực thi chương trình DSL (docs/bmad/p7_python_strategies.md §5): chương trình đã biên dịch -> chiến lược của PortfolioEngine.
#
# Một cấu hình thực thi duy nhất = mặc định của engine Nora: perp OKX, khối lượng theo rủi ro (BASE_POSITION), SL 3×ATR (NORA_DEFAULTS), trần đòn bẩy,
# cooldown 60 phút, RiskConfig mặc định của sổ. Ghi đè bằng thuộc tính lớp của chiến lược hoặc `position` (khoá của params.builder.POSITION_KEYS).
#
# Tín hiệu là cột `py_<hash12>_<le|lx|se|sx>` (core/indicator.py::register_program): vào = [cột le/se] > 0,5; thoát = [cột lx/sx] > 0,5.
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Plan:
    strategies: List[Dict[str, Any]]
    symbols: List[str]                       # ký hiệu dữ liệu cho PortfolioEngine ("BTC@perp")
    risk: Dict[str, Any]
    base_frame: str
    venue: str = "cex"
    warnings: List[str] = field(default_factory=list)
    echo: Dict[str, Any] = field(default_factory=dict)   # cấu hình hiệu lực (vào result.json)


def _ref(program: Program, kind: str) -> Dict[str, Any]:
    return {"frame": program.timeframe, "column": program.column(kind), "index": 0}


def _tree(program: Program, kind: str) -> List:
    return [[[_ref(program, kind), ">", 0.5]]]


def _leg_signals(program: Program, side: str) -> Tuple[List, List]:
    """(cây vào, stop) của một chân: stop theo dạng materialize(): [{"condition": cây}]."""
    ent, ext = ("le", "lx") if side == "LONG" else ("se", "sx")
    return _tree(program, ent), [{"condition": _tree(program, ext)}]


def leg_level(program: Program, side: str, warnings: List[str]) -> float:
    """Mức |position| lớn nhất của chân; nhiều mức khác nhau -> cảnh báo (v1 chỉ dùng mức lớn nhất)."""
    levels = sorted({abs(lv) for lv in program.levels if (lv > 0 if side == "LONG" else lv < 0)})
    if len(levels) > 1:
        warnings.append(f"Chân {side} có nhiều mức position khác nhau {levels}: v1 dùng mức lớn nhất ({levels[-1]:g}) cho mọi lệnh vào, "
                        "không tăng/giảm vị thế theo mức")
    return levels[-1]


def build_plan(program: Program, symbols: List[str], position: Optional[Dict[str, Any]] = None, strategy_id: Optional[str] = None,
               run_frame: Optional[str] = None, exact_id: bool = False, data: Optional[DataSource] = None) -> Plan:
    """strategy_id: tiền tố id chiến lược (mặc định py_<hash12>). exact_id: chương trình một chân -> id chiến lược = strategy_id đúng nguyên văn
    (kiểm parity với chiến lược lõi cùng id). data: nguồn dữ liệu (tên tài sản trần — DataSource.base_name); None = mặc định."""
    if not symbols:
        raise ValueError("Cần ít nhất một tài sản")
    legs = program.legs
    if not legs:
        raise ValueError("Chương trình không có chân nào có mức position khác 0 (chỉ có set_positions(..., position=0))")
    warnings: List[str] = []
    base = run_frame or RUN_FRAME
    if base not in FRAME_ORDER:
        raise ValueError(f"run_frame phải thuộc {list(FRAMES)}")
    if FRAME_ORDER[program.timeframe] < FRAME_ORDER[base]:
        raise ValueError(f"timeframe của chiến lược ({program.timeframe}) nhỏ hơn khung chạy {base}")
    sid = strategy_id or f"py_{program.code_hash}"
    pos = resolve_position_auto({**BASE_POSITION, **NORA_DEFAULTS, **_check_position(program.position_overrides), **_check_position(position or {})}, program.timeframe)
    user_keys = set(program.position_overrides) | set(position or {})
    defaulted = [k for k in NORA_DEFAULTS if k not in user_keys]
    if defaulted:
        warnings.append("Dùng mặc định của engine cho " + ", ".join(f"{k}={NORA_DEFAULTS[k]}" for k in defaulted)
                        + f" (rủi ro {pos['risk_per_trade_pct']}%/lệnh, SL tính theo ATR); khai báo trong code hoặc `position` để đổi")
    if FRAME_ORDER.get(str(pos.get("atr_frame")), 0) < FRAME_ORDER[base]:
        raise ValueError(f"atr_frame {pos.get('atr_frame')} nhỏ hơn khung chạy {base}")
    src = data_source(data)
    names = list(dict.fromkeys(src.base_name(s) for s in symbols))
    data_symbols = [f"{n}@perp" for n in names]
    strategies = []
    for side in legs:
        leg_level(program, side, warnings)    # chỉ để cảnh báo; định cỡ theo rủi ro, bỏ qua độ lớn mức
        tree, stop = _leg_signals(program, side)
        strategies.append({"id": sid if exact_id and len(legs) == 1 else f"{sid}_{side.lower()}", "side": side, "tree": tree, "stop": stop,
                           "position": dict(pos)})
    return Plan(strategies, data_symbols, dict(RISK), base, "cex", warnings, {"position": pos})


def _check_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    from backend.models.params import POSITION_KEYS
    bad = sorted(set(pos) - set(POSITION_KEYS))
    if bad:
        raise ValueError(f"khoá vị thế không hợp lệ: {bad}; có: {sorted(POSITION_KEYS)}")
    for k, v in pos.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError(f"vị thế {k}: phải là số hoặc chuỗi, nhận {v!r}")
    return dict(pos)


NAN = float("nan")


class OrderKind(IntEnum):
    ENTRY = 1   # market, mở tầng đầu
    EXIT = 2    # market, đóng hết (tín hiệu thoát / hết thời gian / kill)
    DCA = 3     # limit nhồi tầng
    SL = 4      # stop-loss đóng hết (từ giá TB)
    TRAIL = 5   # trailing stop đóng hết
    TP = 6      # limit chốt lời đóng hết (từ giá TB)


@dataclass
class Order:
    id: int
    slot: int
    kind: OrderKind
    is_buy: bool
    level: float = NAN          # DCA/SL/TRAIL/TP: mức giá đặt; ENTRY/EXIT: nan (market ở open)
    trigger: float = NAN        # DCA/TP có limit_through: mức phải đi QUA; mặc định (nan) = level
    notional: float = 0.0       # ENTRY/DCA (sim tính qty = notional / giá khớp); EXIT/SL/TRAIL/TP: đóng hết
    margin: float = 0.0
    reason: str = ""            # nhãn close_reason / start_reason của tracker
    reduce_only: bool = False
    post_only: bool = False
    # TRAIL (P6.8b): `level` luôn là mức stop TĨNH tính từ đỉnh các nến trước (SimVenue đọc mức này). Venue có trailing gốc (OKX) đọc thêm
    # `activation` (giá kích hoạt) và `callback_pct` (% lùi khỏi đỉnh, vd 1.5 = 1.5%); thiếu (nan) thì rơi về level / trigger như quy ước cũ.
    activation: float = NAN
    callback_pct: float = NAN
    # TRAIL cho SimVenue đường ohlc/adaptive: `peak` = đỉnh/đáy có lợi các nến TRƯỚC (venue tự chạy tiếp theo từng chặng của nến) và
    # `activation_pct` = ngưỡng lãi % để bật trailing (so với avg hiện tại); thiếu (nan) thì venue dùng `level` tĩnh như đường cũ.
    peak: float = NAN
    activation_pct: float = NAN


@dataclass(frozen=True)
class VenueCaps:
    generates_liquidation: bool   # venue tự sinh Fill thanh lý (sim); sàn thật chỉ quan sát
    native_trailing: bool         # venue có lệnh trailing gốc (OKX); sim dùng mức tĩnh tính từ đỉnh các nến trước
    post_only: bool               # venue hỗ trợ post_only cho lệnh limit
    rounds_qty: bool              # venue làm tròn qty/giá theo bộ lọc sàn


class Venue(Protocol):
    caps: VenueCaps

    def submit(self, order: Order) -> None: ...
    def cancel(self, order_id: int) -> None: ...
    def cancel_slot(self, slot: int) -> None: ...
    def open_orders(self, slot: int) -> List[Order]: ...
    def next_event(self, slot: int) -> Optional[Union[Fill, OrderRejected]]: ...


_ORDER_ID = itertools.count(1)


def new_order_id() -> int:
    """Cấp `Order.id` mới (toàn cục, tăng dần). Tách khỏi `models._ID_SEQ` để việc đặt/huỷ lệnh chờ không tiêu id của OrderModel."""
    return next(_ORDER_ID)


class SignalEngine:
    """Điều phối dữ liệu, tín hiệu và các flow chiến lược."""

    MAX_BACKTEST_DAYS = 1100
    MAX_STRATEGIES = 100
    KELTNER_CONFIGS = ((17, 0.5), (20, 1.5))
    MTM_SAMPLE_MINUTES = 60   # mẫu vốn MTM mỗi giờ (+ mỗi lần đóng lệnh); kernel bỏ qua phút rảnh, kết quả như vòng lặp từng phút

    def __init__(self, account_id: int, campaign_id: int, symbol: str, start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = DEFAULT_CAPITAL, base_frame: str = "1m",
                 data: Optional[DataSource] = None):
        """data: nguồn dữ liệu (core/models.DataSource); None = nguồn mặc định của tiến trình (set_default_data_source)."""
        if base_frame not in FRAME_MS:
            raise ValueError(f"Khung chạy không hợp lệ: {base_frame!r} (có: {list(FRAME_MS)})")
        self.base_frame = base_frame   # khung nến dùng để MÔ PHỎNG (khớp lệnh, SL/TP theo high/low của nến này)
        self.data = data
        self.account_id = account_id
        self.campaign_id = campaign_id
        self.symbol = symbol
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.trade_start_ts = trade_start_ts if trade_start_ts is not None else start_ts
        self.initial_capital = float(initial_capital)

        days_diff = (end_ts - start_ts) / (86400 * 1000)
        if days_diff > self.MAX_BACKTEST_DAYS:
            raise ValueError(
                f"Limit Exceeded: Yêu cầu chạy {days_diff:.1f} ngày. "
                f"Server chỉ cho phép tối đa {self.MAX_BACKTEST_DAYS} ngày để bảo vệ tài nguyên!"
            )

        self.slots: List[SlotSpec] = []
        self.slot_views: List[Any] = []   # trạng thái cuối của từng slot sau run() (SlotView)
        self.ledger = CapitalLedger(self.initial_capital)
        self.funding: Optional[pd.DataFrame] = None  # perp: funding_time, rate
        self.df_base: Optional[pd.DataFrame] = None        # nến khung chạy của cửa sổ (đã gồm warmup)
        self.df_base_hist: Optional[pd.DataFrame] = None   # lịch sử khung chạy từ gốc (chỉ khi có cột của chính khung chạy)
        self.df_4h: Optional[pd.DataFrame] = None
        self.frames: Dict[str, pd.DataFrame] = {}
        self.closed_positions = []
        self.orders = []
        self.equity_curve: List[Dict[str, float]] = []

    # ─── Cấu hình ───────────────────────────────────────────────────────────
    def add_strategy_flow(self, flow_name: str, params: StrategyParams):
        if len(self.slots) >= self.MAX_STRATEGIES:
            raise ValueError(f"Chỉ cho phép tối đa {self.MAX_STRATEGIES} strategy flows mỗi lần chạy.")
        ast = params.extra.get("ast", {}) if isinstance(params.extra, dict) else {}
        ast_type = str(ast.get("type", "") or params.extra.get("type", "")).upper()
        if ast_type == "LONG":
            pos_type = PositionType.LONG
        elif ast_type == "SHORT":
            pos_type = PositionType.SHORT
        else:
            pos_type = PositionType.LONG if "LONG" in flow_name.upper() else PositionType.SHORT
        self.slots.append(SlotSpec(
            account_id=self.account_id, campaign_id=self.campaign_id, symbol=self.symbol, flow_name=flow_name,
            params=params, pos_type=pos_type, initial_capital=self.initial_capital, entry_equity=self.ledger.equity,
        ))

    def _refs_by_frame(self) -> Dict[str, Set[Tuple[str, int]]]:
        by_frame: Dict[str, Set[Tuple[str, int]]] = {}
        for frame, refs in (getattr(self, "extra_refs", None) or {}).items():   # vd. đặc trưng regime (core/regime)
            by_frame.setdefault(frame, set()).update(refs)
        for tracker in self.slots:
            for frame, column, lag in (collect_field_refs(tracker.match_tree) | collect_field_refs(tracker.stop_tree)
                                       | collect_field_refs(tracker.dca_tree)):
                by_frame.setdefault(frame, set()).add((column, lag))
            if tracker.exit_unit == "atr":  # ATR% cho SL/TP/trailing theo biến động
                by_frame.setdefault(tracker.atr_frame, set()).add((f"natr_{tracker.atr_period}", 0))
        return by_frame

    @staticmethod
    def vol_column(tracker: Any) -> Optional[str]:
        return f"{tracker.atr_frame}|natr_{tracker.atr_period}" if tracker.exit_unit == "atr" else None

    def _warmup_ms(self, frame: str, refs: Set[Tuple[str, int]]) -> int:
        bars = max([kernels.warmup_bars(c) + lag for c, lag in refs] + [0])
        return (bars + 2) * FRAME_MS[frame]

    # ─── Dữ liệu ────────────────────────────────────────────────────────────
    def check_frames(self, refs: Optional[Dict[str, Set[Tuple[str, int]]]] = None) -> None:
        """Mọi khung tín hiệu / ATR phải >= khung chạy (không thể nhìn nến nhỏ hơn nến đang mô phỏng)."""
        refs = self._refs_by_frame() if refs is None else refs
        small = sorted(fr for fr in refs if fr in FRAME_MS and FRAME_MS[fr] < FRAME_MS[self.base_frame])
        if small:
            raise ValueError(f"Khung {small} nhỏ hơn khung chạy {self.base_frame} — chọn khung tín hiệu/ATR >= {self.base_frame}")

    def _src(self) -> DataSource:
        return data_source(getattr(self, "data", None))

    def load_data(self):
        refs = self._refs_by_frame()
        self.check_frames(refs)
        base = self.base_frame
        warm = self._warmup_ms(base, refs.get(base, set()))
        src = self._src()
        # df_base = nến của KHUNG CHẠY (mặc định 1m)
        self.df_base = self._prepare_candles(src.candles(self.symbol, base, self.start_ts - warm, self.end_ts))
        # chỉ báo trên chính khung chạy tính từ đầu lịch sử (gốc cố định) -> cần cả lịch sử khi có cột của khung chạy
        self.df_base_hist = src.candles(self.symbol, base, HISTORY_START, self.end_ts) if refs.get(base) else None
        if self.trade_start_ts < self.start_ts:
            self.trade_start_ts = self.start_ts

        self.load_frames(refs)
        if any(tr.market == "perp" for tr in self.slots):
            self.funding = self._load_funding()

    def minute_path(self, open_time: np.ndarray) -> Dict[str, np.ndarray]:
        """Đường giá 1m bên trong từng nến chạy (khung chạy > 1m) — cho khớp "extreme" đúng ngữ nghĩa 1m: lệnh stop khớp ở giá xấu nhất của
        NẾN 1m ĐẦU TIÊN chạm mức, không phải của cả nến 15m/1h/4h (quá bi quan, phụ thuộc khung chạy).
        -> {"m_a", "m_b": int64 (n) — nến chạy i gồm nến 1m [m_a[i], m_b[i]), "m_l", "m_h": float64}. Khung chạy 1m: mảng rỗng."""
        t = np.asarray(open_time, dtype="int64")
        if self.base_frame == "1m" or len(t) == 0:
            return {"m_a": np.zeros(0, dtype="int64"), "m_b": np.zeros(0, dtype="int64"), "m_l": np.zeros(0), "m_h": np.zeros(0)}
        step = FRAME_MS[self.base_frame]
        m1 = self._src().candles(self.symbol, "1m", int(t[0]), int(t[-1]) + step - 1,
                                 columns=["open_time", "high", "low", "is_filled"], use_cache=False)
        if "is_filled" in m1.columns:   # nến 1m điền (không giao dịch) không thể khớp lệnh
            m1 = m1[pd.to_numeric(m1["is_filled"], errors="coerce").fillna(0).astype(int) == 0]
        mt = m1["open_time"].to_numpy(dtype="int64")
        return {"m_a": np.searchsorted(mt, t).astype("int64"), "m_b": np.searchsorted(mt, t + step).astype("int64"),
                "m_l": m1["low"].to_numpy(dtype="float64"), "m_h": m1["high"].to_numpy(dtype="float64")}

    def needs_minute_path(self) -> bool:
        return needs_minute_path(self)

    def load_frames(self, refs: Optional[Dict[str, Set[Tuple[str, int]]]] = None) -> None:
        """Nạp các khung lớn (không gồm 1m) từ ĐẦU lịch sử dữ liệu tới end_ts: chỉ báo tính từ gốc cố định (như TradingView) nên giá trị
        tại nến t không phụ thuộc cửa sổ backtest bắt đầu ở đâu (chỉ phụ thuộc dữ liệu <= t)."""
        refs = self._refs_by_frame() if refs is None else refs
        for frame in sorted(set(refs) | {"4h"}):
            if frame == self.base_frame or frame not in FRAME_MS or FRAME_MS[frame] < FRAME_MS[self.base_frame]:
                continue
            df = self._prepare_candles(self._src().candles(self.symbol, frame, HISTORY_START, self.end_ts))
            self.frames[frame] = self._enrich_4h(df) if frame == "4h" else df
        self.df_4h = self.frames.get("4h")

    def _load_funding(self) -> Optional[pd.DataFrame]:
        """funding.pkl của instrument perp (nếu symbol là BTC@perp; DataSource.funding). Không có -> None (ghi rõ trong kết quả)."""
        df = self._src().funding(self.symbol)
        if df is None:
            return None
        return df[(df["funding_time"] >= self.start_ts) & (df["funding_time"] <= self.end_ts)].sort_values("funding_time")

    # ─── Chạy ───────────────────────────────────────────────────────────────
    def _build_matrix(self, only: Optional[Set[str]] = None) -> Tuple[pd.DataFrame, Dict[str, np.ndarray]]:
        """only: chỉ tính các cột có tên trong tập này ("khung|cột[__lagN]") — dữ liệu dùng chung điền cột còn thiếu.
        Mỗi cột tính độc lập trên khung đã nạp theo refs ĐẦY ĐỦ (frame_features), nên giá trị y hệt khi tính cả bộ."""
        df1 = self._prepare_candles(self.df_base)
        if "is_filled" not in df1.columns:
            df1["is_filled"] = 0
        df1["is_filled"] = pd.to_numeric(df1["is_filled"], errors="coerce").fillna(0).astype(int)
        refs = self._refs_by_frame()
        if only is not None:
            refs = {fr: {(c, lag) for c, lag in rs if f"{fr}|{lag_key(c, lag)}" in only} for fr, rs in refs.items()}
            refs = {fr: rs for fr, rs in refs.items() if rs}
        cols: Dict[str, np.ndarray] = {}
        open_time = df1["open_time"].to_numpy()
        base = self.base_frame
        fresh_frames = slot_fresh_frames(self.slots, base)    # khung cần cột sự kiện (tín hiệu vào theo sự kiện)
        for frame in ([base] if base in refs else []) + [f for f in refs if f != base]:
            if frame not in FRAME_MS:
                continue
            t_frame, vals = self.frame_values(frame, refs[frame])
            idx = self.align_index(frame, t_frame, open_time, base)
            for cid, v in vals.items():
                cols[cid] = self.gather(v, idx)
            if frame in fresh_frames and (only is None or f"{frame}|{FRESH}" in only):
                cols[f"{frame}|{FRESH}"] = frame_fresh(idx, df1["is_filled"].to_numpy() == 0)
        return df1, cols

    def frame_values(self, frame: str, refs: Set[Tuple[str, int]]) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """Giá trị các cột `refs` của khung `frame` trên MỌI nến của khung từ đầu lịch sử (gốc cố định) -> (open_time nến, {cid: giá trị}).
        Khung 1m: chỉ phút có giao dịch (bỏ nến điền). Khung lớn: các nến đã nạp bằng load_frames. Mỗi cột tính độc lập."""
        if frame == self.base_frame:
            src = getattr(self, "df_base_hist", None)
            if src is None:
                src = self.df_base       # dữ liệu gán thẳng (test) = toàn bộ lịch sử
            if src is None:            # đường dữ liệu dùng chung: engine chưa nạp gì
                src = self._src().candles(self.symbol, frame, HISTORY_START, self.end_ts)
            src = self._prepare_candles(src)
            if "is_filled" in src.columns:
                src = src[pd.to_numeric(src["is_filled"], errors="coerce").fillna(0).astype(int) == 0].reset_index(drop=True)
            if frame == "4h":
                src = self._enrich_4h(src)
        elif frame == "4h" and self.df_4h is not None and not self.df_4h.empty:
            src = self._enrich_4h(self._prepare_candles(self.df_4h))
        else:
            src = self.frames.get(frame)
        if src is None or src.empty:
            return np.zeros(0, dtype="int64"), {f"{frame}|{lag_key(c, lag)}": np.zeros(0) for c, lag in sorted(refs)}
        feat = frame_features(src, refs)
        return (feat[KEY].to_numpy(dtype="int64"),
                {f"{frame}|{name}": feat[name].to_numpy(dtype="float64") for name in feat.columns if name != KEY})

    @staticmethod
    def align_index(frame: str, t_frame: np.ndarray, open_time: np.ndarray, base: str = "1m") -> np.ndarray:
        """Chỉ số nến khung dùng ở từng nến chạy `open_time` (-1 = chưa có). Khung = khung chạy: đúng nến đó (nến không giao dịch -> -1).
        Khung lớn hơn: nến cuối ĐÃ ĐÓNG trước thời điểm quyết định (open + độ dài khung <= t + độ dài nến chạy); open_time khung tăng ngặt
        (_prepare_candles bỏ trùng) nên searchsorted phải − 1 chọn đúng nến như merge_asof(direction="backward")."""
        q = np.asarray(open_time, dtype="int64")
        if len(t_frame) == 0:
            return np.full(len(q), -1, dtype="int64")
        if frame == base:
            pos = np.searchsorted(t_frame, q)
            hit = pos < len(t_frame)
            hit[hit] = t_frame[pos[hit]] == q[hit]
            pos[~hit] = -1
            return pos.astype("int64")
        return (np.searchsorted(t_frame + FRAME_MS[frame], q + FRAME_MS[base], side="right") - 1).astype("int64")

    @staticmethod
    def gather(vals: np.ndarray, idx: np.ndarray) -> np.ndarray:
        """Giá trị theo chỉ số căn phút (-1 -> NaN)."""
        if len(vals) == 0:
            return np.full(len(idx), np.nan)
        out = vals[np.maximum(idx, 0)]
        out[idx < 0] = np.nan
        return out



    # ─── Tiện ích dữ liệu ───────────────────────────────────────────────────
    @staticmethod
    def _prepare_candles(df: Optional[pd.DataFrame]) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        if "open_time" not in df.columns:
            raise ValueError("Candle data thiếu cột open_time.")
        ot = df["open_time"]
        if (ot.dtype == np.int64 and all(df[c].dtype.kind in "fiu" for c in DATA_COLUMNS if c in df.columns)
                and (len(ot) < 2 or bool((np.diff(ot.to_numpy()) > 0).all()))):
            return df.reset_index(drop=True)      # đã sạch (int64 tăng ngặt, cột số): các bước dưới là no-op -> chỉ cần bản sao (reset_index sao chép)
        clean = df.reset_index(drop=True).copy()
        clean["open_time"] = pd.to_numeric(clean["open_time"], errors="coerce")
        clean = clean.dropna(subset=["open_time"])
        clean["open_time"] = clean["open_time"].astype("int64")
        for column in DATA_COLUMNS:
            if column in clean.columns:
                clean[column] = pd.to_numeric(clean[column], errors="coerce")
        return clean.sort_values("open_time").drop_duplicates(subset=["open_time"], keep="last").reset_index(drop=True)

    @classmethod
    def _enrich_4h(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Cột 4h kiểu cũ (atr*, Keltner kup/kmid/klo) — giữ để tương thích template cũ."""
        if df is None or df.empty or not {"high", "low", "close"}.issubset(df.columns):
            return df
        if "kup20_15" in df.columns:
            return df
        enriched = df.copy()
        high, low, close = enriched["high"], enriched["low"], enriched["close"]
        prev_close = close.shift(1)
        true_range = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
                               axis=1).max(axis=1)
        for period in (14, 17, 20):
            enriched[f"atr{period}"] = true_range.rolling(period, min_periods=1).mean()
        enriched["atr"] = enriched["atr17"]
        for period, multiplier in cls.KELTNER_CONFIGS:
            mid = close.ewm(span=period, adjust=False, min_periods=1).mean()
            suffix = f"{period}_{str(multiplier).replace('.', '')}"
            enriched[f"kmid{suffix}"] = mid
            enriched[f"kup{suffix}"] = mid + enriched[f"atr{period}"] * multiplier
            enriched[f"klo{suffix}"] = mid - enriched[f"atr{period}"] * multiplier
        return enriched

    @staticmethod
    def _keltner_suffix(period: int, multiplier: float) -> str:
        return f"{period}_{str(multiplier).replace('.', '')}"


class SignalPortfolio:
    """Phần dựng slot của PortfolioEngine cũ (không nạp dữ liệu danh mục / không chạy): đủ cho evaluate_signals / signal_snapshot."""

    def __init__(self, symbols: List[str], strategies: List[Dict[str, Any]], start_ts: int, end_ts: int,
                 trade_start_ts: Optional[int] = None, initial_capital: float = DEFAULT_CAPITAL,
                 risk: Optional[RiskConfig] = None, venue: str = "cex", use_cache: bool = True,
                 shared_dir: Optional[str] = None, close_at_end: bool = True, base_frame: str = "1m",
                 data: Optional[DataSource] = None):
        """data: nguồn dữ liệu (core/models.DataSource); None = nguồn mặc định của tiến trình (set_default_data_source).
        base_frame: khung nến dùng để mô phỏng (1m mặc định; 15m/1h/4h chạy nhanh hơn nhiều, khung tín hiệu phải >= khung chạy).
        strategies: [{"id", "side": LONG|SHORT, "tree": AST đã thay tham số, "position": {...POSITION_KEYS}}].
        Khoá tuỳ chọn "symbols": [..] giới hạn chiến lược đó chỉ chạy trên các tài sản này (mặc định: mọi tài sản).
        close_at_end=False: KHÔNG đóng vị thế còn mở ở cuối dữ liệu (vốn cuối vẫn là MTM) — xem open_positions() (feed giả lập).
        shared_dir: thư mục dữ liệu mmap dùng chung (DataSource.shared_*; optimize/search/evaluate.py); mặc định env NORA_SHARED_DATA_DIR.
        Có thì _load_symbol ưu tiên đọc mmap (chỉ đọc) thay vì tự dựng; không thấy khoá thì dựng như cũ."""
        if not symbols or not strategies:
            raise ValueError("Cần ít nhất một tài sản và một chiến lược")
        ids = [s["id"] for s in strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("id chiến lược phải khác nhau")
        self.symbols = list(symbols)
        self.strategies = strategies
        self.start_ts, self.end_ts = int(start_ts), int(end_ts)
        self.trade_start_ts = int(trade_start_ts if trade_start_ts is not None else start_ts)
        self.initial_capital = float(initial_capital)
        self.risk = risk or RiskConfig()
        self.venue = venue
        self.use_cache = use_cache
        self.data = data
        self.shared_dir = shared_dir or os.environ.get("NORA_SHARED_DATA_DIR") or None
        self.ledger = CapitalLedger(self.initial_capital)
        self.books: List[Dict[str, Any]] = []   # mỗi tài sản: dữ liệu + trackers
        self.closed_positions: List[Any] = []
        self.orders: List[Any] = []
        self.equity_curve: List[Dict[str, float]] = []
        self.halted_at: Optional[int] = None
        self.ruined_at: Optional[int] = None
        self.rejected_for_risk = 0           # số PHÚT lệnh vào bị chặn bởi giới hạn rủi ro (giữ nguyên nghĩa, golden dựa vào đây)
        self.risk_blocked_attempts = 0       # số LẦN vào lệnh bị chặn: các phút liên tiếp của cùng một tracker tính là một lần
        self.close_at_end = close_at_end
        self.base_frame = base_frame
        self.last_close: Dict[str, float] = {}   # giá đóng cửa cuối của từng tài sản (đặt khi run() xong)

    def _src(self) -> DataSource:
        return data_source(getattr(self, "data", None))

    def _make_slots(self, symbol: str, ledger: CapitalLedger) -> Tuple[SignalEngine, List[Tuple[Dict, SlotSpec]]]:
        from backend.models.params import build_params, manifest_pool_fee
        eng = SignalEngine(0, 0, symbol, self.start_ts, self.end_ts, trade_start_ts=self.trade_start_ts,
                             initial_capital=self.initial_capital, base_frame=self.base_frame, data=getattr(self, "data", None))
        eng.ledger = ledger
        pairs = []
        pool_fee = None
        for st in self.strategies:
            if st.get("symbols") and symbol not in st["symbols"]:
                continue
            if st.get("regime"):   # đặc trưng regime đi qua cùng bộ máy căn khung với tín hiệu
                eng.extra_refs = REGIME_REFS
            name = f"{st['side']}_{st['id']}"
            if self.venue == "dex" and st["position"].get("fee_rate") is None and pool_fee is None:   # phí pool đã xác minh (manifest)
                pool_fee = manifest_pool_fee(self._src().manifest(symbol)) if symbol else None
            eng.add_strategy_flow(name, build_params(name, _strategy_flow(st), st["side"], st["position"],
                                                     self.venue, pool_fee=pool_fee))
            pairs.append((st, eng.slots[-1]))
        return eng, pairs
