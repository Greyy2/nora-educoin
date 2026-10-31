#!/usr/bin/env python3
"""Run the owner-authorized fixture-alpha research batch serially on EDU."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EDU_DIR = ROOT / "nora/edu"
ALPHA_DIR = EDU_DIR / "data/alpha/user"
RAW_JOB_DIR = EDU_DIR / "data/cache/process/_mem"
BASELINE_PATH = ROOT / "nora/check/edu_alpha_baseline_results.json"
PROTOCOL_PATH = ROOT / "nora/check/edu_evolution_research_protocol.json"
AMENDMENT_PATH = ROOT / "nora/check/edu_fixture_alpha_research_amendment_20261028.json"
OWNER_METHOD_PATH = ROOT / "nora/check/edu_fixture_alpha_full_history_amendment_20261028.json"
CANDIDATE_PATH = ROOT / "nora/check/candidates/edu_fixture_alpha_candidates_v2_20261028.json"
COMPILE_PATH = ROOT / "nora/check/candidates/edu_fixture_alpha_compile_results_v2_20261028.json"
DEFAULT_OUTPUT = ROOT / "nora/check/candidates/edu_fixture_alpha_wfa_results_v2_20261028.json"
API = "http://127.0.0.1:18022"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def wait_for_job(job_id: str, timeout_s: int) -> dict[str, Any]:
    path = RAW_JOB_DIR / f"{job_id}.json"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                time.sleep(2)
                continue
            if data.get("state") in {"done", "failed", "cancelled"}:
                return data
        time.sleep(2)
    raise TimeoutError(f"EDU job {job_id} did not reach a terminal state in {timeout_s}s")


def matching_cached_jobs(task: dict[str, Any], code: str, config: dict[str, Any]) -> list[str]:
    matches = []
    for path in RAW_JOB_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        params = data.get("params") or {}
        if (
            params.get("code") == code
            and params.get("symbols") == [config["symbol"]]
            and params.get("start") == task["fold"]["train_start"]
            and params.get("end") == task["fold"]["test_end"]
            and params.get("test_start") == task["fold"]["test_start"]
            and params.get("run_frame") == config["timeframe"]
        ):
            matches.append(path.stem)
    return matches


def terminal_receipt(
    *,
    task: dict[str, Any],
    job_id: str,
    job: dict[str, Any],
    request: dict[str, Any],
    code_hash: str,
) -> dict[str, Any]:
    result = job.get("result") or {}
    metrics = result.get("metrics") or {}
    trades = result.get("test_trades") or []
    full_trades = result.get("trades") or []
    return {
        "run_key": task["run_key"],
        "kind": task["kind"],
        "candidate_id": task.get("candidate_id"),
        "parent_ids": task.get("parent_ids", []),
        "fold_index": task["fold_index"],
        "job_id": job_id,
        "status": job.get("state"),
        "exit_code": job.get("exit_code"),
        "source_sha256": code_hash,
        "request": request,
        "result_config": result.get("config"),
        "program_hash": result.get("program_hash"),
        "data": result.get("data"),
        "provenance": result.get("provenance"),
        "metrics": metrics,
        "test_trade_count": len(trades),
        "test_trades": trades,
        "trade_ledger": full_trades,
        "equity_series": result.get("series"),
        "positions_open": result.get("positions_open"),
        "diagnostics": result.get("diagnostics"),
        "warnings": result.get("warnings"),
        "engine_meta": result.get("meta"),
        "resource_progress": {
            "peak_rss_mb": (job.get("progress") or {}).get("peak_rss_mb"),
            "elapsed_s": (job.get("progress") or {}).get("elapsed_s"),
            "log_tail": job.get("log_tail", [])[-12:],
        },
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def request_job(
    task: dict[str, Any],
    code: str,
    config: dict[str, Any],
    timeout_s: int,
    on_submitted: Any,
) -> dict[str, Any]:
    request = {
        "code": code,
        "symbols": [config["symbol"]],
        "start": task["fold"]["train_start"],
        "end": task["fold"]["test_end"],
        "test_start": task["fold"]["test_start"],
        "train_ratio": 0.7,
        "initial_capital": 10000,
        "run_frame": config["timeframe"],
    }
    data = json.dumps(request).encode()
    req = urllib.request.Request(
        f"{API}/api/studio/custom/backtest",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        submitted = json.loads(response.read())
    job_id = submitted.get("job_id")
    if not job_id:
        raise RuntimeError(f"EDU submit did not return job_id: {submitted!r}")
    task["active_job_id"] = job_id
    task["request"] = {key: value for key, value in request.items() if key != "code"}
    task["effective_code_sha256"] = sha256(code.encode())
    task["submitted_at"] = datetime.now(timezone.utc).isoformat()
    on_submitted(task)
    job = wait_for_job(job_id, timeout_s)
    receipt = terminal_receipt(
        task=task,
        job_id=job_id,
        job=job,
        request=task["request"],
        code_hash=task["effective_code_sha256"],
    )
    if receipt["status"] != "done" or receipt["exit_code"] != 0:
        raise RuntimeError(f"EDU job {job_id} failed: {receipt['status']} exit={receipt['exit_code']}")
    peak = receipt["resource_progress"]["peak_rss_mb"]
    if peak is not None and peak > 2048:
        raise RuntimeError(f"EDU job {job_id} exceeded the 2 GB policy cap: {peak} MB")
    return receipt


def parent_with_config_timeframe(source: str, timeframe: str) -> str:
    match = re.search(r"(?m)^(class\s+\w+\s*\([^)]*\)\s*:\s*)$", source)
    if not match:
        raise ValueError("Parent source does not have the expected class declaration")
    if re.search(r"(?m)^\s*timeframe\s*=", source):
        return source
    return source[: match.end()] + f'\n    timeframe = "{timeframe}"' + source[match.end() :]


def validate_compile_receipts(candidates: list[dict[str, Any]], compile_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    compiled = {
        row["candidate_id"]: row
        for row in compile_doc.get("results", [])
        if row.get("ok") is True
    }
    if len(candidates) != 27 or len(compiled) != 27:
        raise ValueError("Expected 27 candidates and 27 production compile passes")
    for candidate in candidates:
        receipt = compiled.get(candidate["candidate_id"])
        if (
            candidate.get("dsl_compile_status") != "PASS"
            or receipt is None
            or receipt.get("program_hash") != candidate.get("program_hash")
        ):
            raise ValueError(
                f"Candidate is not bound to a matching compile receipt: {candidate['candidate_id']}"
            )
    return compiled


def main() -> int:
    if OWNER_METHOD_PATH.exists():
        owner_method = json.loads(OWNER_METHOD_PATH.read_text(encoding="utf-8"))
        if owner_method.get("evaluation", {}).get("wfa") is False:
            raise RuntimeError(
                "WFA was declined for this batch; use run_edu_fixture_alpha_full_history.py instead"
            )
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="Run at most N new jobs; 0 means the full batch.")
    parser.add_argument("--job-timeout", type=int, default=900)
    args = parser.parse_args()

    amendment = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    if amendment.get("status") != "OWNER_AUTHORIZED_RESEARCH_SCOPE":
        raise ValueError("Missing owner-authorized scope amendment")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if protocol.get("protocol_sha256") != amendment["basis"]["prior_protocol_sha256"]:
        raise ValueError("The frozen research protocol changed; stop and review the amendment")
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    blocked_ids = set(baseline["blocked_records"])
    candidates_doc = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    compile_doc = json.loads(COMPILE_PATH.read_text(encoding="utf-8"))
    candidates = candidates_doc.get("candidates", [])
    validate_compile_receipts(candidates, compile_doc)
    if {row["parent_id"] for row in candidates} != blocked_ids:
        raise ValueError("Candidate IDs do not exactly cover the blocked alpha set")

    folds = protocol["wfa_specification"]["folds"]
    alpha_records = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in ALPHA_DIR.glob("*.json")
        if p.stem in blocked_ids
    }
    if len(alpha_records) != 27:
        raise ValueError(f"Expected 27 source records, found {len(alpha_records)}")

    parent_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for alpha_id, parent in alpha_records.items():
        config = parent.get("config") or {}
        symbol = str((config.get("symbols") or [""])[0]).split("-")[0]
        timeframe = str(config.get("timeframe") or "24h")
        source_hash = sha256(str(parent.get("code", "")).encode())
        key = (source_hash, symbol, timeframe)
        group = parent_groups.setdefault(
            key,
            {
                "key": f"parent-{source_hash[:12]}-{symbol}-{timeframe}",
                "source": parent.get("code", ""),
                "source_sha256": source_hash,
                "symbol": symbol,
                "timeframe": timeframe,
                "parent_ids": [],
            },
        )
        group["parent_ids"].append(alpha_id)
    if len(parent_groups) != 4:
        raise ValueError(f"Expected four distinct fixture parent templates, found {len(parent_groups)}")

    tasks: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    for group in sorted(parent_groups.values(), key=lambda item: item["key"]):
        config = {"symbol": group["symbol"], "timeframe": group["timeframe"]}
        effective = parent_with_config_timeframe(group["source"], group["timeframe"])
        for index, fold in enumerate(folds, 1):
            tasks.append(
                (
                    {
                        "run_key": f"{group['key']}:fold{index}",
                        "kind": "parent_template_control",
                        "parent_ids": sorted(group["parent_ids"]),
                        "parent_source_sha256": group["source_sha256"],
                        "fold_index": index,
                        "fold": fold,
                    },
                    effective,
                    config,
                )
            )
    for candidate in sorted(candidates, key=lambda item: item["parent_id"]):
        if candidate["parent_id"] not in blocked_ids:
            raise ValueError(f"Candidate parent is not blocked: {candidate['parent_id']}")
        source_config = candidate.get("config") or {}
        symbol = str((source_config.get("symbols") or [""])[0]).split("-")[0]
        config = {"symbol": symbol, "timeframe": candidate["timeframe"]}
        for index, fold in enumerate(folds, 1):
            tasks.append(
                (
                    {
                        "run_key": f"{candidate['candidate_id']}:fold{index}",
                        "kind": "candidate",
                        "candidate_id": candidate["candidate_id"],
                        "parent_ids": [candidate["parent_id"]],
                        "parent_source_sha256": candidate["parent_source_sha256"],
                        "fold_index": index,
                        "fold": fold,
                    },
                    candidate["code"],
                    config,
                )
            )

    if args.output.exists():
        state = json.loads(args.output.read_text(encoding="utf-8"))
        if state.get("amendment_id") != amendment["amendment_id"]:
            raise ValueError("Existing output belongs to a different research amendment")
    else:
        state = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING",
            "amendment_id": amendment["amendment_id"],
            "protocol_sha256": protocol["protocol_sha256"],
            "api": API,
            "execution_policy": "Serial jobs only; 2 GB per job maximum.",
            "folds": folds,
            "expected_parent_template_count": 4,
            "expected_candidate_count": 27,
            "results": {},
            "active_task": None,
        }

    completed_new = 0
    active = state.get("active_task")
    if active:
        matches = [(task, code, config) for task, code, config in tasks if task["run_key"] == active["run_key"]]
        if len(matches) != 1:
            raise RuntimeError(f"Cannot resolve interrupted task {active.get('run_key')}")
        task, code, _config = matches[0]
        if sha256(code.encode()) != active.get("effective_code_sha256", active.get("code_sha256")):
            raise RuntimeError("Source changed while reconciling the interrupted task")
        job_id = active.get("active_job_id")
        if not job_id:
            cached = matching_cached_jobs(active, code, _config)
            if len(cached) > 1:
                raise RuntimeError(f"Multiple cached jobs match interrupted task {active['run_key']}: {cached}")
            if not cached:
                state.setdefault("pre_submit_reconciliations", []).append(
                    {
                        "run_key": active["run_key"],
                        "outcome": "NO_JOB_FOUND_BEFORE_SUBMISSION",
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                state["active_task"] = None
                write_atomic(args.output, state)
                active = None
            else:
                job_id = cached[0]
                active["active_job_id"] = job_id
                state["active_task"] = active
                write_atomic(args.output, state)
        if active is not None:
            job = wait_for_job(job_id, args.job_timeout)
        else:
            job = None
        if active is None:
            pass
        else:
            receipt = terminal_receipt(
                task=active,
                job_id=job_id,
                job=job,
                request=active["request"],
                code_hash=active["effective_code_sha256"],
            )
            if receipt["status"] != "done" or receipt["exit_code"] != 0:
                raise RuntimeError(
                    f"Interrupted EDU job {job_id} failed: {receipt['status']} exit={receipt['exit_code']}"
                )
            state["results"][active["run_key"]] = receipt
            state["active_task"] = None
            write_atomic(args.output, state)

    for task, code, config in tasks:
        if task["run_key"] in state["results"]:
            continue
        if args.limit and completed_new >= args.limit:
            break
        state["active_task"] = {
            **task,
            "code_sha256": sha256(code.encode()),
            "config": config,
        }
        write_atomic(args.output, state)

        def persist_submission(submitted_task: dict[str, Any]) -> None:
            state["active_task"] = {
                **submitted_task,
                "fold": task["fold"],
                "config": config,
            }
            write_atomic(args.output, state)

        receipt = request_job(task, code, config, args.job_timeout, persist_submission)
        state["results"][task["run_key"]] = receipt
        state["active_task"] = None
        completed_new += 1
        write_atomic(args.output, state)
        metric = (receipt.get("metrics") or {}).get("test") or {}
        print(
            f"{task['run_key']} done; test_return={metric.get('ret_pct')}% "
            f"trades={metric.get('trades')} peak_rss={receipt['resource_progress']['peak_rss_mb']} MB",
            flush=True,
        )

    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["completed_job_count"] = len(state["results"])
    state["expected_job_count"] = len(tasks)
    state["status"] = "COMPLETE" if len(state["results"]) == len(tasks) else "PARTIAL"
    state["active_task"] = None
    write_atomic(args.output, state)
    print(
        f"{state['status']}: {state['completed_job_count']}/{state['expected_job_count']} jobs "
        f"recorded at {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
