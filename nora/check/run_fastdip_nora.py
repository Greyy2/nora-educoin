"""Run the exact FastDip alpha used in the TradingView parity check."""
from __future__ import annotations

import json
from pathlib import Path

from backend.jobs.tasks import run_custom


ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "FastDip_Parity_Manifest.json").read_text())
SOURCE = (ROOT / MANIFEST["artifacts"]["nora_source"]).read_text()
CODE = SOURCE[SOURCE.index("class FastDipHarvesterStrategy") :]

position = {
    "market": MANIFEST["position"]["market"],
    "leverage": MANIFEST["position"]["leverage"],
    "sizing": MANIFEST["position"]["sizing"],
    "risk_per_trade_pct": MANIFEST["position"]["risk_per_trade_pct"],
    "stop_loss_rate": MANIFEST["position"]["stop_loss_pct"],
    "take_profit_rate": MANIFEST["position"]["take_profit_pct"],
    "fee_rate": MANIFEST["costs"]["taker_fee_rate"],
    "maker_fee_rate": MANIFEST["costs"]["maker_fee_rate"],
    "slippage_mode": MANIFEST["costs"]["slippage_mode"],
    "slippage_ticks": MANIFEST["costs"]["slippage_ticks"],
    "stop_slippage_multiplier": MANIFEST["costs"]["stop_slippage_multiplier"],
    "quantity_step": MANIFEST["position"]["lot_step_btc"],
    "max_notional_pct": 300.0
}


def main() -> None:
    result = run_custom(
        {
            "code": CODE,
            "symbols": [MANIFEST["nora"]["symbol_input"]],
            "start": MANIFEST["window"]["start"],
            "end": MANIFEST["window"]["end"],
            "train_ratio": 0.7,
            "initial_capital": MANIFEST["capital"]["initial_capital"],
            "position": position,
        }
    )
    report = {
        "manifest": MANIFEST,
        "program_hash": result["program_hash"],
        "metrics": result["metrics"]["simulate"],
        "final_equity": result["final_equity"],
        "trades": result["trades"],
        "data": result["data"],
        "provenance": result["provenance"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
