"""Top agent trade: doc ket qua da dong bang (implied exit fit + OOS) cua 10 bot copy-trade top OKX.

Nguon duy nhat: data/alphas/research/okx_top10_agents.json (git-tracked, co provenance).
Khong doc scripts nghien cuu; ket qua nghien cuu da duoc dong bang mot lan.

GET /api/studio/alphas/top_agents
{
  "bots": [ { "slug", "name", "bot_type", "n_baskets", "in_sample", "caveat",
              "exit_structure", "formula_summary", "class_mix_pct",
              "in_sample_metrics", "criteria_is", "report_stats", "oos",
              "mixed_runs", "mixed_runs_note" }, ... ],
  "n_bots": 10,
  "generated_at": "<frozen_at>",
  "provenance": { "frozen_at", "git_commit", "source", "per_bot_sources", ... }
}
Neu file khong co: {"bots": [], "n_bots": 0, "reason": "..."}.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

_FROZEN_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "data", "alphas", "research", "okx_top10_agents.json",
))


def _empty(reason: str) -> Dict[str, Any]:
    return {"bots": [], "n_bots": 0, "reason": reason}


def top_agents() -> Dict[str, Any]:
    try:
        with open(_FROZEN_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return _empty("Chua co file dong bang data/alphas/research/okx_top10_agents.json")
    except (OSError, ValueError) as exc:
        return _empty(f"Khong doc duoc file dong bang okx_top10_agents.json: {exc}")
    if not isinstance(d, dict) or not isinstance(d.get("bots"), list):
        return _empty("File dong bang okx_top10_agents.json sai dinh dang (thieu 'bots')")

    prov = d.get("provenance") or {}
    bots = d["bots"]
    for b in bots:
        b.setdefault("mixed_runs", False)
        b.setdefault("mixed_runs_note", None)
    return {
        "bots": bots,
        "n_bots": len(bots),
        "generated_at": prov.get("frozen_at"),
        "provenance": prov,
    }
