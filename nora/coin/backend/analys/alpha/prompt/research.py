"""Pipeline 6 bước Alpha Research (Man Group AlphaTrend) cho Coin Studio (P17 T7).

1. validate_prompt: Thẩm định prompt có ý nghĩa tài chính (20-2000 ký tự).
2. generate_ideas: Sinh 1-3 ý tưởng giao dịch {name, rationale, entry, exit, risk}.
3. to_formula: Chuyển ý tưởng thành công thức chỉ báo (bắt buộc trong catalog Nora).
4. to_code: Sinh mã nguồn Nora DSL, compile_code + route.classify (sửa lỗi <= 2 lần).
5. run_backtest: Chạy backtest Nautilus thật qua run_custom + benchmark.
6. synthesize: Tổng hợp kết luận (loại bỏ câu bịa số bằng regex; nhãn đạt/không đạt tính bằng code).
"""
import hashlib
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlsplit

import httpx

from . import llm
from ..code.compile import compile_code
from ..code.contract import catalog
from ..code.route import classify
from ...signal import DslError

logger = logging.getLogger("backend.analys.alpha.research")
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s]+$", re.IGNORECASE)


def _read_prompt_template(name: str) -> str:
    path = os.path.join(PROMPTS_DIR, name)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            pass
    return ""


# ══════════════════════════════════════════════════════════════════════════
# BƯỚC 1: Validate Prompt
# ══════════════════════════════════════════════════════════════════════════

def validate_prompt(text: str, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Kiểm tra độ dài (20-2000 ký tự) và gọi LLM phân loại 'có ý nghĩa tài chính?'."""
    opts = opts or {}
    text_clean = (text or "").strip()
    length = len(text_clean)

    if length < 20 or length > 2000:
        return {
            "valid": False,
            "reason": f"Độ dài prompt phải từ 20 đến 2000 ký tự (hiện tại: {length} ký tự).",
            "normalized_prompt": text_clean,
            "asset": opts.get("symbol") or "BTC-USDT",
            "timeframe": opts.get("timeframe") or "1h",
            "side": opts.get("side") or "both",
            "opts": opts,
        }

    sys_template = _read_prompt_template("1_validate.md")
    user_prompt = f"Prompt của người dùng:\n{text_clean}\n\nTuỳ chọn kèm theo:\n{json.dumps(opts, ensure_ascii=False)}"

    schema = {
        "valid": True,
        "reason": "Giải thích tính hợp lệ bằng tiếng Việt",
        "normalized_prompt": "Prompt chuẩn hoá",
        "asset": "BTC-USDT",
        "timeframe": "1h",
        "side": "both",
    }

    resp = llm.complete(
        messages=[{"role": "user", "content": user_prompt}],
        schema=schema,
        system=sys_template,
        temperature=0.1,
    )

    if not isinstance(resp, dict):
        return {
            "valid": False,
            "reason": "Không nhận được phản hồi phân tích hợp lệ từ LLM/Provider. Vui lòng kiểm tra cấu hình kết nối.",
            "normalized_prompt": text_clean,
            "asset": opts.get("symbol") or "BTC-USDT",
            "timeframe": opts.get("timeframe") or "1h",
            "side": opts.get("side") or "both",
            "opts": opts,
        }

    raw_valid = resp.get("valid")
    text_fields = ("reason", "normalized_prompt", "asset", "timeframe", "side")
    malformed_fields = [field for field in text_fields if field in resp and not isinstance(resp[field], str)]
    schema_valid = type(raw_valid) is bool and not malformed_fields
    valid = raw_valid if schema_valid else False

    reason_val = resp.get("reason")
    if isinstance(reason_val, str) and reason_val.strip():
        reason = reason_val.strip()
    elif type(raw_valid) is not bool:
        reason = "Phản hồi từ provider không đúng schema: 'valid' phải là boolean."
    elif malformed_fields:
        reason = f"Phản hồi từ provider không đúng schema: trường phải là chuỗi: {', '.join(malformed_fields)}."
    else:
        reason = "Prompt hợp lệ" if valid else "Prompt không có ý nghĩa tài chính rõ ràng hoặc phản hồi từ provider không đạt chuẩn"
    norm = resp.get("normalized_prompt") if isinstance(resp.get("normalized_prompt"), str) and resp["normalized_prompt"].strip() else text_clean
    asset = resp.get("asset") if isinstance(resp.get("asset"), str) and resp["asset"].strip() else opts.get("symbol") or "BTC-USDT"
    tf = resp.get("timeframe") if isinstance(resp.get("timeframe"), str) and resp["timeframe"].strip() else opts.get("timeframe") or "1h"
    side = resp.get("side") if isinstance(resp.get("side"), str) and resp["side"].strip() else opts.get("side") or "both"

    return {
        "valid": valid,
        "reason": reason,
        "normalized_prompt": norm,
        "asset": asset,
        "timeframe": tf,
        "side": side,
        "opts": opts,
    }


# ══════════════════════════════════════════════════════════════════════════
# BƯỚC 2: Generate Ideas
# ══════════════════════════════════════════════════════════════════════════

def _sanitize_citations(cits: Any) -> List[Dict[str, Any]]:
    """Lọc và chuẩn hoá danh mục tài liệu tham khảo.

    Tài liệu do mô hình LLM gợi ý khi chưa qua crawler/công cụ truy xuất web thực tế
    bắt buộc phải mang nhãn verified=False và status='unverified_reference'.
    Tuyệt đối KHÔNG giả mạo cờ verified=True hoặc thời gian truy xuất (retrieval_time).
    """
    if not isinstance(cits, list):
        return []
    sanitized = []
    for c in cits:
        if not isinstance(c, dict):
            continue
        title = c.get("title")
        title = title.strip() if isinstance(title, str) else ""
        if not title:
            continue
        provider = c.get("provider")
        url = c.get("url")
        excerpt = c.get("excerpt")
        sanitized.append({
            "provider": provider.strip() if isinstance(provider, str) and provider.strip() else "LLM Suggested Reference",
            "title": title,
            "url": url.strip() if isinstance(url, str) else "",
            "doi": c.get("doi") if isinstance(c.get("doi"), str) else "",
            "retrieval_time": None,
            "excerpt": excerpt.strip() if isinstance(excerpt, str) else "",
            "verified": False,
            "status": "unverified_reference",
        })
    return sanitized


def _citation_doi(citation: Dict[str, Any]) -> str:
    value = citation.get("doi") or citation.get("url")
    if not isinstance(value, str):
        raise ValueError("Citation phải có DOI hoặc URL DOI.")
    value = value.strip()
    if value.lower().startswith("doi:"):
        value = value[4:].strip()
    elif value.startswith(("https://", "http://")):
        parsed = urlsplit(value)
        if parsed.hostname not in {"doi.org", "www.doi.org", "dx.doi.org"}:
            raise ValueError("Chỉ chấp nhận DOI URL thuộc doi.org.")
        value = parsed.path.lstrip("/")
    value = value.rstrip(".,;)")
    if not _DOI_RE.fullmatch(value):
        raise ValueError("DOI không đúng định dạng.")
    return value


def verify_citation(citation: Dict[str, Any]) -> Dict[str, Any]:
    """Verify one DOI against Crossref through a fixed host; never fetch a caller-provided URL."""
    doi = _citation_doi(citation)
    response = httpx.get(
        f"https://api.crossref.org/works/{quote(doi, safe='/')}",
        headers={"User-Agent": "NoraBT/1.0 (citation verification)"},
        timeout=5.0,
    )
    response.raise_for_status()
    payload = response.json()
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("DOI"), str):
        raise ValueError("Crossref returned no canonical work metadata for this DOI.")
    canonical_doi = message["DOI"]
    if canonical_doi.casefold() != doi.casefold():
        raise ValueError("Crossref returned metadata for a different DOI.")
    title_values = message.get("title")
    title = title_values[0] if isinstance(title_values, list) and title_values and isinstance(title_values[0], str) else ""
    if not title:
        raise ValueError("Crossref returned DOI metadata without a title.")
    published = message.get("published-print") or message.get("published-online") or message.get("created")
    metadata = {
        "doi": canonical_doi,
        "title": title,
        "publisher": message.get("publisher") if isinstance(message.get("publisher"), str) else "",
        "published": published,
        "url": message.get("URL") if isinstance(message.get("URL"), str) else f"https://doi.org/{canonical_doi}",
        "authors": [
            {"given": author.get("given", ""), "family": author.get("family", "")}
            for author in message.get("author", [])
            if isinstance(author, dict)
        ],
    }
    metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        **metadata,
        "provider": "Crossref",
        "verified": True,
        "status": "verified",
        "retrieval_time": datetime.now(timezone.utc).isoformat(),
        "metadata_sha256": hashlib.sha256(metadata_json.encode("utf-8")).hexdigest(),
    }


def generate_ideas(prompt: str, opts: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Sinh 1-3 ý tưởng giao dịch {id, name, rationale, entry, exit, risk}."""
    opts = opts or {}
    sys_template = _read_prompt_template("2_ideas.md")

    user_prompt = (
        f"Prompt giao dịch:\n{prompt}\n\n"
        f"Tài sản: {opts.get('asset', 'BTC-USDT')}, Khung: {opts.get('timeframe', '1h')}, Hướng: {opts.get('side', 'both')}"
    )

    schema = {
        "ideas": [
            {
                "id": 1,
                "name": "Tên ý tưởng",
                "rationale": "Lý do tài chính",
                "economic_mechanism": "Cơ chế kinh tế học / market microstructure giải thích lợi thế",
                "falsifiable_conditions": "Điều kiện quan sát thực nghiệm khiến giả thuyết bị bác bỏ",
                "rejection_rules": "Quy tắc dừng nghiên cứu nếu Sharpe < 0.8 hoặc MDD > 20%",
                "citations": [
                    {
                        "provider": "Academic Literature / Market Microstructure",
                        "title": "Tên bài báo / nghiên cứu tham khảo",
                        "url": "https://doi.org/...",
                        "excerpt": "Trích đoạn luận điểm cốt lõi",
                    }
                ],
                "entry": "Điều kiện vào lệnh",
                "exit": "Điều kiện thoát lệnh",
                "risk": "Quản lý rủi ro",
            }
        ]
    }

    resp = llm.complete(
        messages=[{"role": "user", "content": user_prompt}],
        schema=schema,
        system=sys_template,
        temperature=0.3,
    )

    ideas: List[Dict[str, Any]] = []
    if isinstance(resp, dict) and "ideas" in resp and isinstance(resp["ideas"], list):
        ideas = resp["ideas"]
    elif isinstance(resp, list):
        ideas = resp
    else:
        # Fallback 1 idea mặc định với cơ chế kinh tế và điều kiện bác bỏ rõ ràng, citations rỗng (không bịa nguồn)
        ideas = [{
            "id": 1,
            "name": "Chiến lược theo prompt",
            "rationale": "Giao dịch theo tín hiệu nhận được từ yêu cầu nghiên cứu.",
            "economic_mechanism": "Khai thác độ trễ phản ứng dòng tiền và quán tính giá (Momentum / Underreaction anomaly).",
            "falsifiable_conditions": "Nếu phân phối lợi suất vượt trội (excess return) qua các chu kỳ biến động không khác biệt có ý nghĩa thống kê so với phân phối ngẫu nhiên (t-stat < 2.0).",
            "rejection_rules": "Bác bỏ nếu Sharpe test < 0.5, Max Drawdown vượt quá 25% hoặc tỷ lệ lệnh thắng < 40%.",
            "citations": [],
            "entry": prompt,
            "exit": "Đóng vị thế khi tín hiệu đảo chiều hoặc chạm dừng lỗ",
            "risk": "Đòn bẩy 1.0x, dừng lỗ 3%",
        }]

    # Đảm bảo các trường cần thiết và tối đa 3 ý tưởng
    out = []
    for i, it in enumerate(ideas[:3], start=1):
        default_mech = "Khai thác độ trễ phản ứng dòng tiền và quán tính xu hướng (Momentum / Underreaction anomaly)."
        default_falsify = "Bị bác bỏ nếu lợi suất vượt trội sau chi phí không đạt mức ý nghĩa thống kê (t-stat < 1.5)."
        default_rejection = "Bác bỏ nếu Sharpe test < 0.5 hoặc MDD vượt quá 25% trên tập OOS."
        out.append({
            "id": it.get("id", i),
            "name": it.get("name", f"Ý tưởng {i}"),
            "rationale": it.get("rationale", ""),
            "economic_mechanism": it.get("economic_mechanism") or default_mech,
            "falsifiable_conditions": it.get("falsifiable_conditions") or default_falsify,
            "rejection_rules": it.get("rejection_rules") or default_rejection,
            "citations": _sanitize_citations(it.get("citations")),
            "entry": it.get("entry", ""),
            "exit": it.get("exit", ""),
            "risk": it.get("risk", ""),
        })
    return out



# ══════════════════════════════════════════════════════════════════════════
# BƯỚC 3: To Formula
# ══════════════════════════════════════════════════════════════════════════

def _valid_indicator_names() -> Set[str]:
    cat = catalog()
    feats = cat.get("features", [])
    names = set()
    for f in feats:
        if isinstance(f, dict) and "name" in f:
            names.add(f["name"].lower())
    return names


def to_formula(idea: Dict[str, Any], opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Chuyển ý tưởng thành công thức chỉ báo (bắt buộc nằm trong catalog Nora)."""
    opts = opts or {}
    sys_template = _read_prompt_template("3_formula.md")
    valid_names = _valid_indicator_names()

    user_prompt = (
        f"Ý tưởng giao dịch được chọn:\n"
        f"Tên: {idea.get('name')}\n"
        f"Cơ sở tài chính: {idea.get('rationale')}\n"
        f"Điều kiện vào lệnh: {idea.get('entry')}\n"
        f"Điều kiện thoát lệnh: {idea.get('exit')}\n"
        f"Quản lý rủi ro: {idea.get('risk')}\n"
    )

    schema = {
        "indicators": [
            {"name": "ema", "params": {"timeperiod": 50}, "alias": "ema50"}
        ],
        "entry_rule": "close > ema50",
        "exit_rule": "close < ema50",
        "params": {"leverage": 1.0, "stop_loss_pct": 0.03},
        "description_vi": "Mô tả công thức tiếng Việt",
    }

    resp = llm.complete(
        messages=[{"role": "user", "content": user_prompt}],
        schema=schema,
        system=sys_template,
        temperature=0.2,
    )

    if not isinstance(resp, dict):
        resp = schema

    # Kiểm tra tính hợp lệ của các chỉ báo
    indicators = resp.get("indicators", []) if isinstance(resp.get("indicators"), list) else []
    invalid_found = []
    for ind in indicators:
        nm = str(ind.get("name", "") if isinstance(ind, dict) else ind).lower()
        if nm not in valid_names:
            invalid_found.append(nm)

    # Nếu có chỉ báo không hợp lệ: LLM sửa lại 1 lần
    if invalid_found:
        logger.warning("Phát hiện chỉ báo ngoài catalog: %s. Yêu cầu LLM sửa lại...", invalid_found)
        fix_prompt = (
            f"Các chỉ báo sau đây KHÔNG CÓ trong danh mục của hệ thống Nora: {invalid_found}.\n"
            f"Danh mục chỉ báo hợp lệ được phép dùng là: {sorted(list(valid_names))}.\n"
            f"Hãy thay thế bằng các chỉ báo tương đương hợp lệ trong danh mục và trả về JSON công thức đã chuẩn hoá."
        )
        resp_fixed = llm.complete(
            messages=[
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": json.dumps(resp, ensure_ascii=False)},
                {"role": "user", "content": fix_prompt},
            ],
            schema=schema,
            system=sys_template,
            temperature=0.1,
        )
        if isinstance(resp_fixed, dict):
            resp = resp_fixed

    # Lọc lần cuối: nếu vẫn còn chỉ báo không hợp lệ, loại bỏ
    clean_indicators = []
    final_indicators = resp.get("indicators", []) if isinstance(resp.get("indicators"), list) else []
    for ind in final_indicators:
        if isinstance(ind, dict):
            nm = str(ind.get("name", "")).lower()
            if nm in valid_names:
                clean_indicators.append(ind)
        elif isinstance(ind, str) and ind.lower() in valid_names:
            clean_indicators.append({"name": ind.lower(), "params": {}, "alias": ind.lower()})
    resp["indicators"] = clean_indicators if clean_indicators else [{"name": "ema", "params": {"timeperiod": 50}, "alias": "ema50"}]

    return resp


# ══════════════════════════════════════════════════════════════════════════
# BƯỚC 4: To Code
# ══════════════════════════════════════════════════════════════════════════

def _extract_python_code(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def to_code(formula: Dict[str, Any], opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Sinh code chiến lược Nora DSL, biên dịch qua compile_code + classify (sửa lỗi <= 2 lần)."""
    opts = opts or {}
    sys_template = _read_prompt_template("4_code.md")

    user_prompt = (
        f"Công thức chiến lược cần chuyển thành code Nora DSL:\n"
        f"{json.dumps(formula, ensure_ascii=False, indent=2)}\n\n"
        f"Tài sản: {opts.get('asset', 'BTC-USDT')}, Khung: {opts.get('timeframe', '1h')}"
    )

    resp = llm.complete(
        messages=[{"role": "user", "content": user_prompt}],
        system=sys_template,
        temperature=0.2,
    )

    code = _extract_python_code(str(resp))

    # Vòng lặp biên dịch và sửa lỗi (tối đa 2 lần sửa)
    compile_err = None
    classify_res = None

    for attempt in range(3):
        try:
            compile_code(code)
            classify_res = classify(code)
            compile_err = None
            break
        except (DslError, Exception) as e:
            compile_err = str(e)
            if attempt < 2:
                logger.info("Mã nguồn bị lỗi biên dịch: %s. Thử sửa lại lần %d...", compile_err, attempt + 1)
                fix_prompt = (
                    f"Mã nguồn trước đó bị lỗi biên dịch sau:\n{compile_err}\n\n"
                    f"Hãy sửa lại mã nguồn hoàn chỉnh theo đúng chuẩn Nora DSL kế thừa BaseStrategy, không import thư viện ngoài."
                )
                fix_resp = llm.complete(
                    messages=[
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": f"```python\n{code}\n```"},
                        {"role": "user", "content": fix_prompt},
                    ],
                    system=sys_template,
                    temperature=0.1,
                )
                code = _extract_python_code(str(fix_resp))
            else:
                break

    if compile_err is not None:
        return {
            "code": code,
            "compiled": False,
            "error": compile_err,
            "route": None,
        }

    return {
        "code": code,
        "compiled": True,
        "error": None,
        "route": classify_res,
    }


# BƯỚC 5 (Run Backtest: data_window / backtest_spec / run_backtest) nằm ở backend/routes/research.py — cần tầng data + jobs, cao hơn alpha.


# ══════════════════════════════════════════════════════════════════════════
# BƯỚC 6: Synthesis & Conclusions
# ══════════════════════════════════════════════════════════════════════════

def _extract_all_numbers(data: Any) -> Set[float]:
    """Thu thập toàn bộ số thực từ dict/list kết quả để phục vụ kiểm tra chống bịa số."""
    numbers: Set[float] = set()

    def _walk(obj):
        if isinstance(obj, (int, float)):
            if not math.isnan(obj) and not math.isinf(obj):
                v = float(obj)
                numbers.add(round(v, 4))
                numbers.add(round(v, 2))
                numbers.add(round(v, 1))
                # Dạng phần trăm nhân 100
                numbers.add(round(v * 100, 2))
                numbers.add(round(v * 100, 1))
                numbers.add(round(v * 100, 0))
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(data)
    # Thêm các số thứ tự vô hại cơ bản
    numbers.update({1.0, 2.0, 3.0, 4.0, 5.0})
    return numbers


def _match_number(num_val: float, valid_numbers: Set[float], tol: float = 0.02) -> bool:
    for v in valid_numbers:
        if abs(num_val - v) <= tol:
            return True
    return False


def _is_sentence_valid(sentence: str, valid_numbers: Set[float]) -> bool:
    """Kiểm tra xem câu có chứa số bịa không. Nếu có số không tồn tại trong kết quả -> False."""
    # Tìm tất cả số trong câu (ví dụ 12, 12.5, 12.5%, -3.2)
    tokens = re.findall(r"-?\b\d+(?:\.\d+)?%?", sentence)
    for tok in tokens:
        is_pct = tok.endswith("%")
        clean_num = tok.rstrip("%")
        try:
            val = float(clean_num)
        except ValueError:
            continue

        # Kiểm tra giá trị val (hoặc val/100 nếu là %)
        matched = _match_number(val, valid_numbers)
        if not matched and is_pct:
            matched = _match_number(val / 100.0, valid_numbers)
        if not matched:
            # Phát hiện số lạ không có trong metrics
            return False
    return True


def synthesize(
    result: Dict[str, Any],
    benchmark: Optional[Dict[str, Any]] = None,
    idea: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tổng hợp kết luận 5-8 dòng + nhãn đạt/không đạt do code tính toán.

    Mọi số trong kết luận phải có trong result (loại bỏ câu bịa số).
    """
    sys_template = _read_prompt_template("6_synthesis.md")

    metrics = result.get("metrics") or {}
    bench = benchmark or result.get("benchmark") or {}
    test_metrics = result.get("test_metrics") or metrics

    # 1. Tính toán nhãn đạt / không đạt hoàn toàn bằng code theo tiêu chí:
    # - Sharpe test > 0.5
    # - MDD < 25% (tức max_drawdown <= 0.25 hoặc 25)
    # - Số lệnh >= 20 (hoặc >= 10)
    # - Lợi nhuận vượt benchmark
    sharpe = float(test_metrics.get("sharpe_ratio", metrics.get("sharpe_ratio", 0.0)) or 0.0)
    mdd = abs(float(metrics.get("max_drawdown", 0.0) or 0.0))
    if mdd > 1.0:
        mdd_pct = mdd
    else:
        mdd_pct = mdd * 100.0
    trades = int(metrics.get("total_trades", 0) or 0)
    total_ret = float(metrics.get("total_return", 0.0) or 0.0)
    bench_ret = float(bench.get("total_return", 0.0) or 0.0)

    pass_sharpe = sharpe > 0.5
    pass_mdd = mdd_pct < 25.0
    pass_trades = trades >= 10
    pass_bench = total_ret > bench_ret

    passed = pass_sharpe and pass_mdd and pass_trades and pass_bench
    verdict = "đạt" if passed else "không đạt"

    criteria = {
        "sharpe_test": {"val": sharpe, "threshold": "> 0.5", "passed": pass_sharpe},
        "mdd_pct": {"val": mdd_pct, "threshold": "< 25%", "passed": pass_mdd},
        "trades": {"val": trades, "threshold": ">= 10", "passed": pass_trades},
        "beat_benchmark": {"val": total_ret - bench_ret, "threshold": "> 0", "passed": pass_bench},
    }

    # 2. Gọi LLM sinh văn bản nhận xét
    user_prompt = (
        f"KẾT QUẢ BACKTEST THẬT (NAUTILUS TRADER):\n"
        f"- Tổng lợi nhuận: {metrics.get('total_return', 0):.2%}\n"
        f"- Sharpe ratio: {metrics.get('sharpe_ratio', 0):.2f}\n"
        f"- Sortino ratio: {metrics.get('sortino_ratio', 0):.2f}\n"
        f"- Max Drawdown: {mdd_pct:.2f}%\n"
        f"- Win rate: {metrics.get('win_rate', 0):.2%}\n"
        f"- Tổng số lệnh: {trades}\n"
        f"- Profit Factor: {metrics.get('profit_factor', 0):.2f}\n"
        f"\nKẾT QUẢ BENCHMARK BUY & HOLD:\n"
        f"- Lợi nhuận Benchmark: {bench_ret:.2%}\n"
        f"- Sharpe Benchmark: {bench.get('sharpe_ratio', 0):.2f}\n"
        f"- Max Drawdown Benchmark: {bench.get('max_drawdown', 0):.2%}\n"
    )

    resp = llm.complete(
        messages=[{"role": "user", "content": user_prompt}],
        system=sys_template,
        temperature=0.2,
    )
    raw_summary = str(resp).strip()

    # 3. Kiểm tra số và lọc bỏ câu bịa số
    valid_numbers = _extract_all_numbers(result)
    valid_numbers.update(_extract_all_numbers(bench))

    # Tách các câu bằng dấu chấm, chấm than, chấm hỏi, xuống dòng
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?\n])\s+", raw_summary) if s.strip()]
    accepted_sentences = []
    removed_count = 0

    for sent in raw_sentences:
        if _is_sentence_valid(sent, valid_numbers):
            accepted_sentences.append(sent)
        else:
            logger.info("Loại bỏ câu chứa số không có trong kết quả: %s", sent)
            removed_count += 1

    if not accepted_sentences:
        accepted_sentences = [
            f"Chiến lược hoàn thành backtest với Sharpe {sharpe:.2f} và Max Drawdown {mdd_pct:.1f}%.",
            f"Tổng số giao dịch đạt {trades} lệnh, tỷ suất lợi nhuận đạt {total_ret:.2%}.",
            "Hệ thống kiểm soát rủi ro tuân thủ các quy tắc mô phỏng trên nền tảng NautilusTrader.",
        ]

    final_text = " ".join(accepted_sentences)

    return {
        "summary": final_text,
        "verdict": verdict,
        "passed": passed,
        "criteria": criteria,
        "removed_fabricated_sentences": removed_count,
    }
