"""Module gọi LLM tập trung (Claude API) cho Alpha Research (P17 T7).

Nguyên tắc:
1. Đọc khoá từ ~/.config/nora/llm.env hoặc biến môi trường ANTHROPIC_API_KEY.
2. Tuyệt đối không lưu khoá vào repo, file log hay ném khoá ra ngoài ngoại lệ (mask key).
3. Hỗ trợ timeout (45s), retry 2 lần khi lỗi mạng/5xx.
4. Hỗ trợ mock hoàn toàn trong môi trường test (NORA_LLM_MOCK hoặc set_mock_completer).
"""
import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Union

import httpx

logger = logging.getLogger("backend.analys.alpha.llm")

DEFAULT_MODEL = os.environ.get("NORA_LLM_MODEL", "claude-3-5-sonnet-20241022")
ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

_MOCK_COMPLETER: Optional[Callable[..., Any]] = None


def set_mock_completer(fn: Optional[Callable[..., Any]]) -> None:
    """Gán hàm mock cho LLM trong test suite."""
    global _MOCK_COMPLETER
    _MOCK_COMPLETER = fn


def _mask_key(key: Optional[str]) -> str:
    if not key or len(key) < 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def load_api_key() -> Optional[str]:
    """Đọc API key từ ~/.config/nora/llm.env hoặc env var."""
    # 1. Biến môi trường trực tiếp
    for env_name in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "NORA_LLM_KEY"):
        val = os.environ.get(env_name)
        if val and val.strip():
            return val.strip()

    # 2. File ~/.config/nora/llm.env
    env_file = os.path.expanduser("~/.config/nora/llm.env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("\"'")
                        if k in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "NORA_LLM_KEY"):
                            return v
        except OSError as e:
            logger.warning("Không thể đọc file %s: %s", env_file, e)

    return None


def extract_json_from_text(text: str) -> Optional[Any]:
    """Trích xuất và phân tích JSON từ chuỗi văn bản (hỗ trợ cả codeblock ```json)."""
    text = text.strip()
    # Tìm khối codeblock ```json ... ``` hoặc ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # Tìm json object/array trực tiếp
    match_braces = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match_braces:
        candidate = match_braces.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass

    try:
        return json.loads(text)
    except Exception:
        return None


def _default_mock_completer(
    messages: List[Dict[str, str]],
    schema: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    system: Optional[str] = None,
    temperature: float = 0.2,
    **kwargs: Any,
) -> Union[Dict[str, Any], List[Any], str]:
    user_content = messages[-1]["content"] if messages else ""
    sys_str = (system or "").lower()

    # Bước 1: Thẩm định prompt (validate_prompt)
    if (schema and "valid" in schema and "reason" in schema) or "quant research validator" in sys_str:
        if any(w in user_content.lower() for w in ("thoi tiet", "xin chao", "1234567890")):
            return {
                "valid": False,
                "reason": "Prompt không có ý nghĩa tài chính rõ ràng.",
                "normalized_prompt": user_content,
                "asset": "BTC-USDT",
                "timeframe": "1h",
                "side": "both",
            }
        return {
            "valid": True,
            "reason": "Prompt giao dịch hợp lệ theo xu hướng.",
            "normalized_prompt": user_content.split("\n")[1] if "\n" in user_content else user_content,
            "asset": "BTC-USDT",
            "timeframe": "1h",
            "side": "both",
        }

    # Bước 2: Sinh ý tưởng (generate_ideas)
    if (schema and "ideas" in schema) or "quant alpha researcher" in sys_str:
        return {
            "ideas": [
                {
                    "id": 1,
                    "name": "Dual EMA RSI Trend",
                    "rationale": "Theo xu hướng kết hợp lọc quá mua/quá bán với RSI",
                    "entry": "Giá trên EMA 50 và RSI > 55",
                    "exit": "Giá dưới EMA 50 hoặc cắt xuống",
                    "risk": "Dừng lỗ 3% cố định",
                }
            ]
        }

    # Bước 3: Chuyển thành công thức (to_formula)
    if (schema and "indicators" in schema) or "quant modeler" in sys_str:
        return {
            "indicators": [
                {"name": "ema", "params": {"timeperiod": 50}, "alias": "ema50"},
                {"name": "rsi", "params": {"timeperiod": 14}, "alias": "rsi14"},
            ],
            "entry_rule": "close > ema50 and rsi14 > 55",
            "exit_rule": "close < ema50",
            "params": {"leverage": 1.0, "stop_loss_pct": 0.03},
            "description_vi": "Chiến lược EMA và RSI",
        }

    # Bước 4: Sinh mã nguồn (to_code)
    if "kỹ sư định lượng chuyên viết mã nguồn" in sys_str or "nora dsl" in sys_str:
        return """```python
class DualEmaRsiStrategy(SimpleAlgorithm):
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
```"""

    # Bước 6: Tổng hợp kết luận (synthesize)
    if "quant performance analyst" in sys_str or "nguyên tắc nghiêm ngặt về con số" in sys_str:
        return "Chiến lược đạt lợi nhuận và mức sụt giảm vốn trong kiểm soát. Tín hiệu vận hành ổn định."

    if schema:
        return schema
    return "OK"


def complete(
    messages: List[Dict[str, str]],
    schema: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    system: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> Union[Dict[str, Any], List[Any], str]:
    """Gọi LLM tập trung bọc Claude API hoặc mock.

    Args:
        messages: Danh sách message [{"role": "user"|"assistant", "content": ...}]
        schema: (Tuỳ chọn) Dict mô tả schema JSON mong muốn nhận về
        model: Tên model Claude (mặc định claude-3-5-sonnet-20241022)
        system: (Tuỳ chọn) System prompt
        temperature: Độ biến thiên (mặc định 0.2)
        max_tokens: Số token tối đa (mặc định 4096)

    Returns:
        Dict/List nếu schema được truyền hoặc kết quả parse được JSON; ngược lại chuỗi str.
    """
    # 1. Kiểm tra mock trước
    if _MOCK_COMPLETER is not None:
        return _MOCK_COMPLETER(
            messages=messages,
            schema=schema,
            model=model or DEFAULT_MODEL,
            system=system,
            temperature=temperature,
        )

    if os.environ.get("NORA_LLM_MOCK") == "1":
        return _default_mock_completer(
            messages=messages,
            schema=schema,
            model=model or DEFAULT_MODEL,
            system=system,
            temperature=temperature,
        )

    api_key = load_api_key()
    if not api_key:
        raise ValueError("Chưa cấu hình API key LLM trong ~/.config/nora/llm.env hoặc biến ANTHROPIC_API_KEY")

    mdl = model or DEFAULT_MODEL

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    # Đưa yêu cầu JSON vào system nếu có schema
    sys_prompt = system or ""
    if schema:
        sys_prompt += (
            "\n\nBẠN BẮT BUỘC PHẢI TRẢ VỀ DUY NHẤT MỘT ĐỐI TƯỢNG JSON HỢP LỆ THEO ĐỊNH DẠNG SAU, "
            "KHÔNG KÈM BẤT KỲ VĂN BẢN NÀO NGOÀI JSON:\n"
            + json.dumps(schema, ensure_ascii=False, indent=2)
        )

    payload = {
        "model": mdl,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if sys_prompt:
        payload["system"] = sys_prompt

    # Retry 2 lần (tổng 3 lần)
    last_err = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(ANTHROPIC_ENDPOINT, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    # Trích xuất nội dung từ phản hồi Claude
                    blocks = data.get("content", [])
                    txt = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                    if schema:
                        parsed = extract_json_from_text(txt)
                        if parsed is not None:
                            return parsed
                        # Nếu không parse được json, trả về dict báo lỗi hoặc thô
                        raise ValueError(f"Không thể trích xuất JSON hợp lệ từ phản hồi LLM: {txt[:200]}")
                    return txt

                if resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning("Lỗi tạm thời khi gọi Claude (status %d), thử lại...", resp.status_code)
                    time.sleep(1.0 * (attempt + 1))
                    continue

                # Lỗi client (400, 401, 403, 404...)
                err_text = resp.text
                # Che giấu key nếu có xuất hiện
                err_text = err_text.replace(api_key, _mask_key(api_key))
                raise RuntimeError(f"Claude API trả về lỗi {resp.status_code}: {err_text}")
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_err = e
            logger.warning("Lỗi kết nối tới Claude API (lần %d): %s", attempt + 1, e)
            time.sleep(1.0 * (attempt + 1))

    raise RuntimeError(f"Gọi Claude API thất bại sau 3 lần thử: {last_err}")
