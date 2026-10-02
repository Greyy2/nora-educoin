"""S0: sinh alpha từ không gian tham số của chiến lược (strategy_book.CANDIDATES) + kiểm tính hợp lệ.

alpha_id = sha1(chiến lược + "|" + JSON chuẩn hoá của tham số)[:ALPHA_ID_LEN] — cùng (chiến lược, tham số) luôn cùng id, ở mọi lượt chạy.
Lấy mẫu CÙNG thuật toán build_strategy_book.iter_configs (lấy mẫu theo CHỈ SỐ của lưới, không dựng lưới): n < kích thước lưới -> random.Random(seed).sample.
"""
import hashlib
import json
import random
import sys
from typing import Any, Dict, Iterator, List, Optional

from . import gates


def canonical_params(params: Dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def alpha_id_of(strategy: str, params: Dict[str, Any]) -> str:
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


def space_for(candidate: Dict[str, Any], mode: str = "grid") -> Dict[str, List[Any]]:
    """grid = lưới nhỏ `space` của chiến lược (vài giá trị/khoá); schema = toàn bộ params_schema (chu kỳ chỉ báo, khung thời gian, mọi tham số
    thoát lệnh theo min/max/bước) — không gian khổng lồ cho chạy quy mô lớn."""
    if mode == "schema":
        from backend.core.params.modes import schema_space
        return schema_space(candidate)
    if mode != "grid":
        raise ValueError(f"space phải là một trong {SPACE_MODES}")
    return candidate["space"]


def validate_alpha(candidate: Dict[str, Any], params: Dict[str, Any], mode: str = "grid") -> Optional[str]:
    """None nếu hợp lệ; ngược lại câu tiếng Việt. Kiểm: khoá thuộc không gian tham số, giá trị số hữu hạn (hoặc lựa chọn hợp lệ ở schema),
    EMA nhanh < chậm, đòn bẩy <= S0_MAX_LEVERAGE, và dựng được tham số vị thế (build_params: ngân sách DCA, đòn bẩy spot...)."""
    import math
    space = space_for(candidate, mode)
    bad = sorted(set(params) - set(space))
    if bad:
        return f"khoá tham số không thuộc không gian của {candidate['id']}: {bad}"
    if mode == "schema":
        from backend.core.params.modes import validate_params
        from backend.core.strategy.book import schema_defaults
        _, errs = validate_params(candidate, params, schema_defaults(candidate))
        if errs:
            return errs[0][1]
    elif not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in params.values()):
        return "mọi tham số phải là số hữu hạn"
    try:
        from backend.core.params.builder import build_params
        from backend.core.backtest.portfolio import _strategy_flow
        from backend.core.strategy import book as sb
        st = sb.materialize(candidate, params)
        if float(st["position"].get("leverage") or 1) > gates.S0_MAX_LEVERAGE:
            return f"đòn bẩy > {gates.S0_MAX_LEVERAGE}x"
        build_params(f"{st['side']}_{st['id']}", _strategy_flow(st), st["side"], st["position"], "cex", symbol=None)
    except ValueError as exc:
        return str(exc)
    return None
