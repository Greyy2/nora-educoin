#!/usr/bin/env python3
"""Run one descriptive full-history backtest per v2 candidate and parent template."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EDU_DIR = ROOT / "nora/edu"
ALPHA_DIR = EDU_DIR / "data/alpha/user"
RAW_JOB_DIR = EDU_DIR / "data/cache/process/_mem"
BASELINE_PATH = ROOT / "nora/check/edu_alpha_baseline_results.json"
AMENDMENT_PATH = ROOT / "nora/check/edu_fixture_alpha_full_history_amendment_20261028.json"
CANDIDATE_PATH = ROOT / "nora/check/candidates/edu_fixture_alpha_candidates_v2_20261028.json"
COMPILE_PATH = ROOT / "nora/check/candidates/edu_fixture_alpha_compile_results_v2_20261028.json"
PARENT_COMPILE_PATH = ROOT / "nora/check/candidates/edu_fixture_alpha_parent_compile_results_20261028.json"
DEFAULT_OUTPUT = ROOT / "nora/check/candidates/edu_fixture_alpha_full_history_results_v2_20261028.json"
API = "http://127.0.0.1:18022"
START = "2023-10-06"
END = "2026-10-03"


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


def effective_parent_code(source: str, timeframe: str) -> str:
    match = re.search(r"(?m)^(class\s+\w+\s*\([^)]*\)\s*:\s*)$", source)
    if not match:
        raise ValueError("Parent source does not have the expected class declaration")
    if re.search(r"(?m)^\s*timeframe\s*=", source):
        return source
    return source[: match.end()] + f'\n    timeframe = "{timeframe}"' + source[match.end() :]


def validate_candidate_compiles(candidates: list[dict[str, Any]], compile_doc: dict[str, Any]) -> None:
    receipts = {
        row["candidate_id"]: row
        for row in compile_doc.get("results", [])
        if row.get("ok") is True
    }
    if len(candidates) != 27 or len(receipts) != 27:
        raise ValueError("Need 27 candidates and 27 production compile passes before backtesting")
    for candidate in candidates:
        receipt = receipts.get(candidate["candidate_id"])
        if (
            candidate.get("dsl_compile_status") != "PASS"
            or receipt is None
            or receipt.get("program_hash") != candidate.get("program_hash")
        ):
            raise ValueError(f"Candidate has no matching v2 compile receipt: {candidate['candidate_id']}")


def validate_parent_compiles(groups: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, str]:
    doc = json.loads(PARENT_COMPILE_PATH.read_text(encoding="utf-8"))
    receipts = doc.get("results", [])
    if len(receipts) != 4 or sum(row.get("ok") is True for row in receipts) != 4:
        raise ValueError("Need four production-compiled parent template controls")
    hashes = {}
    for group in groups.values():
        code = effective_parent_code(group["source"], group["timeframe"])
        expected_code_hash = sha256(code.encode())
        matches = [
            row for row in receipts
            if row.get("source_sha256") == group["source_sha256"]
            and row.get("symbol") == group["symbol"]
            and row.get("timeframe") == group["timeframe"]
            and row.get("effective_parent_code_sha256") == expected_code_hash
            and row.get("ok") is True
        ]
        if len(matches) != 1:
            raise ValueError(f"Missing matching compile receipt for parent {group['key']}")
        hashes[group["key"]] = matches[0]["program_hash"]
    return hashes


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
            and params.get("start") == START
            and params.get("end") == END
            and not params.get("test_start")
            and params.get("run_frame") == config["timeframe"]
            and params.get("train_ratio") == 0.7
            and params.get("initial_capital") == 10000
            and not params.get("position")
        ):
            matches.append(path.stem)
    return matches


def make_receipt(task: dict[str, Any], code: str, job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") or {}
    return {
        "run_key": task["run_key"],
        "kind": task["kind"],
        "candidate_id": task.get("candidate_id"),
        "parent_ids": task.get("parent_ids", []),
        "parent_source_sha256": task.get("parent_source_sha256"),
        "request": task.get("request"),
        "source_sha256": sha256(code.encode()),
        "job_id": job_id,
        "status": job.get("state"),
        "exit_code": job.get("exit_code"),
        "result_config": result.get("config"),
        "program_hash": result.get("program_hash"),
        "data": result.get("data"),
        "provenance": result.get("provenance"),
        "metrics": result.get("metrics"),
        "full_history_metrics": (result.get("metrics") or {}).get("simulate"),
        "trades": result.get("trades") or [],
        "trade_count": len(result.get("trades") or []),
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


def backtest_request(code: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "symbols": [config["symbol"]],
        "start": START,
        "end": END,
        "train_ratio": 0.7,
        "initial_capital": 10000,
        "run_frame": config["timeframe"],
    }


def run_task(
    task: dict[str, Any],
    code: str,
    config: dict[str, Any],
    timeout_s: int,
    on_submitted: Any,
) -> dict[str, Any]:
    request = backtest_request(code, config)
    req = urllib.request.Request(
        f"{API}/api/studio/custom/backtest",
        data=json.dumps(request).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        submitted = json.loads(response.read())
    job_id = submitted.get("job_id")
    if not job_id:
        raise RuntimeError(f"EDU submit did not return job_id: {submitted!r}")
    task["active_job_id"] = job_id
    task["effective_code_sha256"] = sha256(code.encode())
    task["request"] = {key: value for key, value in request.items() if key != "code"}
    task["submitted_at"] = datetime.now(timezone.utc).isoformat()
    on_submitted(task)
    job = wait_for_job(job_id, timeout_s)
    receipt = make_receipt(task, code, job_id, job)
    if receipt["status"] != "done" or receipt["exit_code"] != 0:
        raise RuntimeError(f"EDU job {job_id} failed: {receipt['status']} exit={receipt['exit_code']}")
    expected_program_hash = task.get("program_hash")
    if expected_program_hash and receipt["program_hash"] != expected_program_hash:
        raise RuntimeError(f"EDU job {job_id} program hash did not match its compiled source")
    peak = receipt["resource_progress"]["peak_rss_mb"]
    if peak is not None and peak > 2048:
        raise RuntimeError(f"EDU job {job_id} exceeded the 2 GB policy cap: {peak} MB")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="Run at most N new jobs; 0 means the full batch.")
    parser.add_argument("--job-timeout", type=int, default=1800)
    args = parser.parse_args()

    novelty = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8")).get("novelty_gate", {})
    if novelty.get("status") != "PASS" or novelty.get("backtest_allowed") is not True:
        raise ValueError(
            "Research-v2 failed the owner-required all-alpha novelty gate; "
            "do not run this superseded 31-job candidate batch."
        )

    amendment = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    if amendment.get("status") != "OWNER_AUTHORIZED_SINGLE_FULL_HISTORY_RESEARCH":
        raise ValueError("Missing owner-authorized single-run research scope")
    if amendment.get("evaluation", {}).get("wfa") is not False:
        raise ValueError("This runner only supports the approved non-WFA evaluation")
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    blocked_ids = set(baseline["blocked_records"])
    candidates_doc = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    candidates = candidates_doc.get("candidates", [])
    validate_candidate_compiles(
        candidates,
        json.loads(COMPILE_PATH.read_text(encoding="utf-8")),
    )
    if {row["parent_id"] for row in candidates} != blocked_ids:
        raise ValueError("Candidate IDs do not exactly cover the blocked alpha set")

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
        raise ValueError(f"Expected four distinct parent templates, found {len(parent_groups)}")
    parent_program_hashes = validate_parent_compiles(parent_groups)

    tasks: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    for group in sorted(parent_groups.values(), key=lambda item: item["key"]):
        task = {
            "run_key": f"{group['key']}:full-history",
            "kind": "parent_template_control",
            "parent_ids": sorted(group["parent_ids"]),
            "parent_source_sha256": group["source_sha256"],
            "program_hash": parent_program_hashes[group["key"]],
        }
        config = {"symbol": group["symbol"], "timeframe": group["timeframe"]}
        tasks.append((task, effective_parent_code(group["source"], group["timeframe"]), config))
    for candidate in sorted(candidates, key=lambda item: item["parent_id"]):
        source_config = candidate.get("config") or {}
        config = {
            "symbol": str((source_config.get("symbols") or [""])[0]).split("-")[0],
            "timeframe": candidate["timeframe"],
        }
        task = {
            "run_key": f"{candidate['candidate_id']}:full-history",
            "kind": "candidate",
            "candidate_id": candidate["candidate_id"],
            "parent_ids": [candidate["parent_id"]],
            "parent_source_sha256": candidate["parent_source_sha256"],
            "program_hash": candidate["program_hash"],
        }
        tasks.append((task, candidate["code"], config))

    if args.output.exists():
        state = json.loads(args.output.read_text(encoding="utf-8"))
        if state.get("amendment_id") != amendment["amendment_id"]:
            raise ValueError("Existing output belongs to a different research amendment")
        if state.get("evaluation_method") != "single_full_history_run":
            raise ValueError("Existing output was not created by this non-WFA runner")
    else:
        state = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING",
            "amendment_id": amendment["amendment_id"],
            "evaluation_method": "single_full_history_run",
            "window": {"start": START, "end": END},
            "api": API,
            "execution_policy": "Serial jobs only; 2 GB per job maximum.",
            "wfa_used": False,
            "parameter_tuning_used": False,
            "expected_candidate_count": 27,
            "expected_parent_template_count": 4,
            "expected_job_count": len(tasks),
            "results": {},
            "active_task": None,
        }

    tasks_by_key = {task["run_key"]: (task, code) for task, code, _ in tasks}
    for run_key, receipt in state.get("results", {}).items():
        match = tasks_by_key.get(run_key)
        if match is None or receipt.get("source_sha256") != sha256(match[1].encode()):
            raise RuntimeError(f"Saved result is stale or outside this batch: {run_key}")

    completed_new = 0
    active = state.get("active_task")
    if active:
        matches = [(task, code, config) for task, code, config in tasks if task["run_key"] == active["run_key"]]
        if len(matches) != 1:
            raise RuntimeError(f"Cannot resolve interrupted task {active.get('run_key')}")
        task, code, config = matches[0]
        code_hash = sha256(code.encode())
        if code_hash != active.get("effective_code_sha256", active.get("code_sha256")):
            raise RuntimeError("Source changed while reconciling the interrupted task")
        job_id = active.get("active_job_id")
        if not job_id:
            cached = matching_cached_jobs(active, code, config)
            if len(cached) > 1:
                raise RuntimeError(f"Multiple cached jobs match interrupted task {active['run_key']}: {cached}")
            if cached:
                job_id = cached[0]
            else:
                state.setdefault("pre_submit_reconciliations", []).append({
                    "run_key": active["run_key"],
                    "outcome": "NO_JOB_FOUND_BEFORE_SUBMISSION",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                })
                state["active_task"] = None
                write_atomic(args.output, state)
                active = None
        if active is not None:
            job = wait_for_job(job_id, args.job_timeout)
            receipt = make_receipt(active, code, job_id, job)
            if receipt["status"] != "done" or receipt["exit_code"] != 0:
                raise RuntimeError(f"Interrupted EDU job {job_id} failed")
            if receipt["program_hash"] != active.get("program_hash"):
                raise RuntimeError(f"Interrupted EDU job {job_id} program hash did not match compiled source")
            peak = receipt["resource_progress"]["peak_rss_mb"]
            if peak is not None and peak > 2048:
                raise RuntimeError(f"Interrupted EDU job {job_id} exceeded the 2 GB policy cap: {peak} MB")
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
                "config": config,
            }
            write_atomic(args.output, state)

        receipt = run_task(task, code, config, args.job_timeout, persist_submission)
        state["results"][task["run_key"]] = receipt
        state["active_task"] = None
        completed_new += 1
        write_atomic(args.output, state)
        metric = receipt.get("full_history_metrics") or {}
        print(
            f"{task['run_key']} done; full_return={metric.get('ret_pct')}% "
            f"trades={metric.get('trades')} peak_rss={receipt['resource_progress']['peak_rss_mb']} MB",
            flush=True,
        )

    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["completed_job_count"] = len(state["results"])
    state["status"] = "COMPLETE" if len(state["results"]) == len(tasks) else "PARTIAL"
    state["active_task"] = None
    write_atomic(args.output, state)
    print(f"{state['status']}: {len(state['results'])}/{len(tasks)} full-history runs", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
