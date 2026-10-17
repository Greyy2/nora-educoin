"""Kiểm thử tính năng Alpha Research (Man Group AlphaTrend) trên Coin Studio (P17 T7).

Kiểm tra:
1. Thẩm định prompt (validate_prompt): độ dài 20-2000, từ chối prompt spam.
2. Sinh ý tưởng (generate_ideas): 1-3 ý tưởng có cấu trúc.
3. Chuyển thành công thức (to_formula): chỉ báo bắt buộc trong catalog Nora.
4. Chuyển thành mã nguồn (to_code): compile DSL + classify (sửa lỗi <= 2 lần).
5. Chạy backtest thật (run_backtest): trả về kết quả Nautilus thật.
6. Tổng hợp kết luận (synthesize): loại bỏ câu bịa số; nhãn đạt/không đạt do code tính toán.
7. Toàn bộ API endpoints của /api/studio/research: tạo job, pick idea, rerun, save.
"""
import os
import pytest
from starlette.testclient import TestClient

from backend.alpha import llm
from backend.alpha import research
from backend.main import app

os.environ["NORA_LLM_MOCK"] = "1"


@pytest.fixture(autouse=True)
def setup_mock_llm():
    """Đảm bảo môi trường test luôn dùng mock LLM nhanh và deterministic."""
    os.environ["NORA_LLM_MOCK"] = "1"
    yield
    llm.set_mock_completer(None)


def test_step1_validate_prompt():
    # Prompt quá ngắn (< 20 ký tự)
    res_short = research.validate_prompt("mua BTC")
    assert not res_short["valid"]
    assert "20 đến 2000" in res_short["reason"]

    # Prompt spam không có ý nghĩa giao dịch
    res_spam = research.validate_prompt("xin chao hom nay thoi tiet the nao 1234567890")
    assert not res_spam["valid"]

    # Prompt hợp lệ có ý nghĩa tài chính
    valid_text = "Mua khi giá vượt EMA 50 và RSI > 55, thoát khi cắt xuống"
    res_ok = research.validate_prompt(valid_text, {"symbol": "BTC-USDT", "timeframe": "1h"})
    assert res_ok["valid"]
    assert res_ok["asset"] == "BTC-USDT"
    assert res_ok["timeframe"] == "1h"


def test_step2_generate_ideas():
    prompt = "Mua khi giá vượt EMA 50 và RSI > 55, thoát khi cắt xuống"
    ideas = research.generate_ideas(prompt, {"symbol": "BTC-USDT", "timeframe": "1h"})
    assert isinstance(ideas, list)
    assert 1 <= len(ideas) <= 3
    for idea in ideas:
        assert "name" in idea
        assert "rationale" in idea
        assert "entry" in idea
        assert "exit" in idea
        assert "risk" in idea


def test_step3_to_formula_indicator_catalog():
    idea = {
        "name": "EMA Cross & RSI",
        "rationale": "Theo xu hướng kết hợp lọc nhiễu",
        "entry": "Giá trên EMA 50 và RSI > 55",
        "exit": "Giá dưới EMA 50",
        "risk": "Dừng lỗ 3%",
    }
    formula = research.to_formula(idea)
    assert isinstance(formula, dict)
    assert "indicators" in formula
    assert "entry_rule" in formula
    assert "exit_rule" in formula

    # Xác nhận mọi chỉ báo đều nằm trong catalog
    cat_names = research._valid_indicator_names()
    for ind in formula["indicators"]:
        assert ind["name"].lower() in cat_names


def test_step4_to_code_and_auto_repair():
    # Trường hợp 1: Mock trả về code chuẩn
    formula = {
        "indicators": [{"name": "ema", "params": {"timeperiod": 50}, "alias": "ema50"}],
        "entry_rule": "close > ema50",
        "exit_rule": "close < ema50",
    }
    code_res = research.to_code(formula)
    assert code_res["compiled"] is True
    assert code_res["route"] is not None
    assert code_res["route"]["engine"] == "dsl"

    # Trường hợp 2: LLM trả về code lỗi ở lần đầu, sau đó sửa thành công ở lần 2
    attempts = [0]

    def mock_broken_then_fixed(messages, schema=None, system=None, **kwargs):
        attempts[0] += 1
        if attempts[0] == 1:
            # Code bị lỗi cú pháp
            return "```python\nclass BadStrategy:\n    def syntax_error(\n```"
        sample_code = """class DualEmaRsiStrategy(SimpleAlgorithm):
    timeframe = "1h"
    fast = 20
    slow = 50
    rsi_period = 14

    def __algorithm__(self):
        f = self.feat.ema(self.data.close, self.fast)
        s = self.feat.ema(self.data.close, self.slow)
        r = self.feat.rsi(self.data.close, self.rsi_period)

        self.set_positions((f > s) & (r > 50), position=1.0)
        self.set_positions(f < s, position=0.0)
"""
        return f"```python\n{sample_code}\n```"

    llm.set_mock_completer(mock_broken_then_fixed)
    repaired_res = research.to_code(formula)
    assert repaired_res["compiled"] is True
    assert attempts[0] >= 2


def test_step6_synthesis_and_fabrication_rejection():
    # Kết quả giả lập
    fake_result = {
        "metrics": {
            "total_return": 0.155,       # 15.5%
            "sharpe_ratio": 1.25,
            "sortino_ratio": 1.80,
            "max_drawdown": 0.082,       # 8.2%
            "win_rate": 0.60,            # 60%
            "total_trades": 45,
            "profit_factor": 1.75,
        },
        "test_metrics": {
            "sharpe_ratio": 1.10,
        },
        "benchmark": {
            "total_return": 0.05,
            "sharpe_ratio": 0.40,
            "max_drawdown": 0.15,
        }
    }

    # Trường hợp 1: LLM sinh câu có số bịa đặt (ví dụ bịa ra số 88.8% không có trong dữ liệu)
    def mock_with_fabricated_numbers(messages, schema=None, system=None, **kwargs):
        return (
            "Chiến lược đạt lợi nhuận 15.5% và Sharpe 1.25 rất ấn tượng. "
            "Tuy nhiên tỷ lệ thắng bịa đặt lên tới 88.8% không có thật trong dữ liệu. "
            "Mức sụt giảm vốn kiểm soát tốt ở 8.2% với 45 giao dịch."
        )

    llm.set_mock_completer(mock_with_fabricated_numbers)
    synth = research.synthesize(fake_result, benchmark=fake_result["benchmark"])

    # Xác nhận câu chứa số bịa 88.8% đã bị loại bỏ
    assert synth["removed_fabricated_sentences"] >= 1
    assert "88.8" not in synth["summary"]
    # Các câu chứa số thật 15.5% và 8.2% vẫn được giữ lại
    assert "15.5" in synth["summary"]
    # Nhãn đạt/không đạt tính bằng code
    assert synth["verdict"] == "đạt"
    assert synth["passed"] is True


def test_api_alpha_research_flow():
    client = TestClient(app)

    # 1. Khởi tạo phiên nghiên cứu
    resp = client.post("/api/studio/research", json={
        "prompt": "Mua khi giá vượt EMA 50 và RSI > 55, thoát khi cắt xuống",
        "opts": {"symbol": "BTC-USDT", "timeframe": "1h"}
    })
    assert resp.status_code == 200
    data = resp.json()
    job_id = data["job_id"]
    assert data["state"] == "waiting_pick"
    assert data["steps"]["step1"]["valid"] is True
    assert len(data["steps"]["step2"]) >= 1

    # 2. Lấy trạng thái qua GET
    get_resp = client.get(f"/api/studio/research/{job_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["job_id"] == job_id

    # 3. Chọn ý tưởng (Pick) -> hoàn thành 6 bước
    pick_resp = client.post(f"/api/studio/research/{job_id}/pick", json={"idea_index": 0})
    assert pick_resp.status_code == 200
    pick_data = pick_resp.json()
    assert pick_data["state"] == "done"
    assert pick_data["steps"]["step3"] is not None
    assert pick_data["steps"]["step4"]["compiled"] is True
    assert pick_data["steps"]["step5"] is not None
    assert pick_data["steps"]["step6"] is not None
    assert pick_data["steps"]["step6"]["verdict"] in ("đạt", "không đạt")

    # 4. Chạy lại từ bước 3 (Rerun)
    rerun_resp = client.post(f"/api/studio/research/{job_id}/rerun", json={
        "from_step": 3,
        "edits": {}
    })
    assert rerun_resp.status_code == 200
    rerun_data = rerun_resp.json()
    assert rerun_data["state"] == "done"

    # 5. Lưu chiến lược vào User Alpha
    save_resp = client.post(f"/api/studio/research/{job_id}/save", json={
        "name": "Alpha Trend EMA RSI",
        "note": "Tạo từ quy trình Alpha Research"
    })
    assert save_resp.status_code == 200
    save_data = save_resp.json()
    assert save_data["ok"] is True
    assert "alpha_id" in save_data
