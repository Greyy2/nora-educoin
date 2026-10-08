"""
test_ticks.py — crawl tick swap on-chain EVM (chỉ DEX) + lưu cửa sổ trượt (không gọi mạng).

- Giải mã log Swap Aerodrome/Uniswap v2 + v3 (hai chiều, price/amount/side), vai trò token trong pool, quy WETH -> USD, chia đôi đoạn getLogs.
- days > 14 bị cắt về 14; tick cũ hơn cửa sổ bị cắt khi lưu; save/load dex; manifest["ticks"]; ticks_to_bars; job (từ chối CEX) + router.
"""
import json
import os
import time

import numpy as np
import pandas as pd
import pytest

from backend.crawl import cex as oc
from backend.crawl import dex as tc
from backend.crawl.store import asset_meta, manifest_of_dir, ticks_to_bars
from data_helpers import write_asset
from backend.crawl import dex as ts

DAY = 86_400_000
USDC, AERO_T = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
WETH = "0x4200000000000000000000000000000000000006"
POOL = "0x6cdcb1c4a4d1c3c6d054b27ac5b77e89eafb971d"


def _asset(root, venue, sym, **manifest):
    return write_asset(root, venue, sym, **manifest)


def _ticks(n, end_ms=None, step_ms=1000, price=100.0, prefix="t"):
    end_ms = end_ms or int(time.time() * 1000)
    return pd.DataFrame({"timestamp_ms": end_ms - (n - 1 - np.arange(n)) * step_ms, "price": price, "volume_usd": price, "amount": 1.0,
                         "side": "buy", "block_number": np.arange(n), "tx_hash": [f"{prefix}{i}" for i in range(n)]})


# ─── RPC giả + metadata pool ─────────────────────────────────────────────────
def _w(*vals):
    return "0x" + "".join(format(v % (1 << 256), "064x") for v in vals)


def _swap(topic0, data, block=100, idx=1, tx="0xaa", block_ts=None):
    lg = {"topics": [topic0, "0x" + "0" * 64, "0x" + "0" * 64], "data": data, "blockNumber": hex(block), "logIndex": hex(idx), "transactionHash": tx}
    if block_ts:
        lg["blockTimestamp"] = hex(block_ts)
    return lg


def _sync(r0, r1, block=100, idx=0, tx="0xaa", topic=None):
    return {"topics": [topic or tc.SYNC_TOPICS[0]], "data": _w(r0, r1), "blockNumber": hex(block), "logIndex": hex(idx), "transactionHash": tx}


def _abi_string(s):
    raw = s.encode()
    return "0x" + format(32, "064x") + format(len(raw), "064x") + raw.hex().ljust(64, "0")


class _FakeRpc:
    """RPC giả cho pool (token0, token1): metadata on-chain, block (timestamp theo ts_of), eth_getLogs có giới hạn đoạn."""
    FACTORY = "0x420dd381b31aef6683db6b902084cb0ffece40da"

    def __init__(self, logs=(), head=1_000_000, head_ts=1_790_000_000, tokens=((USDC, "USDC", 6), (AERO_T, "AERO", 18)), stable=False, factory=FACTORY,
                 fee_raw=30, span_limit=None, ts_of=None, chain_id=8453):
        self.logs, self.head, self.head_ts, self.tokens, self.stable, self.factory, self.fee_raw = list(logs), head, head_ts, tokens, stable, factory, fee_raw
        self.span_limit, self.chain_id, self.calls, self.log_calls, self.block_lookups = span_limit, chain_id, [], [], []
        self.ts_of = ts_of or (lambda b: head_ts - (head - b) * 2)

    def batch(self, calls, size=50):
        return [self.call(m, p) for m, p in calls]

    def call(self, method, params):
        self.calls.append(method)
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getBlockByNumber":
            n = self.head if params[0] == "latest" else int(params[0], 16)
            self.block_lookups.append(n)
            return {"number": hex(n), "timestamp": hex(self.ts_of(n))}
        if method == "eth_getLogs":
            f = params[0]
            lo, hi = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            self.log_calls.append((lo, hi, f["topics"]))
            if self.span_limit and hi - lo + 1 > self.span_limit:
                raise tc.RpcRange("eth_getLogs is limited to a 500 range")
            return [lg for lg in self.logs if lo <= int(lg["blockNumber"], 16) <= hi and lg["topics"][0] in f["topics"][0]]
        to, sel = params[0]["to"], params[0]["data"]
        if sel in ("0x0dfe1681", "0xd21220a7"):
            return "0x" + "0" * 24 + self.tokens[sel == "0xd21220a7"][0][2:]
        if sel == "0x22be3de1":
            if self.stable is None:
                raise RuntimeError("RPC eth_call lỗi 3: execution reverted")
            return _w(int(self.stable))
        if sel == "0xc45a0155":
            if self.factory is None:
                raise RuntimeError("RPC eth_call lỗi 3: execution reverted")
            return "0x" + "0" * 24 + self.factory[2:]
        if sel.startswith("0xcc56b2c5"):
            if self.fee_raw is None:
                raise RuntimeError("RPC eth_call lỗi 3: execution reverted")
            self.fee_call = sel
            return _w(self.fee_raw)
        tok = next(t for t in self.tokens if t[0] == to)
        return _abi_string(tok[1]) if sel == "0x95d89b41" else hex(tok[2])


CFG = {"uniswap_v2_factories": ["0x8909dc15e40173ff4699343b6eb8132c65e18ec6"]}


def test_network_config_defaults():
    base = tc.network_config("base")
    assert base["chain_id"] == 8453 and base["rpc_url"].startswith("https://") and base["max_rps"] <= 8 and base["eth_usd"]["source"] == "okx_candles"
    base["rpc_url"] = "https://x.example"                                                                    # bản sao: không đổi NETWORKS
    assert tc.network_config("base")["rpc_url"] == tc.NETWORKS["base"]["rpc_url"] != base["rpc_url"]
    with pytest.raises(ValueError):
        tc.network_config("khong_co")


def test_read_pool_onchain_roles_stable_volatile_fee():
    info = tc.read_pool_onchain(_FakeRpc(), POOL, "AERO / USDC", CFG)
    assert info["base_index"] == 1 and info["decimals"] == [6, 18] and info["symbols"] == ["USDC", "AERO"] and info["quote_kind"] == "usd"
    assert info["pool_type"] == "aerodrome_v2" and info["stable"] is False and info["fee_rate"] == 0.003 and info["fee_note"] is None
    assert info["factory"] == _FakeRpc.FACTORY and info["tokens"] == [USDC, AERO_T]

    fake = _FakeRpc(stable=True, fee_raw=5)
    st = tc.read_pool_onchain(fake, POOL, "AERO / USDC", CFG)
    assert st["stable"] is True and st["fee_rate"] == 0.0005 and fake.fee_call.endswith(format(1, "064x"))    # getFee(pool, stable=true)

    nofee = tc.read_pool_onchain(_FakeRpc(fee_raw=None), POOL, "AERO / USDC", CFG)
    assert nofee["pool_type"] == "aerodrome_v2" and nofee["fee_rate"] is None and "getFee" in nofee["fee_note"]

    uni = tc.read_pool_onchain(_FakeRpc(stable=None, factory="0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"), POOL, "AERO / USDC", CFG)
    assert uni["pool_type"] == "uniswap_v2" and uni["fee_rate"] == 0.003 and uni["stable"] is False
    unk = tc.read_pool_onchain(_FakeRpc(stable=None, factory="0x" + "12" * 20), POOL, "AERO / USDC", CFG)
    assert unk["pool_type"] is None and unk["fee_rate"] is None and "không nhận diện" in unk["fee_note"]

    weth = tc.read_pool_onchain(_FakeRpc(tokens=((AERO_T, "VVV", 18), (WETH, "WETH", 18))), POOL, "VVV / WETH", CFG)
    assert weth["base_index"] == 0 and weth["quote_kind"] == "eth"
    assert tc.read_pool_onchain(_FakeRpc(tokens=((AERO_T, "VVV", 18), (WETH, "WETH", 18))), POOL, "ZZZ / WETH", CFG)["base_index"] == 0
    with pytest.raises(ValueError):
        tc.read_pool_onchain(_FakeRpc(tokens=((USDC, "USDC", 6), (WETH, "WETH", 18))), POOL, "FOO / BAR", CFG)


def test_pool_onchain_cached_in_ticks_attrs(tmp_path):
    d = _asset(str(tmp_path), "dex", "AERO")
    fake = _FakeRpc()
    first = tc.pool_onchain(fake, d, POOL, "AERO / USDC", CFG)
    assert first["pool_address"] == POOL and first["base_index"] == 1 and first["checked_at"] > 0
    n = len(fake.calls)
    assert n > 0 and not os.path.exists(os.path.join(d, "dex_pool.json"))                                          # không còn dex_pool.json
    tc.save_ticks(_ticks(3), "AERO", retention_days=3, source="evm_swaps", data_root=str(tmp_path), onchain=first)   # cache = attrs ticks.parquet
    assert asset_meta(d)["onchain"] == first
    assert tc.pool_onchain(fake, d, POOL, "AERO / USDC", CFG) == first and len(fake.calls) == n                 # lần 2 đọc cache, không gọi RPC
    tc.pool_onchain(fake, d, "0x" + "ab" * 20, "AERO / USDC", CFG)
    assert len(fake.calls) > n                                                                                    # đổi pool -> đọc lại


# ─── Swap + Sync ─────────────────────────────────────────────────────────────
def test_decode_sync_swap_pairing_and_both_directions():
    info = tc.read_pool_onchain(_FakeRpc(), POOL, "AERO / USDC", CFG)      # base = token1 (AERO, 18), quote = token0 (USDC, 6)
    t = tc.SWAP_V2_TOPICS[0]
    logs = [
        _sync(1_000 * 10**6, 2_000 * 10**18, block=100, idx=5, tx="0xaa"),                                   # Sync -> Swap cùng tx: mua
        _swap(t, _w(100 * 10**6, 0, 0, 200 * 10**18), block=100, idx=6, tx="0xaa"),                          # vào 100 USDC, ra 200 AERO
        _swap(t, _w(0, 50 * 10**18, 24_850_000, 0), block=100, idx=2, tx="0xbb"),                            # không có Sync -> reserve NaN; bán 50 AERO
        _sync(1_100 * 10**6, 1_800 * 10**18, block=101, idx=1, tx="0xcc"),                                   # tx có hai swap, mỗi swap một Sync riêng
        _swap(t, _w(10 * 10**6, 0, 0, 20 * 10**18), block=101, idx=2, tx="0xcc"),
        _sync(1_110 * 10**6, 1_780 * 10**18, block=101, idx=3, tx="0xcc"),
        _swap(t, _w(0, 10 * 10**18, 4_900_000, 0), block=101, idx=4, tx="0xcc"),
        _sync(1, 1, block=102, idx=1, tx="0xdd"),                                                            # Sync lạc của tx khác (mint/skim): không ghép nhầm
        _swap(t, _w(0, 0, 0, 0), block=102, idx=2, tx="0xee"),                                               # swap rỗng: bỏ
        _sync(7, 7, block=103, idx=1, tx="0xff", topic=tc.SYNC_TOPICS[1]),                                   # Sync kiểu Uniswap v2
        _swap(tc.SWAP_V2_TOPICS[1], _w(0, 5 * 10**18, 2_500_000, 0), block=103, idx=2, tx="0xff"),
    ]
    df = tc.decode_swaps(logs, info)
    assert df["tx_hash"].tolist() == ["0xbb:2", "0xaa:6", "0xcc:2", "0xcc:4", "0xff:2"]                      # theo (block, logIndex); id = tx:logIndex
    assert df["log_index"].tolist() == [2, 6, 2, 4, 2] and df["block_number"].tolist() == [100, 100, 101, 101, 103]
    assert df["side"].tolist() == ["sell", "buy", "buy", "sell", "sell"]
    assert df["price"].tolist() == pytest.approx([0.497, 0.5, 0.5, 0.49, 0.5]) and df["amount"].tolist() == pytest.approx([50, 200, 20, 10, 5])
    assert df["quote_amount"].tolist() == pytest.approx([24.85, 100, 10, 4.9, 2.5])
    assert np.isnan(df["reserve_base"].iloc[0]) and np.isnan(df["reserve_quote"].iloc[0])                    # không Sync
    assert df["reserve_base"].iloc[1:4].tolist() == pytest.approx([2000, 1800, 1780]) and df["reserve_quote"].iloc[1:4].tolist() == pytest.approx([1000, 1100, 1110])
    assert df["reserve_base"].iloc[4] == pytest.approx(7e-18) and df["block_ts"].isna().all()                # reserve = SAU swap, đã chia decimals theo vai base/quote


def test_decode_uniswap_v2_and_v3_token0_base_and_block_timestamp():
    info = {"base_index": 0, "decimals": [18, 6]}
    v2 = _swap(tc.SWAP_V2_TOPICS[1], _w(0, 30 * 10**6, 20 * 10**18, 0), block_ts=1_700_000_123)              # vào 30 USDC, ra 20 token0 -> mua @1.5
    v3 = _swap(tc.SWAP_V3_TOPIC, _w(5 * 10**18, -(9 * 10**6), 0, 0, 0), idx=3, block_ts=1_700_000_124)       # amount0 > 0 vào pool, amount1 < 0 ra -> bán @1.8
    df = tc.decode_swaps([v2, v3], info)
    assert df["side"].tolist() == ["buy", "sell"] and df["price"].tolist() == pytest.approx([1.5, 1.8]) and df["block_ts"].tolist() == [1_700_000_123, 1_700_000_124]
    assert df["reserve_base"].isna().all()                                                                    # v3 không có Sync


def test_reserve_price_volatile_and_stable_matches_curve_slope():
    assert tc.reserve_price(1000.0, 500.0, False) == pytest.approx(0.5)
    x, y = 120.0, 80.0                                                                                          # x^3y + xy^3 = k -> giá = -dy/dx
    k = lambda a, b: a ** 3 * b + a * b ** 3
    h, y2 = 1e-5, y
    for _ in range(50):                                                                                          # Newton: tìm y2 để k(x+h, y2) = k(x, y)
        y2 -= (k(x + h, y2) - k(x, y)) / ((x + h) ** 3 + 3 * (x + h) * y2 ** 2)
    assert tc.reserve_price(x, y, True) == pytest.approx((y - y2) / h, rel=1e-4)
    assert tc.reserve_price(x, y, True) == pytest.approx((3 * x * x * y + y ** 3) / (x ** 3 + 3 * x * y * y))
    assert tc.reserve_price(100.0, 100.0, True) == pytest.approx(1.0) and tc.reserve_price(x, y, True) != pytest.approx(y / x)
    df = pd.DataFrame({"price": [0.5 * 1.003, 0.4], "reserve_base": [1000.0, np.nan], "reserve_quote": [500.0, np.nan]})
    dev = tc.reserve_deviation_bps(df, False)
    assert dev.index.tolist() == [0] and dev.iloc[0] == pytest.approx(30.0)


# ─── Timestamp / chia đoạn / cửa sổ ──────────────────────────────────────────
def _df_blocks(blocks, ts=None):
    return pd.DataFrame({"block_ts": ts if ts is not None else np.nan, "block_number": blocks})


def test_timestamp_method_choice():
    lo, hi = 1000, 2000
    blocks = [1000, 1337, 1500, 1999]
    got, how = tc.attach_timestamps(_df_blocks(blocks, [5.0, 6.0, 7.0, 8.0]), None, lo, hi)                    # có blockTimestamp -> không gọi RPC
    assert how == "log_block_timestamp" and got["timestamp_ms"].tolist() == [5000, 6000, 7000, 8000] and "block_ts" not in got

    lin = _FakeRpc(head=hi, head_ts=1_790_000_000)                                                              # block 2s đều -> nội suy
    got, how = tc.attach_timestamps(_df_blocks(blocks), lin, lo, hi)
    assert how == "linear_interpolation" and got["timestamp_ms"].tolist() == [(1_790_000_000 - (hi - b) * 2) * 1000 for b in blocks]
    assert len(lin.block_lookups) <= 2 + tc.TS_SAMPLES                                                          # chỉ lấy mẫu, không tra từng block

    skip = lambda b: 1_790_000_000 - (hi - b) * 2 + (1 if b > 1600 else 0)                                      # một khe block bị lỡ giữa cửa sổ -> không tuyến tính
    irr = _FakeRpc(head=hi, head_ts=1_790_000_000, ts_of=skip)
    got, how = tc.attach_timestamps(_df_blocks(blocks), irr, lo, hi)
    assert how == "per_block_lookup" and got["timestamp_ms"].tolist() == [skip(b) * 1000 for b in blocks]

    half = _df_blocks([1000, 1500], [5.0, np.nan])                                                              # log lẫn: phần thiếu mới tra
    got, how = tc.attach_timestamps(half, _FakeRpc(head=hi), lo, hi)
    assert got["timestamp_ms"].iloc[0] == 5000 and how == "linear_interpolation"


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise tc.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class _Session:
    """Session giả: trả lần lượt các phản hồi đã định (hàm nhận payload -> _Resp)."""

    def __init__(self, *responders):
        self.responders, self.payloads = list(responders), []

    def post(self, url, json=None, timeout=None):
        self.payloads.append(json)
        r = self.responders.pop(0)
        return r(json) if callable(r) else r


def test_rpc_retries_rate_limit_413_and_batch_cap(monkeypatch):
    monkeypatch.setattr(tc.time, "sleep", lambda s: None)
    ok = lambda p: _Resp(200, {"jsonrpc": "2.0", "id": 1, "result": "0x1"})
    rpc = tc.Rpc("u", 8, _Session(_Resp(429), _Resp(200, {"error": {"code": -32016, "message": "over rate limit"}}), ok))
    assert rpc.call("eth_blockNumber", []) == "0x1" and len(rpc.session.payloads) == 3                     # 429 + rate limit -> thử lại
    big = tc.Rpc("u", 8, _Session(_Resp(413)))
    with pytest.raises(tc.RpcRange):
        big.call("eth_getLogs", [{}])                                                                       # 413 không thử lại: báo để co đoạn
    err = tc.Rpc("u", 8, _Session(_Resp(200, {"error": {"code": -32614, "message": "eth_getLogs is limited to a 500 range"}})))
    with pytest.raises(tc.RpcRange):
        err.call("eth_getLogs", [{}])
    with pytest.raises(RuntimeError, match="lỗi 3"):
        tc.Rpc("u", 8, _Session(_Resp(200, {"error": {"code": 3, "message": "execution reverted"}}))).call("eth_call", [])

    def echo(p):
        return _Resp(200, [{"jsonrpc": "2.0", "id": c["id"], "result": hex(c["params"][0])} for c in reversed(p)])        # trả ngược thứ tự: ghép theo id
    cap = lambda p: _Resp(200, {"jsonrpc": "2.0", "error": {"code": -32014, "message": "maximum 3 calls in 1 batch"}, "id": None})
    b = tc.Rpc("u", 8, _Session(cap, echo, echo, echo, echo))
    assert b.batch([("m", [i]) for i in range(10)], 50) == [hex(i) for i in range(10)]
    assert b.batch_cap == 3 and [len(p) for p in b.session.payloads] == [10, 3, 3, 3, 1]                   # nhớ giới hạn 3 sau khi bị từ chối
    with pytest.raises(RuntimeError, match="lỗi"):
        tc.Rpc("u", 8, _Session(_Resp(200, [{"id": 0, "error": {"code": 1, "message": "x"}}]))).batch([("m", [0])])


def test_block_at_or_after_binary_search_on_real_timestamps():
    fake = _FakeRpc(head=1_000_000, head_ts=1_790_000_000)
    target = 1_790_000_000 - 3 * 86400
    b = tc.block_at_or_after(fake, target, 1_000_000)
    assert fake.ts_of(b) >= target > fake.ts_of(b - 1) and b == 1_000_000 - 3 * 43200 and len(fake.block_lookups) < 30
    irregular = _FakeRpc(head=1000, head_ts=10_000, ts_of=lambda n: 3 * n + (n // 7) % 3)                       # thời gian block bất kỳ: vẫn đúng
    b = tc.block_at_or_after(irregular, 1500, 1000)
    assert irregular.ts_of(b) >= 1500 > irregular.ts_of(b - 1)


def test_fetch_logs_adaptive_span_shrinks_and_remembers():
    logs = [{"blockNumber": hex(b), "topics": [tc.SWAP_V2_TOPICS[0]]} for b in range(0, 5000, 7)]
    fake = _FakeRpc(logs, span_limit=500)
    out, span = tc.fetch_logs(fake, POOL, 0, 4999, 2000, [tc.SWAP_V2_TOPICS[0]])
    assert span == 500 and [int(x["blockNumber"], 16) for x in out] == [b for b in range(0, 5000, 7)]          # đủ log, không trùng
    spans = [hi - lo + 1 for lo, hi, _ in fake.log_calls]
    assert spans[:3] == [2000, 1000, 500] and max(spans[3:]) == 500 and len(spans) == 3 + 10 - 1                  # sau khi co chỉ dùng 500 (lần 500 đầu đã thành công)
    always = _FakeRpc(logs, span_limit=0.5)                                                                      # nút từ chối cả đoạn 1 block -> báo lỗi, không lặp vô hạn
    with pytest.raises(tc.RpcRange):
        tc.fetch_logs(always, POOL, 0, 10, 4, [tc.SWAP_V2_TOPICS[0]])


def test_crawl_dex_ticks_end_to_end(tmp_path, monkeypatch):
    root = str(tmp_path)
    _asset(root, "dex", "AERO", pool_address=POOL.upper(), network="base", pool_name="AERO / USDC")
    head, head_ts = 1_000_000, int(time.time())
    t = tc.SWAP_V2_TOPICS[0]
    logs = []
    for i in range(5):
        blk = head - 100 - i
        logs += [_sync(1000 * 10**6, 2000 * 10**18, block=blk, idx=2 * i, tx=f"0x{i:02x}"), _swap(t, _w(10 * 10**6, 0, 0, 20 * 10**18), block=blk, idx=2 * i + 1, tx=f"0x{i:02x}")]
    logs.append(_swap(t, _w(10 * 10**6, 0, 0, 20 * 10**18), block=head - 3 * 43200 - 5, tx="0xold"))             # trước cửa sổ 3 ngày
    fake = _FakeRpc(logs, head=head, head_ts=head_ts, span_limit=500)
    monkeypatch.setattr(tc, "Rpc", lambda *a, **k: fake)
    res = tc.crawl_dex_ticks("dex:AERO", days=3, data_root=root)
    assert res["rows"] == 5 and res["window_days"] == 3 and res["ts_method"] == "linear_interpolation" and res["sync_matched_pct"] == 100.0
    lo, hi = fake.log_calls[0][0], fake.log_calls[-1][1]
    assert lo == head - 3 * 43200 and hi == head and max(b - a + 1 for a, b, _ in fake.log_calls) <= 2000
    assert set(fake.log_calls[0][2][0]) == set(tc.SWAP_V2_TOPICS) | {tc.SWAP_V3_TOPIC} | set(tc.SYNC_TOPICS)
    df = ts.load_ticks_df("dex:AERO", data_root=root)
    assert (df["price"] == 0.5).all() and (df["volume_usd"] == 10.0).all() and (df["quote_usd"] == 1.0).all() and (df["side"] == "buy").all()
    assert df["timestamp_ms"].max() == (head_ts - 100 * 2) * 1000 and (df["reserve_base"] == 2000).all() and (df["reserve_quote"] == 1000).all()
    assert (df["mid_price"] == 0.5).all()                                      # dự trữ 1000/2000 sau swap
    assert df["tx_hash"].tolist() == [f"0x{i:02x}:{2 * i + 1}" for i in (4, 3, 2, 1, 0)] and df["block_number"].is_monotonic_increasing
    man = asset_meta(os.path.join(root, "dex", "AERO"))["ticks"]
    assert man["source"] == "evm_swaps" and man["network"] == "base" and man["quote"] == "USDC" and man["rows"] == 5 and man["pool_type"] == "aerodrome_v2"
    assert man["price_basis"]["price"].startswith("fill") and man["price_basis"]["mid_price"].startswith("post-swap")
    assert man["ts_method"] == "linear_interpolation" and man["reserves_basis"] == "post_swap" and man["fee_rate"] == 0.003 and man["stable"] is False
    assert man["quote_usd_source"] == "stable_quote=1" and man["sync_matched_pct"] == 100.0 and man["log_span"] == 500 and man["chain_id"] == 8453
    assert man["reserve_dev_bps_median"] == pytest.approx(0.0, abs=1e-6)                                      # giá swap 0.5 = dự trữ 1000/2000
    assert asset_meta(os.path.join(root, "dex", "AERO"))["onchain"]["pool_type"] == "aerodrome_v2"
    assert not os.path.exists(os.path.join(root, "dex", "AERO", "dex_pool.json")) and not os.path.exists(os.path.join(root, "dex", "AERO", "manifest.json"))

    fake2 = _FakeRpc(logs, head=head, head_ts=head_ts)
    monkeypatch.setattr(tc, "Rpc", lambda *a, **k: fake2)
    res = tc.crawl_dex_ticks("AERO", days=99, data_root=root)                  # days > 14 -> cắt về 14
    assert res["window_days"] == 14 and fake2.log_calls[0][0] == head - 14 * 43200 and len(res["issues"]) == 1 and "vượt tối đa" in res["issues"][0]
    assert res["rows"] == 6                                                    # lệnh cũ nay nằm trong cửa sổ 14 ngày; 5 cũ gộp không trùng

    monkeypatch.setattr(tc, "Rpc", lambda *a, **k: _FakeRpc(logs, head=head, head_ts=head_ts, chain_id=1))
    with pytest.raises(RuntimeError, match="chain"):
        tc.crawl_dex_ticks("AERO", days=1, data_root=root)


def test_crawl_dex_weth_quote_converts_with_eth_candles(tmp_path, monkeypatch):
    root = str(tmp_path)
    _asset(root, "dex", "VVV", pool_address=POOL, network="base", pool_name="VVV / WETH")
    head, head_ts = 1_000_000, int(time.time()) // 60 * 60
    swap = _swap(tc.SWAP_V2_TOPICS[0], _w(0, 2 * 10**18, 100 * 10**18, 0), block=head - 10)                  # vào 2 WETH, ra 100 VVV (base = token0) -> 0.02 WETH
    fake = _FakeRpc([swap, _sync(10 * 10**18, 5 * 10**18, block=head - 10, idx=0)], head=head, head_ts=head_ts, tokens=((AERO_T, "VVV", 18), (WETH, "WETH", 18)))
    monkeypatch.setattr(tc, "Rpc", lambda *a, **k: fake)
    seen = {}

    def eth_candles(session, base, lo, hi):
        seen.update(base=base, lo=lo, hi=hi)
        return pd.DataFrame({"open_time": np.arange(lo, hi + 60_000, 60_000), "open": 3000.0})
    monkeypatch.setattr(oc, "fetch_rest_candles", eth_candles)
    res = tc.crawl_dex_ticks("VVV", days=1, data_root=root)
    df = ts.load_ticks_df("VVV", data_root=root)
    assert seen["base"] == "ETH" and res["rows"] == 1 and df["quote_usd"].iloc[0] == 3000.0
    assert df["price"].iloc[0] == pytest.approx(0.02 * 3000) and df["volume_usd"].iloc[0] == pytest.approx(2 * 3000)
    assert df["reserve_base"].iloc[0] == 10 and df["reserve_quote"].iloc[0] == 5                                 # dự trữ giữ theo đơn vị token, không đổi USD
    man = asset_meta(os.path.join(root, "dex", "VVV"))["ticks"]
    assert man["quote"] == "WETH" and man["quote_usd_source"] == "okx_eth_usdt_swap_1m_open"


def test_quote_to_usd_weth_uses_eth_open_of_the_minute():
    info = {"quote_kind": "eth", "stable": False}
    base = 1_700_000_040_000                                              # thẳng phút
    df = pd.DataFrame({"timestamp_ms": [base + 5_000, base + 65_000, base + 70_000], "price": [0.001, 0.002, 0.002], "amount": [1.0, 1.0, 2.0],
                       "quote_amount": [0.001, 0.002, 0.004], "side": "buy", "block_number": 1, "tx_hash": ["a", "b", "c"],
                       "reserve_base": [1000.0, 1000.0, np.nan], "reserve_quote": [2.0, 1.0, np.nan]})
    eth = pd.DataFrame({"open_time": [base, base + 60_000], "open": [2000.0, 3000.0]})
    out = tc.quote_to_usd(df, info, eth)
    assert out["price"].tolist() == pytest.approx([2.0, 6.0, 6.0]) and out["volume_usd"].tolist() == pytest.approx([2.0, 6.0, 12.0])
    assert out["quote_usd"].tolist() == [2000.0, 3000.0, 3000.0] and "quote_amount" not in out
    assert out["mid_price"].iloc[:2].tolist() == pytest.approx([0.002 * 2000, 0.001 * 3000]) and np.isnan(out["mid_price"].iloc[2])      # mid theo dự trữ x quote_usd; không Sync -> NaN
    with pytest.raises(RuntimeError):
        tc.quote_to_usd(df, info, eth.iloc[1:])                           # swap đầu trước nến ETH đầu tiên
    with pytest.raises(RuntimeError):
        tc.quote_to_usd(df, info, None)
    assert tc.quote_to_usd(df, {"quote_kind": "usd", "stable": False}, None)["volume_usd"].tolist() == [0.001, 0.002, 0.004]


def test_mid_price_volatile_and_stable_after_swap():
    base = pd.DataFrame({"price": [1.0, 1.0], "quote_amount": [1.0, 1.0], "reserve_base": [120.0, 100.0], "reserve_quote": [80.0, 100.0]})
    vol = tc.quote_to_usd(base, {"quote_kind": "usd", "stable": False}, None)
    assert vol["mid_price"].tolist() == pytest.approx([80 / 120, 1.0]) and vol["price"].tolist() == [1.0, 1.0]       # price = giá khớp, giữ nguyên
    stb = tc.quote_to_usd(base, {"quote_kind": "usd", "stable": True}, None)
    x, y = 120.0, 80.0
    assert stb["mid_price"].iloc[0] == pytest.approx((3 * x * x * y + y ** 3) / (x ** 3 + 3 * x * y * y)) and stb["mid_price"].iloc[0] != pytest.approx(80 / 120)
    assert stb["mid_price"].iloc[1] == pytest.approx(1.0)
    zero = tc.quote_to_usd(base.assign(reserve_base=[0.0, np.nan]), {"quote_kind": "usd", "stable": False}, None)
    assert zero["mid_price"].isna().all()                                                                          # dự trữ 0/NaN -> NaN, không chia 0


# ─── Lưu / đọc / cửa sổ ──────────────────────────────────────────────────────
def test_save_prunes_old_dedups_and_roundtrips(tmp_path):
    root = str(tmp_path)
    _asset(root, "dex", "AERO")
    _asset(root, "cex", "BTC")                                              # CEX không có tick
    now = int(time.time() * 1000)
    old = _ticks(5, end_ms=now - 10 * DAY, prefix="old")
    new = _ticks(20, end_ms=now, prefix="n")
    res = ts.save_ticks(pd.concat([old, new]), "AERO", retention_days=3, source="evm_swaps", data_root=root, extra_meta={"network": "base", "quote": "USDC"})
    assert res["rows"] == 20 and os.path.isfile(os.path.join(root, "dex", "AERO", "ticks.parquet"))
    again = _ticks(25, end_ms=now + 5000, prefix="n")                       # 20 trùng + 5 mới; bản mới thắng
    again["price"] = 101.0
    ts.save_ticks(again, "AERO", retention_days=3, source="evm_swaps", data_root=root)
    for sym in ("AERO", "dex:AERO", "dex/aero"):
        df = ts.load_ticks_df(sym, data_root=root)
        assert len(df) == 25 and df["tx_hash"].is_unique and df["timestamp_ms"].is_monotonic_increasing and (df["price"] == 101.0).all()
        assert ts.resolve_tick_file(sym, root)
    m = manifest_of_dir(os.path.join(root, "dex", "AERO"))
    assert m["ticks"]["source"] == "evm_swaps" and m["ticks"]["synthetic"] is False and m["ticks"]["rows"] == 25 and m["venue"] == "dex"
    assert m["ticks"]["window_days"] == 3 and m["ticks"]["start_ts"] == int(df["timestamp_ms"].min()) and m["ticks"]["end_ts"] == int(df["timestamp_ms"].max())
    assert m["ticks"]["crawled_at"] > 0 and "network" not in m["ticks"]                       # extra_meta của lần lưu gần nhất
    ts.save_ticks(_ticks(7, prefix="d"), "AERO", retention_days=14, source="evm_swaps", data_root=root, extra_meta={"network": "base"})
    assert len(ts.load_ticks_df("AERO", data_root=root)) == 32
    assert ts.resolve_tick_file("BTC", root) is None and ts.load_ticks_df("NOPE", data_root=root).empty
    assert asset_meta(os.path.join(root, "dex", "AERO"))["ticks"]["network"] == "base"
    from backend.crawl.store import has_ticks
    assert has_ticks("dex:AERO", data_root=root) and not has_ticks("BTC", data_root=root)
    cov = ts.tick_coverage(root)
    assert [c["symbol"] for c in cov] == ["AERO"] and cov[0]["venue"] == "dex" and cov[0]["rows"] == 32 and cov[0]["window_days"] == 14
    assert cov[0]["source"] == "evm_swaps" and {"start_ts", "end_ts"} <= set(cov[0])


def test_save_rejects_bad_input(tmp_path):
    root = str(tmp_path)
    _asset(root, "dex", "AERO")
    kw = dict(source="evm_swaps", data_root=root)
    with pytest.raises(ValueError):
        ts.save_ticks(_ticks(3), "AERO", retention_days=15, **kw)                       # quá 14 ngày
    with pytest.raises(ValueError):
        ts.save_ticks(_ticks(3).drop(columns=["tx_hash"]), "AERO", retention_days=3, **kw)
    with pytest.raises(ValueError):
        ts.save_ticks(_ticks(3, end_ms=1_600_000_000_000), "AERO", retention_days=3, **kw)   # toàn tick cũ -> rỗng sau khi cắt
    with pytest.raises(FileNotFoundError):
        ts.save_ticks(_ticks(3), "KHONGCO", retention_days=3, **kw)
    assert not os.path.exists(os.path.join(root, "dex", "AERO", "ticks.parquet"))


def test_ticks_to_bars_1m_ohlcv_n_trades_vwap_and_fill():
    m0 = 1_700_000_040_000
    t = pd.DataFrame({"timestamp_ms": [m0 + 50_000, m0 + 1000, m0 + 30_000, m0 + 3 * 60_000 + 7000], "price": [12.0, 10.0, 8.0, 11.0],
                      "volume_usd": [12.0, 20.0, 24.0, 11.0], "amount": [1.0, 2.0, 3.0, 1.0]})         # chưa sắp xếp: trong phút đầu theo thời gian là 10, 8, 12
    c = ticks_to_bars(t)
    assert list(c.columns) == ["open_time", "open", "high", "low", "close", "volume", "n_trades", "n_fallback", "vwap", "is_filled"]
    assert c["open_time"].tolist() == [m0, m0 + 60_000, m0 + 120_000, m0 + 180_000] and (c["open_time"] % 60_000 == 0).all()
    r0 = c.iloc[0]
    assert (r0.open, r0.high, r0.low, r0.close, r0.volume, r0.n_trades, r0.is_filled) == (10.0, 12.0, 8.0, 12.0, 56.0, 3, 0)
    assert r0.vwap == pytest.approx(56.0 / 6.0)
    for i in (1, 2):                                                 # phút trống: O=H=L=C=vwap=close trước, volume 0, KHÔNG có lệnh
        r = c.iloc[i]
        assert r[["open", "high", "low", "close", "vwap"]].tolist() == [12.0] * 5 and r.volume == 0 and r.n_trades == 0 and r.is_filled == 1
    assert c.iloc[3].is_filled == 0 and c.iloc[3].close == 11.0 and c.iloc[3].n_trades == 1 and c["n_trades"].dtype == np.int64
    assert ticks_to_bars(t.iloc[:0]).empty and list(ticks_to_bars(t.iloc[:0]).columns) == list(c.columns)


def test_ticks_to_bars_price_col_fallback_and_n_fallback():
    m0 = 1_700_006_400_000
    t = pd.DataFrame({"timestamp_ms": [m0 + 1000, m0 + 2000, m0 + 3000, m0 + 61_000], "price": [10.0, 12.0, 11.0, 20.0],
                      "mid_price": [10.5, np.nan, 11.5, np.nan], "volume_usd": [10.0, 12.0, 11.0, 20.0], "amount": [1.0, 1.0, 1.0, 1.0]})
    fill = ticks_to_bars(t)                                              # mặc định: giá khớp
    assert fill.iloc[0][["open", "high", "low", "close"]].tolist() == [10.0, 12.0, 10.0, 11.0] and fill["n_fallback"].tolist() == [0, 0]
    mid = ticks_to_bars(t, "1m", "mid_price")
    assert mid.iloc[0][["open", "high", "low", "close"]].tolist() == [10.5, 12.0, 10.5, 11.5]                # swap thứ 2 thiếu mid -> dùng price 12.0
    assert mid["n_fallback"].tolist() == [1, 1] and mid["n_trades"].tolist() == [3, 1] and mid.iloc[1].close == 20.0
    assert mid.iloc[0].vwap == pytest.approx(33.0 / 3) and mid.iloc[0].vwap == fill.iloc[0].vwap                 # vwap luôn theo giá khớp
    assert ticks_to_bars(t.drop(columns="mid_price"), "1m", "mid_price")["n_fallback"].tolist() == [3, 1]       # không có cột -> toàn bộ fallback
    gap = ticks_to_bars(t.iloc[[0, 3]].assign(timestamp_ms=[m0 + 1000, m0 + 181_000]), "1m", "mid_price")
    assert gap["n_fallback"].tolist() == [0, 0, 0, 1] and gap["n_trades"].tolist() == [1, 0, 0, 1]             # nến điền: không bịa lệnh, không tính fallback


def test_ticks_to_bars_any_frame():
    h0 = 1_700_006_400_000 + 3_600_000                                  # 01:00 UTC, cùng ngày với các tick
    t = pd.DataFrame({"timestamp_ms": [h0 + 60_000, h0 + 4 * 60_000, h0 + 6 * 60_000, h0 + 3_600_000 * 2 + 5], "price": [1.0, 3.0, 2.0, 5.0],
                      "volume_usd": [1.0, 3.0, 2.0, 5.0], "amount": [1.0, 1.0, 1.0, 1.0]})
    five = ticks_to_bars(t, "5m")
    assert five["open_time"].tolist()[:2] == [h0, h0 + 300_000] and five.iloc[0].n_trades == 2 and five.iloc[0].high == 3.0 and five.iloc[1].open == 2.0
    hour = ticks_to_bars(t, "1h")
    assert hour["open_time"].tolist() == [h0, h0 + 3_600_000, h0 + 7_200_000] and hour["n_trades"].tolist() == [3, 0, 1]
    assert hour.iloc[0].vwap == pytest.approx(2.0) and hour.iloc[1].is_filled == 1 and hour.iloc[1].close == 2.0 and hour.iloc[1].volume == 0
    assert hour["volume"].sum() == t["volume_usd"].sum() and len(ticks_to_bars(t, "1d")) == 1
    with pytest.raises(ValueError):
        ticks_to_bars(t, "abc")


# ─── Job + router ────────────────────────────────────────────────────────────
def test_clamp_days():
    assert tc.clamp_days(3) == (3, None) and tc.clamp_days(None) == (3, None)
    assert tc.clamp_days(99)[0] == 14 and "14" in tc.clamp_days(99)[1] and tc.clamp_days(0)[0] == tc.DEFAULT_TICK_DAYS == 3


def test_dex_name_rejects_cex_symbols():
    assert tc.dex_name("AERO") == "AERO" and tc.dex_name("dex:aero") == "AERO"
    for bad in ("BTC@perp", "cex:BTC"):
        with pytest.raises(ValueError, match="chỉ có nến"):
            tc.dex_name(bad)


def test_run_job_dispatches_and_reports_failures(tmp_path, monkeypatch):
    root = str(tmp_path)
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", root)
    jobdir = tmp_path / "job"
    os.makedirs(jobdir, exist_ok=True)   # writer chỉ ghi khi thư mục job tồn tại (launch tạo sẵn)
    monkeypatch.setenv("NORA_JOB_DIR", str(jobdir))
    calls = []
    monkeypatch.setattr(tc, "crawl_dex_ticks", lambda s, d, r: calls.append((s, d, r)) or {"symbol": s, "rows": 2})
    assert len(tc.run_job({"symbols": "AERO,dex:VVV", "days": 5})) == 2 and calls == [("AERO", 5, root), ("VVV", 5, root)]
    with pytest.raises(RuntimeError, match="BTC@perp"):
        tc.run_job({"symbols": ["AERO", "BTC@perp"]})
    res = json.load(open(jobdir / "result.json"))["assets"]
    assert res[0]["rows"] == 2 and "chỉ có nến" in res[1]["error"]               # kết quả được ghi đủ trước khi báo lỗi
    for bad in ({"symbols": ""}, {"symbols": "AERO", "bogus": 1}):
        with pytest.raises(ValueError):
            tc.run_job(bad)


def test_job_kind_registered_and_router(tmp_path, monkeypatch):
    import importlib
    from backend.optimize.process import process as batch
    from backend.routes import data as data_routes
    spec = batch.KINDS["data_crawl_ticks"]
    assert spec["module"] == "backend.crawl.dex" and spec["params"] == {"symbols", "days"}
    assert callable(importlib.import_module(spec["module"]).run_job)
    batch._check_params("data_crawl_ticks", {"symbols": ["AERO"], "days": 3})
    with pytest.raises(batch.JobError):
        batch._check_params("data_crawl_ticks", {"symbols": ["AERO"], "output_dir": "/x"})
    assert "Tải tick" in batch.job_label("data_crawl_ticks", {"symbols": ["AERO"], "days": 3})

    paths = {(m, r.path) for r in data_routes.data_router.routes for m in r.methods}
    assert ("POST", "/api/data/ticks/crawl") in paths and ("GET", "/api/data/ticks/coverage") in paths
    assert data_routes.TicksRequest(symbols=["dex:AERO", "VVV"]).days == 3
    for bad in ({"symbols": ["AERO"], "days": 15}, {"symbols": ["AERO"], "days": 0}, {"symbols": ["../x"]}, {"symbols": []},
                {"symbols": ["BTC@perp"]}, {"symbols": ["cex:BTC"]}, {"symbols": ["A B"]}):
        with pytest.raises(Exception):
            data_routes.TicksRequest(**bad)

    launched = []
    monkeypatch.setattr(batch, "launch", lambda kind, params: launched.append((kind, params)) or "20260101_000000_abcdef")
    assert data_routes.post_ticks_crawl(data_routes.TicksRequest(symbols=["AERO"], days=7)) == {"job_id": "20260101_000000_abcdef"}
    assert launched == [("data_crawl_ticks", {"symbols": ["AERO"], "days": 7})]

    root = str(tmp_path)
    monkeypatch.setenv("NORA_LOCAL_DATA_ROOT", root)
    _asset(root, "dex", "AERO")
    ts.save_ticks(_ticks(4), "AERO", retention_days=3, source="evm_swaps", data_root=root)
    cov = data_routes.get_ticks_coverage()["assets"]
    assert len(cov) == 1 and cov[0]["symbol"] == "AERO" and cov[0]["rows"] == 4 and cov[0]["window_days"] == 3
