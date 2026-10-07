"""top_agents: doc file dong bang data/alphas/research/okx_top10_agents.json (khong dung test/scripts)."""
from __future__ import annotations

import os

import pytest

from backend.core.analytics import top_agents as ta
from backend.crawl import store

FROZEN = next((os.path.join(store.DATA_HOME, *sub, "research", "okx_top10_agents.json") for sub in (("alpha",), ("alphas",))
               if os.path.isfile(os.path.join(store.DATA_HOME, *sub, "research", "okx_top10_agents.json"))), "")


@pytest.fixture(autouse=True)
def _real_frozen_file(monkeypatch):
    """conftest trỏ kho dữ liệu vào thư mục tạm: file đóng băng (git-tracked) lấy từ cây dữ liệu thật."""
    monkeypatch.setattr(ta, "_frozen_path", lambda: FROZEN)

_BOT_KEYS = {
    "slug", "name", "bot_type", "n_baskets", "in_sample", "caveat", "exit_structure",
    "formula_summary", "class_mix_pct", "in_sample_metrics", "criteria_is",
    "report_stats", "oos", "mixed_runs",
}


def test_frozen_payload_shape_and_provenance():
    d = ta.top_agents()
    assert d["n_bots"] == len(d["bots"]) == 10
    prov = d["provenance"]
    assert d["generated_at"] == prov["frozen_at"]
    assert prov["git_commit"] and len(prov["git_commit"]) >= 7
    assert prov["source"].startswith("test/scripts/okx_top10")
    for b in d["bots"]:
        assert _BOT_KEYS <= set(b)
        src = prov["per_bot_sources"][b["slug"]]
        for k in ("implied", "oos"):
            assert {"file", "mtime", "size", "sha256"} <= set(src[k])
        assert src["mixed_runs"] == b["mixed_runs"]
        assert b["oos"] is not None


def test_mixed_runs_flags_match_mtimes():
    d = ta.top_agents()
    flagged = {b["slug"] for b in d["bots"] if b["mixed_runs"]}
    assert flagged == {"01pp", "dark_wood_dahlia", "physical_epoch_fuel"}
    for b in d["bots"]:
        src = d["provenance"]["per_bot_sources"][b["slug"]]
        newer = src["implied"]["mtime"] > src["oos"]["mtime"]  # ISO UTC cung dinh dang -> so sanh chuoi
        assert b["mixed_runs"] is newer
        assert bool(b.get("mixed_runs_note")) is newer


def test_missing_file_returns_empty_with_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(ta, "_frozen_path", lambda: str(tmp_path / "nope.json"))
    d = ta.top_agents()
    assert d["bots"] == [] and d["n_bots"] == 0 and d["reason"]


def test_corrupt_file_returns_empty_with_reason(monkeypatch, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(ta, "_frozen_path", lambda: str(p))
    d = ta.top_agents()
    assert d["bots"] == [] and d["n_bots"] == 0 and d["reason"]


def test_no_reference_to_research_scripts():
    src = open(ta.__file__, encoding="utf-8").read()
    assert "test/scripts" not in src and "okx_top10/out" not in src
    assert "okx_top10_agents.json" in src
