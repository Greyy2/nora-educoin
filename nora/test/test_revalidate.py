"""P3.3: kiểm lại alpha trong kho bằng engine hiện hành (backend/optimize/revalidate.py) + ghi trạng thái registry / gỡ testnet."""
import json
import os

from backend.optimize import revalidate as rv
from backend.optimize.funnel import gates
from test_strategy_book import T0, market  # noqa: F401  (market là fixture: 70 ngày, 3 tài sản)

DAY = 86_400_000
F = lambda fr, c: {"frame": fr, "column": c, "index": 0}  # noqa: E731
ALPHA = {"alpha_id": "rsi_long__AAA", "strategy": "rsi_long", "side": "LONG", "symbol": "AAA", "data_symbol": "AAA@perp", "market": "perp",
         "position": {"market": "perp", "leverage": 1, "order_size_pct": 30, "stop_loss_rate": 2.0, "take_profit_rate": 2.0, "timeout": 720},
         "flows": [{"id": "rsi_long", "type": "LONG", "ast": {"type": "LONG", "match": [{"condition": [[[F("15m", "rsi_14"), "<", 40]]]}],
                                                              "stop": []}}]}
WIN = {"start": T0 + 2 * DAY, "dev1_end": T0 + 20 * DAY, "dev2_end": T0 + 55 * DAY, "end": T0 + 68 * DAY}


def _kit(tmp_path):
    base = tmp_path / "alphas"
    (base / "testnet").mkdir(parents=True)
    (base / "registry.json").write_text(json.dumps({"alphas": [ALPHA]}))
    (base / "testnet" / "rsi_long__AAA.json").write_text("{}")
    return str(base)


def test_retired_when_wfa_fails_and_apply_moves_testnet(market, monkeypatch, tmp_path):
    base = _kit(tmp_path)
    monkeypatch.setattr(gates, "S3_TRAIN_DAYS", 10)
    monkeypatch.setattr(gates, "S3_TEST_DAYS", 5)
    monkeypatch.setattr(gates, "S3_MIN_FOLDS", 99)                       # cổng không thể qua -> loại
    rep = rv.revalidate(rv.load_alpha("rsi_long__AAA", base), WIN)
    assert rep["status"] == "retired" and rep["reject_code"] == "S3.folds" and rep["wfa"]["passed"] is False
    assert rep["wfa"]["summary"]["folds"] == len(gates.wfa_folds(WIN)) >= 4
    assert rep["shock"] is None or set(rep["shock"]) >= {"crash_loss", "surge_loss"}
    changed = rv.apply_result(rep, base)
    reg = json.load(open(os.path.join(base, "registry.json")))
    assert reg["alphas"][0]["status"] == "retired" and reg["alphas"][0]["revalidation"]["reject_code"] == "S3.folds"
    assert not os.path.exists(os.path.join(base, "testnet", "rsi_long__AAA.json"))
    assert os.path.isfile(os.path.join(base, "testnet", "_retired", "rsi_long__AAA.json")) and len(changed) == 2


def test_validated_with_lenient_gates_gets_scale_and_keeps_testnet(market, monkeypatch, tmp_path):
    base = _kit(tmp_path)
    for k, v in dict(S3_TRAIN_DAYS=10, S3_TEST_DAYS=5, S3_MIN_FOLDS=2, S3_MIN_TRADED_FOLDS=0, S3_MIN_FOLD_T=-1e9, S3_MIN_EX_BEST_FOLD_PCT=-1e9, S3_MIN_COMPOUNDED_OOS_PCT=-1000.0,
                     S3_MAX_FOLD_MDD_PCT=1000.0, S3_MIN_AVG_IS_RET_PCT=-1000.0, S4_MIN_SIMULATIONS=200, S4_MAX_RUIN_PCT=100.0,
                     S4_STRESS_MAX_MDD_PCT=1000.0, S4_MIN_DAYS=5, S6_MIN_RET_PCT=-1000.0, S6_MAX_MDD_PCT=1000.0).items():
        monkeypatch.setattr(gates, k, v)
    rep = rv.revalidate(rv.load_alpha("rsi_long__AAA", base), WIN)
    assert rep["status"] == "validated" and rep["final_scale"] == 1.0 and rep["holdout"]["passed"] is True
    assert rep["wfa"]["metrics"]["trades"] > 0
    rv.apply_result(rep, base)
    assert json.load(open(os.path.join(base, "registry.json")))["alphas"][0]["status"] == "validated"
    assert os.path.isfile(os.path.join(base, "testnet", "rsi_long__AAA.json"))
