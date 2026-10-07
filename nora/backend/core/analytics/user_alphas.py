"""Quản lý Alpha người dùng (C1 — lưu trữ, xác minh, checklist, catalog).

Kho lưu trữ: data/alphas/user/<alpha_id>.json (đường dẫn đặt MỘT chỗ: get_user_alphas_dir; thư mục job: batch.jobs_root())
alpha_id = sha1(program_hash + cấu hình chạy)[:12]
Bản ghi = code + program_hash + config + ảnh chụp đầy đủ kết quả (`result`) + `evidence`, đã xác minh trực tiếp từ job_id (chống giả mạo từ client).
Chạy ở /alpha/create và /education chỉ là TẠM THỜI (job_ttl dọn sau 24 h nếu không được lưu); chỉ lệnh Lưu mới ghi vào đây.
Vòng đời: SAVED -> CANDIDATE -> ARCHIVED
"""
import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.core.analytics.insights import BETA_DRIVEN_ID


def get_user_alphas_dir(base_dir: Optional[str] = None) -> str:
    if base_dir:
        return os.path.join(base_dir, "user")
    from backend.db.data_layout import DATA_HOME
    return os.path.join(DATA_HOME, "alphas", "user")


def generate_alpha_id(program_hash: str, config: Dict[str, Any]) -> str:
    """Tạo mã alpha_id bất biến: sha1(program_hash + canonical config)[:12]."""
    canon = {
        "profile": config.get("profile"),
        "symbols": sorted(config.get("symbols") or []),
        "start": config.get("start"),
        "end": config.get("end"),
        "train_ratio": config.get("train_ratio"),
        "initial_capital": config.get("initial_capital"),
        "timeframe": config.get("timeframe"),
        "position": config.get("position"),
    }
    raw = f"{program_hash}:{json.dumps(canon, sort_keys=True)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _num(v: Any) -> Optional[float]:
    """Số hữu hạn (kể cả 0) hoặc None — không bao giờ thay thiếu bằng 0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _first_num(block: Any, *keys: str) -> Optional[float]:
    for k in keys:
        n = _num((block or {}).get(k)) if isinstance(block, dict) else None
        if n is not None:
            return n
    return None


def _item(item_id: str, label: str, state: str, value: str, required: str) -> Dict[str, Any]:
    """state: pass | fail | missing. `passed` = True | False | None (thiếu dữ liệu: không đạt cũng không trượt)."""
    return {"id": item_id, "label": label, "state": state, "passed": {"pass": True, "fail": False}.get(state), "value": value, "required": required}


MISSING_VI = "không có dữ liệu"


def evaluate_checklist(result: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra 5 tiêu chí trước khi lưu (chỉ cảnh báo, không chặn). Nguồn DUY NHẤT của checklist: giao diện chỉ hiển thị.
    - >= 20 lệnh đóng
    - có giai đoạn test
    - Sharpe test > 0 (khối nora; không có thì khối xno)
    - MDD < 50% (khối nora: mdd_pct đã là %; khối xno: max_drawdown là phân số -> nhân 100)
    - không phải thuần beta (insight beta_driven)
    Đầu vào thiếu -> state "missing" (không đạt cũng không trượt), không bao giờ ngầm coi là 0."""
    metrics = result.get("metrics") or {}
    trades = result.get("trades")
    n_trades = len(trades) if isinstance(trades, list) else None

    has_test = bool(metrics.get("test"))
    test_blocks = metrics.get("test") or {}
    test_sharpe = _first_num(test_blocks.get("nora"), "sharpe")
    if test_sharpe is None:
        test_sharpe = _first_num(test_blocks.get("xno"), "sharpe")

    sim = metrics.get("simulate") or {}
    mdd_pct = _first_num(sim.get("nora"), "mdd_pct")
    if mdd_pct is not None:
        mdd_pct = abs(mdd_pct)
    else:
        f = _first_num(sim.get("xno"), "max_drawdown")
        mdd_pct = abs(f) * 100.0 if f is not None else None

    insights = result.get("insights")
    has_beta_driven = any(isinstance(i, dict) and i.get("id") == BETA_DRIVEN_ID for i in insights) if isinstance(insights, list) else None

    items = [
        _item("trades_ge_20", "Tối thiểu 20 lệnh giao dịch",
              "missing" if n_trades is None else ("pass" if n_trades >= 20 else "fail"),
              MISSING_VI if n_trades is None else f"{n_trades} lệnh", "≥ 20 lệnh"),
        _item("has_test_stage", "Có kiểm định ngoài mẫu (Out-Of-Sample)", "pass" if has_test else "fail", "Đã chạy" if has_test else "Chưa có", "Có giai đoạn test"),
        _item("test_sharpe_positive", "Sharpe ngoài mẫu dương (Sharpe Test > 0)",
              "missing" if test_sharpe is None else ("pass" if test_sharpe > 0.0 else "fail"),
              MISSING_VI if test_sharpe is None else f"{test_sharpe:.2f}", "> 0.0"),
        _item("mdd_under_50", "Mức sụt giảm tối đa dưới 50% (MDD < 50%)",
              "missing" if mdd_pct is None else ("pass" if mdd_pct < 50.0 else "fail"),
              MISSING_VI if mdd_pct is None else f"{mdd_pct:.1f}%", "< 50%"),
        _item("not_pure_beta", "Không phụ thuộc thuần túy vào thị trường (Beta-driven)",
              "missing" if has_beta_driven is None else ("fail" if has_beta_driven else "pass"),
              MISSING_VI if has_beta_driven is None else ("Cảnh báo beta" if has_beta_driven else "Độc lập"), f"Không kích hoạt {BETA_DRIVEN_ID}"),
    ]
    return {"all_passed": all(it["state"] == "pass" for it in items), "n_missing": sum(1 for it in items if it["state"] == "missing"), "items": items}


# ─── Lưu / đọc ──────────────────────────────────────────────────────────────

SNAPSHOT_REQUIRED = ("config", "metrics", "program_hash")


def _git_commit() -> Optional[str]:
    try:
        from backend.core.backtest.edu_precompute import git_commit
        return git_commit()
    except Exception:      # noqa: BLE001 — bằng chứng phụ, thiếu thì null
        return None


def build_evidence(result: Dict[str, Any], job_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    data = result.get("data") or {}
    return {"job_id": job_id, "program_hash": result.get("program_hash"), "data_source": data.get("source"), "data_sha256_1m": data.get("sha256_1m"),
            "git_commit": _git_commit(), "job_created": job.get("created"), "job_finished": job.get("finished"), "engine": "custom_run (PortfolioEngine)"}


def _finite(o: Any) -> Any:
    """NaN/Inf -> None (JSON hợp lệ cho trình duyệt)."""
    if isinstance(o, float):
        return o if o == o and o not in (float("inf"), float("-inf")) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


def _write_json(path: str, obj: Any) -> None:
    obj = _finite(obj)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, allow_nan=False)
    os.replace(tmp, path)


def save_user_alpha(job_id: str, code: str, name: str, note: str = "", source: str = "alpha-create",
                    base_dir: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """Xác thực và lưu trữ bản ghi Alpha người dùng (lần lưu DUY NHẤT; chạy ở /alpha/create và /education chỉ là tạm thời):
    - Đọc kết quả job thật từ máy chủ (job.status == 'done'), KHÔNG nhận kết quả từ client
    - Kiểm tra mã băm chương trình khớp với code gửi lên (chống giả mạo)
    - Ghi ảnh chụp ĐẦY ĐỦ kết quả (`result`) + `explain` + `evidence` nên bản ghi không còn phụ thuộc thư mục job
    - Trả về (record, action: 'created' | 'updated'); cùng code + cùng cấu hình -> cùng id -> cập nhật, không nhân bản
    """
    from backend.api.jobs import batch

    job = batch.status(job_id)
    if not job:
        raise ValueError(f"Không tìm thấy job_id {job_id}")
    if job.get("status") != "done":
        raise ValueError(f"Job {job_id} chưa hoàn tất (trạng thái: {job.get('status')})")

    result = job.get("result")
    if not result:
        raise ValueError(f"Job {job_id} không có dữ liệu result.json")
    lacking = [k for k in SNAPSHOT_REQUIRED if not result.get(k)]
    if lacking or not (result.get("metrics") or {}).get("simulate"):
        raise ValueError(f"Kết quả job {job_id} thiếu {lacking or ['metrics.simulate']}: không đủ để lưu")

    # Kiểm tra program_hash
    from backend.core.strategy.pydsl import compile_code
    prog = compile_code(code, register=False)
    if result.get("program_hash") != prog.code_hash:
        raise ValueError(f"Mã băm chương trình không khớp (kết quả job: {result.get('program_hash')}, code hiện tại: {prog.code_hash})")

    config = result.get("config", {})
    alpha_id = generate_alpha_id(prog.code_hash, config)
    checklist = evaluate_checklist(result)

    user_dir = get_user_alphas_dir(base_dir)
    os.makedirs(user_dir, exist_ok=True)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")

    action = "updated" if os.path.isfile(file_path) else "created"
    now_iso = datetime.now(timezone.utc).isoformat()

    old_record = {}
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                old_record = json.load(fh)
        except Exception:
            pass

    explain = None
    try:
        from backend.core.strategy.pydsl import explain_program
        explain = explain_program(prog, profile=config.get("profile", "xno"), position=config.get("position"))
    except Exception:      # noqa: BLE001 — giải thích là phần phụ; thiếu thì null
        explain = None

    snapshot = {k: v for k, v in result.items() if k not in ("checklist",)}
    snapshot["checklist"] = checklist
    record: Dict[str, Any] = {
        "id": alpha_id,
        "name": name.strip(),
        "note": (note or "").strip(),
        "source": source,
        "status": old_record.get("status", "SAVED"),
        "created_at": old_record.get("created_at", now_iso),
        "updated_at": now_iso,
        "code": code,
        "program_hash": prog.code_hash,
        "profile": config.get("profile", "xno"),
        "config": config,
        "metrics": result.get("metrics", {}),
        "checklist": checklist,
        "data_sha": (result.get("data") or {}).get("sha256_1m"),
        "job_id": job_id,
        "final_equity": result.get("final_equity"),
        "evidence": build_evidence(result, job_id, job),
        "explain": explain,
        "result": snapshot,       # ảnh chụp đầy đủ: metrics, yearly, series (stages + benchmark), trades, diagnostics, insights, by_symbol, warnings...
    }
    _write_json(file_path, record)
    return record, action


_HEAVY = ("result", "explain")


def _summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Bản ghi gọn cho danh sách: bỏ ảnh chụp kết quả + giải thích (lấy bằng GET /user/{id})."""
    out = {k: v for k, v in rec.items() if k not in _HEAVY}
    out["has_result"] = isinstance(rec.get("result"), dict)
    return out


def _sort_value(rec: Dict[str, Any], key: str) -> Optional[float]:
    m = rec.get("metrics") or {}
    if key == "sharpe":      # Sharpe test, khối nora (365)
        return _first_num((m.get("test") or {}).get("nora"), "sharpe")
    if key == "cagr":        # CAGR (365 ngày) toàn kỳ, khối nora — không phải ret_pct
        return _first_num((m.get("simulate") or {}).get("nora"), "cagr_pct")
    return None


def list_user_alphas(sort: Optional[str] = None, status: Optional[str] = None,
                     base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Liệt kê danh sách alpha người dùng (bản ghi gọn, không kèm ảnh chụp kết quả)."""
    user_dir = get_user_alphas_dir(base_dir)
    if not os.path.isdir(user_dir):
        return []

    items: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(user_dir)):
        if fname.endswith(".json") and not fname.endswith(".tmp"):
            path = os.path.join(user_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    rec = json.load(fh)
                    if isinstance(rec, dict) and rec.get("id"):
                        if status and rec.get("status") != status:
                            continue
                        items.append(_summary(rec))
            except Exception:
                continue

    # Sắp xếp (giá trị thiếu xếp cuối)
    if sort in ("sharpe", "cagr"):
        have = sorted((x for x in items if _sort_value(x, sort) is not None), key=lambda x: _sort_value(x, sort), reverse=True)
        items = have + [x for x in items if _sort_value(x, sort) is None]
    elif sort == "date":
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    else:
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    return items


def get_user_alpha(alpha_id: str, base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lấy chi tiết một alpha người dùng theo id."""
    user_dir = get_user_alphas_dir(base_dir)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def update_user_alpha_status(alpha_id: str, new_status: str, base_dir: Optional[str] = None) -> bool:
    """Cập nhật trạng thái alpha: SAVED -> CANDIDATE -> ARCHIVED."""
    rec = get_user_alpha(alpha_id, base_dir)
    if not rec:
        return False
    rec["status"] = new_status
    rec["updated_at"] = datetime.now(timezone.utc).isoformat()
    user_dir = get_user_alphas_dir(base_dir)
    file_path = os.path.join(user_dir, f"{alpha_id}.json")
    _write_json(file_path, rec)
    return True


# ─── Dọn job tạm của người dùng (TTL 24 h) ─────────────────────────────────

CUSTOM_JOB_KIND = "custom_backtest"
CUSTOM_JOB_TTL_S = 24 * 3600
_JOB_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")
_ACTIVE_STATES = ("running", "queued")


def referenced_job_ids(base_dir: Optional[str] = None) -> set:
    """Mã job mà một alpha người dùng đã lưu tham chiếu (job_id và evidence.job_id)."""
    ids = set()
    user_dir = get_user_alphas_dir(base_dir)
    if not os.path.isdir(user_dir):
        return ids
    for fname in os.listdir(user_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(user_dir, fname), encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            for j in (rec.get("job_id"), (rec.get("evidence") or {}).get("job_id")):
                if isinstance(j, str):
                    ids.add(j)
    return ids


def cleanup_unsaved_jobs(ttl_s: float = CUSTOM_JOB_TTL_S, now: Optional[float] = None, jobs_root: Optional[str] = None,
                         base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Xoá thư mục job `custom_backtest` (chạy tạm của /alpha/create và /education) cũ hơn `ttl_s` giây mà KHÔNG được alpha đã lưu tham chiếu.
    Không đụng job đang chạy/chờ, job loại khác (edu_precompute... — kết quả bền của nó nằm ở data/education/results), hay thư mục lạ.
    Tuổi = thời điểm kết thúc (hoặc tạo nếu chưa có). Trả {deleted: [id], kept_referenced, kept_recent, skipped}."""
    from backend.api.jobs import batch
    root = jobs_root or batch.jobs_root()
    now = time.time() if now is None else now
    out: Dict[str, Any] = {"deleted": [], "kept_referenced": 0, "kept_recent": 0, "skipped": 0}
    if not os.path.isdir(root):
        return out
    keep = referenced_job_ids(base_dir)
    real_root = os.path.realpath(root)
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not _JOB_ID_RE.match(name) or os.path.islink(path) or not os.path.isdir(path) or os.path.dirname(os.path.realpath(path)) != real_root:
            out["skipped"] += 1
            continue
        try:
            with open(os.path.join(path, "job.json"), encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            out["skipped"] += 1
            continue
        if meta.get("kind") != CUSTOM_JOB_KIND or meta.get("state") in _ACTIVE_STATES:
            out["skipped"] += 1
            continue
        if name in keep or meta.get("id") in keep:
            out["kept_referenced"] += 1
            continue
        t = meta.get("finished") or meta.get("created")
        if not isinstance(t, (int, float)) or now - float(t) < ttl_s:
            out["kept_recent"] += 1
            continue
        shutil.rmtree(path, ignore_errors=True)
        out["deleted"].append(name)
    return out


def cleanup_quietly() -> None:
    """Gọi từ khởi động API và sau mỗi lần chạy custom_backtest: lỗi dọn dẹp không bao giờ làm hỏng yêu cầu."""
    try:
        cleanup_unsaved_jobs()
    except Exception:      # noqa: BLE001
        pass
