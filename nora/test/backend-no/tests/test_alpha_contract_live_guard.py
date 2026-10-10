"""Tách từ test_alpha_contract.py (P15): guard LIVE_BOT_RUNNING chờ live Nautilus TradingNode. Cần fixture client/temp_strategies của test_alpha_contract."""
import os

from test_alpha_contract import client, temp_strategies  # noqa: F401


def test_edit_live_bot_guard_and_backup_limit(client, temp_strategies, monkeypatch):
    got = client.get("/api/studio/strategies/source/sideway").json()
    legs = got["legs"]
    renamed = got["code"].replace(f'"{legs[0]}"', f'"{legs[0]}_v2"')
    assert renamed != got["code"]
    from backend.optimize.process import process as jobs_store
    running = [{"status": "running", "params": {"strategy": legs[0]}}]
    monkeypatch.setattr(jobs_store, "list_jobs", lambda **kw: running)
    r = client.put("/api/studio/strategies/source/sideway", json={"code": renamed, "sha256": got["sha256"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LIVE_BOT_RUNNING" and legs[0] in r.json()["detail"]["removed"]
    # giữ nguyên id vẫn sửa được khi bot chạy; 22 lần sửa -> tối đa 20 bản sao lưu
    sha, code = got["sha256"], got["code"]
    for i in range(22):
        code = code.replace("Dạng đã biên dịch" if i == 0 else f"#{i - 1}#", f"#{i}#", 1) if i else code + "\n# v0\n"
        r = client.put("/api/studio/strategies/source/sideway", json={"code": code + f"\n# edit {i}\n", "sha256": sha})
        assert r.status_code == 200, r.text
        sha = r.json()["sha256"]
        code = code.split("\n# edit")[0]
    from backend.alpha import compile as dsl
    bdir = os.path.join(dsl.strategies_dir(), dsl.BACKUP_DIRNAME)
    assert dsl.strategies_dir() == str(temp_strategies)
    assert all(os.path.dirname(p) == str(temp_strategies) for p in dsl.strategy_files())      # .versions không lẫn vào loader
    assert len([n for n in os.listdir(bdir) if n.startswith("sideway.")]) == dsl.MAX_BACKUPS
    running.clear()          # bot dừng -> đổi id được phép
    r = client.put("/api/studio/strategies/source/sideway", json={"code": renamed, "sha256": sha})
    assert r.status_code == 200 and f"{legs[0]}_v2" in r.json()["legs"]
