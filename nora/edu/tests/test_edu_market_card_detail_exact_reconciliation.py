"""Test reconciliation of Market cards and User strategies against Strategy Detail endpoint (EDU-16).

Acceptance Criteria:
- 100% of rows accounted for across all persisted user alphas in nora/edu/data/alpha/user.
- Every card advertising a completed result resolves to an exact valid result object with matching run_id, version, and metrics.
- Card metrics (ret_pct, trades, sharpe, pnl_usd) reconcile exactly with detail.result metrics.
- Historical results are transparently identified with is_historical_result=True and matching metrics_status.
"""
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.analys.alpha import store
from backend import users


@pytest.fixture
def client():
    return TestClient(app)


def test_reconcile_100_percent_of_user_alpha_records(client):
    """Kiểm tra 100% toàn bộ mọi file alpha trong kho dữ liệu nora/edu/data/alpha/user:
    - Phân loại rõ ràng từng file: ACTIVE, HISTORICAL, NO_RESULT, ARCHIVED, OWNERLESS.
    - Card và Detail API phải phân giải cùng 1 run_id, cùng version, cùng trạng thái is_historical_result.
    - Provenance chân thực: result_version phải lấy từ chính artifact lịch sử (nếu không có thì None, không được gán bừa current_version).
    - Đối soát PnL với Oracle tính độc lập từ final_equity - initial_capital của chính run config trong artifact.
    """
    alpha_dir = Path("nora/edu/data/alpha/user")
    files = sorted(alpha_dir.glob("*.json"))
    total_files = len(files)
    assert total_files > 0, "No user alpha files found"

    counts = {
        "active": 0,
        "historical": 0,
        "no_result": 0,
        "archived": 0,
        "ownerless": 0,
    }

    for path in files:
        rec = json.loads(path.read_text(encoding="utf-8"))
        alpha_id = rec.get("id") or path.stem
        owner_id = rec.get("owner_id")

        if not owner_id:
            counts["ownerless"] += 1
            res = client.get(f"/api/edu/strategies/{alpha_id}")
            assert res.status_code == 404
            continue

        if rec.get("status") == "ARCHIVED":
            counts["archived"] += 1
            res = client.get(f"/api/edu/strategies/{alpha_id}")
            assert res.status_code == 404
            continue

        card = store.strategy_card(rec, store._sample_meta())

        # Kiểm tra qua API endpoint công khai
        res = client.get(f"/api/edu/strategies/{alpha_id}")
        assert res.status_code == 200, f"Failed to get strategy detail for {alpha_id}"
        detail = res.json()

        # Đối chiếu định danh phiên bản và lần chạy
        assert detail["id"] == alpha_id
        assert detail.get("run_id") == card.get("run_id"), f"Mismatch run_id for {alpha_id}"
        assert detail.get("version") == card.get("version"), f"Mismatch version for {alpha_id}"
        assert detail.get("is_historical_result") == card.get("is_historical_result"), f"Mismatch is_historical for {alpha_id}"
        assert detail.get("metrics_status") == card.get("metrics_status"), f"Mismatch metrics_status for {alpha_id}"
        assert detail.get("current_version") == rec.get("version"), f"Mismatch current_version for {alpha_id}"
        assert detail.get("result_version") == card.get("result_version"), f"Mismatch result_version for {alpha_id}"

        # Kiểm tra Provenance lịch sử chân thực:
        if detail.get("is_historical_result"):
            hist = rec.get("contract_history") or []
            snap = next(((x.get("result_snapshot") or {}) for x in reversed(hist) if isinstance(x, dict) and isinstance((x.get("result_snapshot") or {}).get("result"), dict) and (x.get("result_snapshot") or {}).get("result")), {})
            expected_res_ver = snap.get("version") or (snap.get("result") or {}).get("version")
            # TUYỆT ĐỐI KHÔNG gán current_version nếu snapshot không có version
            assert detail.get("result_version") == expected_res_ver, f"Alpha {alpha_id}: historical result_version must be {expected_res_ver}, got {detail.get('result_version')}"
        else:
            if card.get("has_result"):
                assert detail.get("result_version") == rec.get("version"), f"Active alpha {alpha_id} result_version mismatch"

        # Đối soát số đo giữa Card và Detail
        if card.get("has_result"):
            assert detail.get("result") is not None, f"Card for {alpha_id} claims has_result=True, but detail.result is None!"
            result = detail["result"]
            res_m = result.get("metrics", {})
            sim = res_m.get("simulate") or res_m

            # Đối soát ret_pct
            if card.get("ret_pct") is not None:
                sim_ret = sim.get("ret_pct") if "ret_pct" in sim else sim.get("return_pct")
                assert sim_ret is not None, f"Alpha {alpha_id}: card has ret_pct={card['ret_pct']} but simulate metrics has no return"
                assert round(float(card["ret_pct"]), 2) == round(float(sim_ret), 2), f"Alpha {alpha_id} ret_pct mismatch"

            # Đối soát trades
            if card.get("trades") is not None:
                sim_trades = sim.get("trades") if "trades" in sim else sim.get("total_trades")
                assert sim_trades is not None, f"Alpha {alpha_id}: card has trades={card['trades']} but simulate metrics has no trades"
                assert int(card["trades"]) == int(sim_trades), f"Alpha {alpha_id} trades count mismatch"

            # Đối soát sharpe
            if card.get("sharpe") is not None:
                sim_sharpe = sim.get("sharpe")
                assert sim_sharpe is not None, f"Alpha {alpha_id}: card has sharpe={card['sharpe']} but simulate metrics has no sharpe"
                assert round(float(card["sharpe"]), 4) == round(float(sim_sharpe), 4), f"Alpha {alpha_id} sharpe mismatch"

            # Đối soát mdd_pct
            if card.get("mdd_pct") is not None:
                sim_mdd = sim.get("mdd_pct") if "mdd_pct" in sim else (abs(float(sim.get("mdd", 0))) * 100.0 if sim.get("mdd") is not None else None)
                assert sim_mdd is not None, f"Alpha {alpha_id}: card has mdd_pct={card['mdd_pct']} but simulate metrics has no mdd"
                assert round(float(card["mdd_pct"]), 2) == round(abs(float(sim_mdd)), 2), f"Alpha {alpha_id} mdd_pct mismatch"

            # Đối soát pnl_usd với ORACLE tính độc lập từ final_equity - initial_capital của chính lượt chạy
            if card.get("pnl_usd") is not None:
                detail_card = detail.get("card", {})
                assert detail_card.get("pnl_usd") is not None, f"Alpha {alpha_id}: card has pnl_usd but detail card does not"
                assert round(float(card["pnl_usd"]), 2) == round(float(detail_card["pnl_usd"]), 2), f"Alpha {alpha_id} pnl_usd mismatch"

                # Oracle check từ run artifact config
                run_cfg = result.get("config") or rec.get("config") or {}
                run_cap = run_cfg.get("initial_capital")
                fin_eq = result.get("final_equity") or rec.get("final_equity")
                if run_cap is not None and fin_eq is not None:
                    oracle_pnl = round(float(fin_eq) - float(run_cap), 2)
                    assert round(float(card["pnl_usd"]), 2) == oracle_pnl, f"Alpha {alpha_id}: card pnl {card['pnl_usd']} does not match oracle {oracle_pnl}"

            if detail.get("is_historical_result"):
                counts["historical"] += 1
            else:
                counts["active"] += 1
        else:
            assert detail.get("result") is None, f"Card for {alpha_id} has_result=False, but detail.result is not None!"
            counts["no_result"] += 1

    # Khẳng định 100% tệp đều được kiểm toán và phân loại đầy đủ
    total_audited = sum(counts.values())
    assert total_audited == total_files, f"Audited {total_audited} / {total_files} files"
    print(f"\nAUDIT TOTAL: {total_files} files | "
          f"Active: {counts['active']} | "
          f"Historical: {counts['historical']} | "
          f"No result: {counts['no_result']} | "
          f"Archived: {counts['archived']} | "
          f"Ownerless: {counts['ownerless']}")


def test_market_cards_and_detail_reconciliation(client):
    """Mọi thẻ chiến lược hiển thị trên Market khi mở chi tiết /api/edu/strategies/{id} đều phải khớp 100% về identity và metrics."""
    res = client.get("/api/edu/market")
    assert res.status_code == 200
    data = res.json()
    assert "users" in data
    assert len(data["users"]) > 0

    checked_alphas = set()
    for u in data["users"]:
        best = u.get("best")
        if best and best.get("id"):
            alpha_id = best["id"]
            if alpha_id not in checked_alphas:
                checked_alphas.add(alpha_id)
                detail_res = client.get(f"/api/edu/strategies/{alpha_id}")
                assert detail_res.status_code == 200, f"Failed to get detail for alpha {alpha_id}"
                detail = detail_res.json()
                assert detail["id"] == alpha_id

                # Khớp định danh lần chạy và phiên bản giữa Market card và Strategy Detail
                assert detail.get("run_id") == best.get("run_id"), f"Market card vs detail run_id mismatch for {alpha_id}"
                assert detail.get("version") == best.get("version"), f"Market card vs detail version mismatch for {alpha_id}"
                assert detail.get("is_historical_result") == best.get("is_historical_result"), f"Market card vs detail is_historical mismatch for {alpha_id}"
                assert detail.get("metrics_status") == best.get("metrics_status"), f"Market card vs detail metrics_status mismatch for {alpha_id}"

                # Nếu card có số đo PnL / trades thì detail BẮT BUỘC phải có result (không được rỗng)
                if best.get("has_result"):
                    assert detail.get("result") is not None, f"Alpha {alpha_id} has card has_result=True but null detail.result"
                    res_metrics = detail["result"].get("metrics", {})
                    sim = res_metrics.get("simulate") or res_metrics
                    assert sim is not None, f"Alpha {alpha_id} result missing simulate metrics"

                    # Đối soát số đo
                    if best.get("ret_pct") is not None:
                        assert round(float(best["ret_pct"]), 2) == round(float(detail.get("card", {}).get("ret_pct")), 2)
                    if best.get("trades") is not None:
                        assert int(best["trades"]) == int(detail.get("card", {}).get("trades"))
                    if best.get("pnl_usd") is not None:
                        assert round(float(best["pnl_usd"]), 2) == round(float(detail.get("card", {}).get("pnl_usd")), 2)
                else:
                    assert detail.get("result") is None, f"Alpha {alpha_id} card has has_result=False but detail.result is not None"


def test_all_user_strategies_resolve_accurately(client):
    """Mọi strategy trong hồ sơ user (/api/edu/users/{handle}) đều đối soát chính xác với detail."""
    user_list = users.list_users()
    tested_users = 0

    for u in user_list:
        handle = u.get("handle")
        if not handle:
            continue
        res = client.get(f"/api/edu/users/{handle}")
        if res.status_code != 200:
            continue
        data = res.json()
        strategies = data.get("strategies", [])
        for s in strategies:
            alpha_id = s.get("id")
            if not alpha_id:
                continue
            detail_res = client.get(f"/api/edu/strategies/{alpha_id}")
            assert detail_res.status_code == 200
            detail = detail_res.json()
            assert detail.get("run_id") == s.get("run_id")
            assert detail.get("version") == s.get("version")
            if s.get("has_result"):
                assert detail.get("result") is not None, f"User strategy {alpha_id} has has_result=True but detail.result is None"
            else:
                assert detail.get("result") is None, f"User strategy {alpha_id} has has_result=False but detail.result is not None"
        tested_users += 1

    assert tested_users > 0
