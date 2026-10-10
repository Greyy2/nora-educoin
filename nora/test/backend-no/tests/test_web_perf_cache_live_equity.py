"""Tách từ test_web_perf_cache.py (P15-C): đệm chuỗi vốn bot live — routes/live.py cũ (test/backend-no/routes/live.py)."""
import json

from backend.routes import live


# ─── 6. live: chuỗi vốn ──────────────────────────────────────────────────────
def test_equity_series_cache_equal_and_invalidates(tmp_path):
    p = tmp_path / "events.jsonl"
    rows = [{"kind": "start", "t": 5}] + [{"kind": "step", "bar": i, "equity": 100.0 + i} for i in range(6)] + [{"kind": "warn", "t": 9}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    a = live._equity_series(str(tmp_path), cap=4)
    assert a == live._equity_series_uncached(str(tmp_path), cap=4) and len(a[0]) == 4 and a[1] == 5 and a[2] == [{"kind": "warn", "t": 9}]
    assert live._equity_series(str(tmp_path), cap=4) is live._equity_series(str(tmp_path), cap=4)          # đệm
    assert live._equity_series(str(tmp_path), cap=2) == live._equity_series_uncached(str(tmp_path), cap=2)  # cap khác: khoá khác
    with open(p, "a") as fh:
        fh.write(json.dumps({"kind": "step", "bar": 99, "equity": 7.0}) + "\n")
    b = live._equity_series(str(tmp_path), cap=4)
    assert b == live._equity_series_uncached(str(tmp_path), cap=4) and b[0][-1] == {"t": 99, "equity": 7.0}
    assert live._equity_series(str(tmp_path / "nope")) == ([], None, [], live._equity_series_uncached(str(tmp_path / "nope"))[3])
    assert a[3]["bars"] == 6 and a[3]["start"] == 100.0 and a[3]["last"] == 105.0   # tóm tắt trên TOÀN đường vốn, không bị cắt cap=4


# ─── 7. chart: nến đọc từ pkl ────────────────────────────────────────────────
