"""P15-B: so sánh engine CŨ (test/backend-no, kernel numba, venv ~/.venvs/nora Python 3.11) với engine MỚI (backend/nautilus, venv nora312) trên cùng dữ liệu.

10 mẫu education đầu tiên (backend.crawl.store.load_samples) × BTC, ETH × 2024-01-01..2024-07-01, base_frame 1m, vốn 10 000, close_at_end.
Hai chế độ: "product" (tham số vị thế mặc định của sản phẩm: slippage 0,02%, limit_through 0,05%...) và "neutral" (slippage_rate=0, limit_through_pct=0:
chỉ còn khác biệt do quy ước khớp lệnh của Nautilus / funding / thanh lý).

Chạy:  NORA_PYTHON=$HOME/.venvs/nora312/bin/python ops/run_limited.sh --no-lock --mem 8G -- test/scripts/p15_compare_old_engine.py [--n 10] [--json out.json]
Nội bộ: `--worker OUT.json MODE` chạy engine của PYTHONPATH hiện tại và ghi lệnh ra JSON (engine cũ chạy qua PYTHONPATH = thư mục tạm có symlink backend -> test/backend-no).
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import warnings

NORA = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OLD_PY = os.path.expanduser("~/.venvs/nora/bin/python")
SYMS = ["BTC", "ETH"]
START, END = "2024-01-01", "2024-07-01"
MODES = {"product": {}, "neutral": {"slippage_rate": 0.0, "limit_through_pct": 0.0}}


def ms(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def worker(out_path: str, mode: str, n: int) -> None:
    """Chạy n mẫu với engine có trong PYTHONPATH (cũ hoặc mới); ghi {key: {symbol: [lệnh]}, final_equity, wall}."""
    warnings.filterwarnings("ignore")
    sys.path.insert(0, os.environ["PYTHONPATH"].split(os.pathsep)[0])
    import backend.optimize  # noqa: F401  (đăng ký nguồn dữ liệu mặc định)
    from backend.alpha.compile import compile_code
    from backend.crawl.store import load_samples
    from backend.optimize.search.evaluate import execute
    try:
        from backend.core.strategy import build_plan
        engine = "nautilus"
    except ImportError:
        from backend.core.backtest import build_plan
        engine = "old-kernel"
    out = {"engine": engine, "runs": {}}
    for sample in load_samples()[:n]:
        t0 = time.time()
        plan = build_plan(compile_code(sample["code"]), SYMS, position=dict(MODES[mode]) or None, run_frame="1m")
        res, _ = execute(plan, ms(START), ms(END), 10000.0, close_at_end=True)
        trades = {}
        for p in res["positions"]:
            trades.setdefault(p.symbol.split("@")[0], []).append({
                "side": p.pos_type.name, "enter_time": int(p.enter_time), "enter_price": float(p.enter_price), "close_time": int(p.close_time),
                "close_price": float(p.close_price), "reason": p.close_reason, "pnl": float(p.real_pnl), "qty": float(p.qty), "fees": float(p.fees_usd),
                "layers": int(p.layers), "funding": float(p.funding_usd or 0.0)})
        out["runs"][sample["key"]] = {"trades": trades, "final_equity": float(res["final_equity"]), "wall": round(time.time() - t0, 1)}
        print(f"  [{engine}/{mode}] {sample['key']}: {len(res['positions'])} lệnh, vốn cuối {res['final_equity']:.2f}, {time.time() - t0:.1f}s", flush=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh)


def run_worker(old: bool, mode: str, n: int, tmp: str) -> dict:
    out = os.path.join(tmp, f"{'old' if old else 'new'}_{mode}.json")
    env = dict(os.environ)
    env["NORA_DATA_ROOT"] = os.path.join(NORA, "data")
    env.pop("NORA_LOCAL_DATA_ROOT", None)
    env["NORA_ALLOW_UNLIMITED"] = "1"
    if old:
        shim = os.path.join(tmp, "oldpath")
        os.makedirs(shim, exist_ok=True)
        link = os.path.join(shim, "backend")
        if not os.path.islink(link):
            os.symlink(os.path.join(NORA, "test", "backend-no"), link)
        env["PYTHONPATH"], py = shim, OLD_PY
    else:
        env["PYTHONPATH"], py = NORA, sys.executable
    subprocess.run([py, os.path.abspath(__file__), "--worker", out, mode, "--n", str(n)], env=env, check=True, cwd=tmp)
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


TICK = {"BTC": 0.1, "ETH": 0.01}


def explain(old: dict, new: dict, sym: str, mode: str) -> str:
    """Lệnh khác đầu tiên + lý do theo quy ước Nautilus."""
    if old is None:
        return "chỉ engine mới có lệnh này"
    if new is None:
        return "chỉ engine cũ có lệnh này"
    t = TICK[sym]
    if old["enter_time"] != new["enter_time"]:
        return f"giờ vào khác ({_hm(old['enter_time'])} vs {_hm(new['enter_time'])}): chuỗi lệnh lệch sau lệnh trước (đường vốn / nhịp thoát khác)"
    if abs(old["enter_price"] - new["enter_price"]) > 2 * t:
        why = "slippage 0,02% của engine cũ" if mode == "product" else "giá MỞ nến kế (cũ) vs giá ĐÓNG nến tín hiệu (Nautilus market fill)"
        return f"giá vào {old['enter_price']:.2f} vs {new['enter_price']:.2f} ({why})"
    if old["reason"] != new["reason"]:
        return f"lý do thoát khác: '{old['reason']}' vs '{new['reason']}' (cũ: SL theo bar-path/limit_through/thanh lý; Nautilus: khớp theo O→H→L→C)"
    if old["close_time"] != new["close_time"]:
        return f"giờ thoát khác ({_hm(old['close_time'])} vs {_hm(new['close_time'])})"
    if abs(old["close_price"] - new["close_price"]) > 2 * t:
        return f"giá thoát {old['close_price']:.2f} vs {new['close_price']:.2f} (slippage/limit_through của engine cũ; Nautilus stop khớp tại trigger)"
    return f"khác nhỏ: qty {old['qty']:.4f} vs {new['qty']:.4f}, pnl {old['pnl']:.2f} vs {new['pnl']:.2f} (làm tròn lot / phí / funding)"


def _hm(t: int) -> str:
    return dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%m-%d %H:%M")


def table(old: dict, new: dict, mode: str) -> list:
    rows = []
    for key, o in old["runs"].items():
        nw = new["runs"][key]
        for sym in SYMS:
            ot, nt = o["trades"].get(sym, []), nw["trades"].get(sym, [])
            first, why = None, "giống nhau"
            for i in range(max(len(ot), len(nt))):
                a, b = (ot[i] if i < len(ot) else None), (nt[i] if i < len(nt) else None)
                if a is None or b is None or a["enter_time"] != b["enter_time"] or a["reason"] != b["reason"] or a["close_time"] != b["close_time"] \
                        or abs(a["enter_price"] - b["enter_price"]) > 2 * TICK[sym] or abs(a["close_price"] - b["close_price"]) > 2 * TICK[sym]:
                    first, why = i + 1, explain(a, b, sym, mode)
                    break
            rows.append({"sample": key, "symbol": sym, "trades_old": len(ot), "trades_new": len(nt), "first_diff": first, "why": why,
                         "pnl_old": sum(x["pnl"] for x in ot), "pnl_new": sum(x["pnl"] for x in nt), "fund_old": sum(x["funding"] for x in ot)})
        rows[-1]["ret_old"] = (o["final_equity"] / 10000 - 1) * 100
        rows[-1]["ret_new"] = (nw["final_equity"] / 10000 - 1) * 100
        rows[-2]["ret_old"], rows[-2]["ret_new"] = rows[-1]["ret_old"], rows[-1]["ret_new"]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", nargs=2, metavar=("OUT", "MODE"))
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--json", default=None)
    ap.add_argument("--modes", default="product,neutral")
    a = ap.parse_args()
    if a.worker:
        return worker(a.worker[0], a.worker[1], a.n)
    allrows = {}
    with tempfile.TemporaryDirectory(prefix="p15_cmp_") as tmp:
        for mode in a.modes.split(","):
            old, new = run_worker(True, mode, a.n, tmp), run_worker(False, mode, a.n, tmp)
            rows = table(old, new, mode)
            allrows[mode] = rows
            print(f"\n=== chế độ {mode} {MODES[mode] or '(tham số sản phẩm mặc định)'} | {START}..{END} | {', '.join(SYMS)} | base_frame 1m ===")
            print(f"{'mẫu':34s} {'sym':4s} {'lệnh cũ/mới':>11s} {'ret% cũ/mới (2 sym)':>20s} {'Δpnl$ mới-cũ':>12s} {'funding cũ$':>11s} {'lệch đầu':>8s}  lý do")
            for r in rows:
                ret = f"{r['ret_old']:7.2f} / {r['ret_new']:7.2f}" if "ret_old" in r and r["symbol"] == SYMS[-1] else ""
                print(f"{r['sample']:34s} {r['symbol']:4s} {r['trades_old']:5d}/{r['trades_new']:<5d} {ret:>20s} {r['pnl_new'] - r['pnl_old']:12.2f} {r['fund_old']:11.2f} {str(r['first_diff'] or '-'):>8s}  {r['why']}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(allrows, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
