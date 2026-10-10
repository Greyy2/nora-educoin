"""Sinh alpha (P9.6): lưới/mẫu tham số, id alpha, biến thể regime, kiểm S0. Nguồn: docs/bmad/p9_review_log.md (mục P9.6).
"""
import hashlib
import json
import random
import sys
from typing import Any, Dict, Iterator, List, Optional


# ══════════════════════════════════════════════════════════════════════════
# S0: sinh alpha từ không gian tham số của chiến lược (strategy_book.CANDIDATES) + kiểm tính hợp lệ.
#
# alpha_id = sha1(chiến lược + "|" + JSON chuẩn hoá của tham số)[:ALPHA_ID_LEN] — cùng (chiến lược, tham số) luôn cùng id, ở mọi lượt chạy.
# Lấy mẫu CÙNG thuật toán build_strategy_book.iter_configs (lấy mẫu theo CHỈ SỐ của lưới, không dựng lưới): n < kích thước lưới -> random.Random(seed).sample.
# ══════════════════════════════════════════════════════════════════════════

def canonical_params(params: Dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def alpha_id_of(strategy: str, params: Dict[str, Any]) -> str:
    from backend.optimize.funnel import stages as gates
    return hashlib.sha1(f"{strategy}|{canonical_params(params)}".encode("utf-8")).hexdigest()[:gates.ALPHA_ID_LEN]


def grid_size(space: Dict[str, List[Any]]) -> int:
    total = 1
    for k in space:
        total *= len(space[k])
    return total


def iter_params(space: Dict[str, List[Any]], n: Optional[int], seed: int, full_grid: bool = False) -> Iterator[Dict[str, Any]]:
    """Sinh lười từng bộ tham số: full_grid hoặc n >= kích thước lưới -> toàn lưới (thứ tự product theo khoá sắp xếp); ngược lại n vị trí ngẫu nhiên không lặp."""
    keys = sorted(space)
    sizes = [len(space[k]) for k in keys]
    total = grid_size(space)
    if full_grid or n is None or total <= n:
        positions = range(total)
    elif total <= sys.maxsize:
        positions = random.Random(seed).sample(range(total), int(n))
    else:   # không gian khổng lồ (> 2^63): rút ngẫu nhiên không lặp
        rng = random.Random(seed)

        def _draw():
            seen = set()
            while len(seen) < n:
                x = rng.randrange(total)
                if x not in seen:
                    seen.add(x)
                    yield x
        positions = _draw()
    for pos in positions:
        vals, r = [], pos
        for k, sz in zip(reversed(keys), reversed(sizes)):
            r, m = divmod(r, sz)
            vals.append(space[k][m])
        vals.reverse()
        yield dict(zip(keys, vals))


SIGNAL_POSITION_KEYS = ("exit_unit", "atr_frame", "atr_period")   # đổi cột tín hiệu ATR -> cùng nhóm tín hiệu
PER_SIGNAL = 20                                                  # schema: số bộ tham số vị thế/thoát lệnh cho mỗi bộ tín hiệu


def iter_params_factored(space: Dict[str, List[Any]], n: int, seed: int, per_signal: int = PER_SIGNAL) -> Iterator[Dict[str, Any]]:
    """Lấy mẫu PHÂN TẦNG (chế độ schema): rút một bộ tham số tín hiệu (sig.* + khung/chu kỳ ATR) rồi `per_signal` bộ tham số vị thế/thoát lệnh
    cho bộ tín hiệu đó -> các alpha cùng tín hiệu đi chung một nhóm run_many (nạp dữ liệu + tính tín hiệu một lần). Tất định theo seed;
    không lặp (bộ trùng bị bỏ, rút tiếp)."""
    sig_keys = sorted(k for k in space if k.startswith("sig.") or k in SIGNAL_POSITION_KEYS)
    pos_keys = sorted(k for k in space if k not in sig_keys)
    rng = random.Random(seed)
    seen = set()
    made = 0
    tries = 0
    while made < n and tries < n * 20:
        sig = {k: rng.choice(space[k]) for k in sig_keys}
        for _ in range(min(per_signal, n - made)):
            tries += 1
            p = {**sig, **{k: rng.choice(space[k]) for k in pos_keys}}
            key = canonical_params(p)
            if key in seen:
                continue
            seen.add(key)
            made += 1
            yield p


def count_params(space: Dict[str, List[Any]], n: Optional[int], full_grid: bool = False) -> int:
    total = grid_size(space)
    return total if (full_grid or n is None) else min(int(n), total)


SPACE_MODES = ("grid", "schema")


def space_for(candidate: Dict[str, Any], mode: str = "grid", base_frame: str = "1m") -> Dict[str, List[Any]]:
    """grid = lưới nhỏ `space` của chiến lược (vài giá trị/khoá); schema = toàn bộ params_schema (chu kỳ chỉ báo, khung thời gian, mọi tham số
    thoát lệnh theo min/max/bước) — không gian khổng lồ cho chạy quy mô lớn.
    base_frame (khung chạy): mọi khung tín hiệu/ATR phải >= khung chạy -> lựa chọn nhỏ hơn được nâng lên bằng khung chạy; ở grid, khung mặc
    định nhỏ hơn khung chạy được thêm vào lưới với đúng một giá trị là khung chạy."""
    if mode == "schema":
        from backend.optimize.book.build import schema_space
        space = dict(schema_space(candidate))
    elif mode == "grid":
        space = dict(candidate["space"])
    else:
        raise ValueError(f"space phải là một trong {SPACE_MODES}")
    if base_frame != "1m":
        from backend.optimize.book.build import frame_keys, lift_frame
        from backend.core.params import schema_defaults
        defaults = schema_defaults(candidate)
        schema = candidate.get("params_schema") or {}
        for k in frame_keys(candidate):
            choices = list(schema[k]["choices"])
            if k in space:
                lifted = [lift_frame(fr, base_frame, choices) for fr in space[k]]
                space[k] = list(dict.fromkeys(fr for fr in lifted if fr is not None))
            elif lift_frame(defaults[k], base_frame, choices) != defaults[k]:
                fr = lift_frame(defaults[k], base_frame, choices)
                space[k] = [fr] if fr is not None else []
    return space


def incompatible(candidates: List[Dict[str, Any]], mode: str, base_frame: str) -> Dict[str, List[str]]:
    """{id: [khoá khung không còn lựa chọn nào >= khung chạy]} — chiến lược không chạy được ở khung chạy này."""
    out = {}
    for c in candidates:
        empty = [k for k, v in space_for(c, mode, base_frame).items() if not v]
        if empty:
            out[c["id"]] = empty
    return out


REGIME_KEY = "regime"                     # khoá đặc biệt trong params của alpha: "learn" = học bảng regime trên dữ liệu train (regime/regime.learn_map)
REGIME_MODES = ("off", "learn", "both")


def regime_variants(params: Dict[str, Any], mode: str) -> List[Dict[str, Any]]:
    """off: [params]; learn: [params + regime=learn]; both: cả hai (mỗi biến thể là MỘT alpha -> một lần thử trong DSR/PBO)."""
    if mode == "off":
        return [params]
    learn = {**params, REGIME_KEY: "learn"}
    if mode == "learn":
        return [learn]
    if mode == "both":
        return [params, learn]
    raise ValueError(f"regime phải là một trong {REGIME_MODES}")


def split_regime(params: Dict[str, Any]):
    """-> (tham số chiến lược, chế độ regime | None)."""
    if REGIME_KEY not in params:
        return params, None
    p = dict(params)
    return p, p.pop(REGIME_KEY)


def validate_alpha(candidate: Dict[str, Any], params: Dict[str, Any], mode: str = "grid", base_frame: str = "1m") -> Optional[str]:
    """None nếu hợp lệ; ngược lại câu tiếng Việt. Kiểm: khoá thuộc không gian tham số, giá trị số hữu hạn (hoặc lựa chọn hợp lệ ở schema),
    mọi khung >= khung chạy, EMA nhanh < chậm, đòn bẩy <= S0_MAX_LEVERAGE, và dựng được tham số vị thế (build_params: ngân sách DCA...)."""
    from backend.optimize.funnel import stages as gates
    import math
    from backend.core.backtest import FRAME_MS
    from backend.optimize.book.build import frame_keys
    from backend.core.params import schema_defaults
    params, rmode = split_regime(params)
    if rmode not in (None, "learn"):
        return f"regime phải là learn (nhận {rmode!r})"
    space = space_for(candidate, mode, base_frame)
    bad = sorted(set(params) - set(space))
    if bad:
        return f"khoá tham số không thuộc không gian của {candidate['id']}: {bad}"
    fkeys = frame_keys(candidate)
    defaults = schema_defaults(candidate)
    small = [k for k in fkeys if FRAME_MS.get(params.get(k, defaults.get(k)), 0) < FRAME_MS[base_frame]]
    if small:
        return f"khung {small} nhỏ hơn khung chạy {base_frame}"
    if mode == "schema":
        from backend.optimize.book.build import validate_params
        from backend.core.params import schema_defaults
        _, errs = validate_params(candidate, params, schema_defaults(candidate))
        if errs:
            return errs[0][1]
    elif not all(k in fkeys or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)) for k, v in params.items()):
        return "mọi tham số phải là số hữu hạn"
    try:
        from backend.core.params import build_params
        from backend.core.backtest import _strategy_flow
        from backend.core.params import materialize
        st = materialize(candidate, params)
        if float(st["position"].get("leverage") or 1) > gates.S0_MAX_LEVERAGE:
            return f"đòn bẩy > {gates.S0_MAX_LEVERAGE}x"
        build_params(f"{st['side']}_{st['id']}", _strategy_flow(st), st["side"], st["position"], "cex")
    except ValueError as exc:
        return str(exc)
    return None
