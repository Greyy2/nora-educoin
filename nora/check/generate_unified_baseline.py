#!/usr/bin/env python3
"""Unified UX & Performance Baseline Generator for Nora COIN and Nora EDU.

This script executes empirical measurements against currently active local services:
1. API Latencies & Payload Sizes (5 monotonic samples per endpoint, min/avg/max/p50/p95).
2. Headless Chrome DOM rendering timings and structural element counts (Viewports: 1440x900, 1280x800).
3. Produces synchronized measured_api_baseline.json, measured_dom_baseline.json,
   and renders measured_ux_baseline.md from the EXACT measurement dictionaries.
"""

import json
import gzip
import time
import statistics
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PRODUCT_DIR = BASE_DIR / "nora"
sys.path.insert(0, str(PRODUCT_DIR / "edu"))

# 1. API Endpoints
API_TARGETS = [
    {"product": "COIN", "port": 18012, "endpoint": "/api/home/summary"},
    {"product": "COIN", "port": 18012, "endpoint": "/api/studio/market/regime"},
    {"product": "COIN", "port": 18012, "endpoint": "/api/health"},
    {"product": "COIN", "port": 18012, "endpoint": "/api/me"},
    {"product": "EDU", "port": 18022, "endpoint": "/api/home/summary"},
    {"product": "EDU", "port": 18022, "endpoint": "/api/edu/market"},
    {"product": "EDU", "port": 18022, "endpoint": "/api/studio/jobs"},
    {"product": "EDU", "port": 18022, "endpoint": "/api/health"},
    {"product": "EDU", "port": 18022, "endpoint": "/api/me"},
]

def calc_p95(samples):
    if len(samples) == 1:
        return samples[0]
    sorted_s = sorted(samples)
    # Linear interpolation percentile
    k = (len(sorted_s) - 1) * 0.95
    f = int(k)
    c = min(f + 1, len(sorted_s) - 1)
    d = k - f
    return round(sorted_s[f] + (sorted_s[c] - sorted_s[f]) * d, 2)

def measure_apis():
    print("=== Measuring API Endpoints ===")
    api_results = []
    for target in API_TARGETS:
        url = f"http://127.0.0.1:{target['port']}{target['endpoint']}"
        raw_samples = []
        payload_sizes = []
        statuses = []
        for i in range(5):
            t0 = time.perf_counter()
            req = urllib.request.Request(url, headers={"User-Agent": "Nora-Benchmark/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    status_code = resp.status
            except Exception as err:
                raise RuntimeError(f"API sample {i + 1}/5 failed for {url}: {err}") from err
            dt = round((time.perf_counter() - t0) * 1000, 2)
            assert status_code == 200, f"{url} sample {i + 1}/5 returned HTTP {status_code}"
            assert data, f"{url} sample {i + 1}/5 returned an empty payload"
            try:
                json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as err:
                raise AssertionError(f"{url} sample {i + 1}/5 did not return JSON") from err
            raw_samples.append(dt)
            payload_sizes.append(len(data))
            statuses.append(status_code)
            time.sleep(0.05)

        assert len(raw_samples) == 5

        avg_ms = round(statistics.mean(raw_samples), 2)
        min_ms = round(min(raw_samples), 2)
        max_ms = round(max(raw_samples), 2)
        p50_ms = round(statistics.median(raw_samples), 2)
        p95_ms = calc_p95(raw_samples)

        entry = {
            "product": target["product"],
            "endpoint": target["endpoint"],
            "status": statuses[-1],
            "sample_statuses": statuses,
            "payload_bytes": payload_sizes[-1],
            "sample_payload_bytes": payload_sizes,
            "sample_count": len(raw_samples),
            "raw_samples_ms": raw_samples,
            "avg_ms": avg_ms,
            "min_ms": min_ms,
            "max_ms": max_ms,
            "p50_ms": p50_ms,
            "p95_ms": p95_ms,
            "sla": "not established",
            "sla_status": "NOT_SET",
        }
        api_results.append(entry)
        print(f"[{target['product']}] {target['endpoint']}: {payload_sizes[-1]} B | avg={avg_ms}ms (p95={p95_ms}ms) | measured")
    return api_results

def measure_dom():
    print("\n=== Measuring Headless Chrome DOM Renders ===")
    from playwright.sync_api import sync_playwright

    from backend.users.store import sign_uid

    uid = os.environ.get("NORA_EDU_BASELINE_UID")
    if not uid:
        raise RuntimeError("Set NORA_EDU_BASELINE_UID to an existing EDU user before measuring authenticated Studio.")
    token = sign_uid(uid)
    coin_base_url = os.environ.get("NORA_COIN_BASELINE_URL", "http://coin.expsolution.io").rstrip("/")
    edu_base_url = os.environ.get("NORA_EDU_BASELINE_URL", "http://edu.expsolution.io").rstrip("/")

    viewports = [
        {"name": "desktop_large", "label": "Large Desktop", "width": 1440, "height": 900},
        {"name": "desktop_standard", "label": "Standard Desktop", "width": 1280, "height": 800},
    ]

    pages_to_test = [
        {"page": "COIN_HOME", "label": "COIN Home", "url": f"{coin_base_url}/", "auth": False},
        {"page": "COIN_LOGIN", "label": "COIN Login", "url": f"{coin_base_url}/login", "auth": False},
        {"page": "EDU_HOME", "label": "EDU Home", "url": f"{edu_base_url}/", "auth": False},
        {"page": "EDU_LOGIN", "label": "EDU Login", "url": f"{edu_base_url}/login", "auth": False},
        {"page": "EDU_STUDIO", "label": "EDU Studio (Authenticated)", "url": f"{edu_base_url}/edu/studio", "auth": True},
    ]

    dom_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=[
                "--host-rules=MAP coin.expsolution.io 127.0.0.1, MAP edu.expsolution.io 127.0.0.1",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        for pinfo in pages_to_test:
            for vp in viewports:
                context = browser.new_context(viewport={"width": vp["width"], "height": vp["height"]})
                if pinfo["auth"]:
                    context.add_cookies([
                        {
                            "name": "edu_session",
                            "value": token,
                            "url": edu_base_url,
                            "httpOnly": True,
                            "secure": False,
                            "sameSite": "Lax",
                        }
                    ])
                page = context.new_page()

                page_errors = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.goto(pinfo["url"], wait_until="load", timeout=15000)

                # Measured benchmark run
                t0 = time.perf_counter()
                page.goto(pinfo["url"], wait_until="networkidle", timeout=15000)
                render_time = round((time.perf_counter() - t0) * 1000, 2)

                content = page.content()
                dom_bytes = len(content.encode("utf-8"))

                divs = page.locator("div").count()
                buttons = page.locator("button").count()
                links = page.locator("a").count()
                inputs = page.locator("input, textarea, select").count()
                headings = page.locator("h1, h2, h3, h4, h5, h6").count()
                has_nav = page.locator("nav").count() > 0
                has_form = page.locator("form").count() > 0
                total_est = divs + buttons + links + inputs + headings
                title = page.title()

                # Assert product identity and the expected rendered view, not merely a nonempty title.
                assert title, f"Page title must not be empty for {pinfo['page']}"
                expected_product = "Nora EDU" if pinfo["page"].startswith("EDU") else "Nora COIN"
                assert expected_product in title, f"{pinfo['page']} has wrong product title: {title}"
                expected_host = urlparse(pinfo["url"]).hostname
                assert urlparse(page.url).hostname == expected_host, f"{pinfo['page']} served from unexpected host: {page.url}"
                if pinfo["auth"] and pinfo["page"] == "EDU_STUDIO":
                    assert "/studio" in page.url, f"EDU Studio unexpectedly redirected to {page.url}"
                    assert "Login" not in title, f"EDU Studio authenticated view redirected to login (title: {title})"
                    assert page.get_by_role("tablist", name="Bản nháp").count() == 1, "EDU Studio draft workspace did not render"
                    assert page.get_by_role("button", name="Chạy backtest").count() == 1, "EDU Studio backtest action did not render"
                    auth_response = page.evaluate(
                        "async () => { const response = await fetch('/api/me'); return {status: response.status, body: await response.json()}; }"
                    )
                    assert auth_response["status"] == 200
                    auth_user = auth_response["body"].get("user")
                    assert auth_user and auth_user.get("id") == uid, "EDU Studio session is not authenticated as the requested baseline user"
                    assert buttons >= 20, f"EDU Studio must render interactive controls, found only {buttons} buttons"
                    assert total_est >= 100, f"EDU Studio full workspace must have at least 100 DOM elements, found {total_est}"
                    assert inputs >= 1, f"EDU Studio must render input elements, found only {inputs} inputs"
                else:
                    assert page.locator("h1").count() > 0, f"{pinfo['page']} has no visible page heading"
                assert not page_errors, f"{pinfo['page']} raised browser runtime errors: {page_errors}"

                item = {
                    "page": pinfo["page"],
                    "page_label": pinfo["label"],
                    "url": pinfo["url"],
                    "title": title,
                    "viewport": vp["name"],
                    "viewport_label": vp["label"],
                    "width": vp["width"],
                    "height": vp["height"],
                    "render_time_ms": render_time,
                    "dom_size_bytes": dom_bytes,
                    "interactive_elements": {
                        "divs": divs,
                        "buttons": buttons,
                        "links": links,
                        "inputs": inputs,
                        "headings": headings,
                        "total_est": total_est,
                    },
                    "has_nav": has_nav,
                    "has_form": has_form,
                    "assertion_status": "PASS",
                    "page_errors": page_errors,
                }
                dom_results.append(item)
                print(f"[{pinfo['page']}] {vp['name']}: {render_time}ms | {dom_bytes} B | total_est={total_est}")
                context.close()

        browser.close()
    return dom_results

def measure_bundles():
    bundle_results = []
    for product, assets_dir in (
        ("COIN", PRODUCT_DIR / "coin/frontend/dist/assets"),
        ("EDU", PRODUCT_DIR / "edu/frontend/dist/assets"),
    ):
        if not assets_dir.is_dir():
            raise FileNotFoundError(f"Build assets are missing for {product}: {assets_dir}")
        assets = sorted(path for path in assets_dir.rglob("*") if path.is_file())
        if not assets:
            raise RuntimeError(f"No built assets found for {product}: {assets_dir}")
        for asset in assets:
            contents = asset.read_bytes()
            bundle_results.append(
                {
                    "product": product,
                    "asset": str(asset.relative_to(assets_dir)),
                    "bytes": len(contents),
                    "gzip_bytes": len(gzip.compress(contents, mtime=0)),
                }
            )
    return bundle_results


def generate_markdown(api_data, dom_data, bundle_data, generated_at):
    # API Table
    api_rows = []
    for a in api_data:
        p_bold = f"**{a['product']}**"
        status_str = f"`{a['status']} OK`"
        p_bytes_str = f"{a['payload_bytes']:,} B"
        min_str = f"{a['min_ms']:.2f} ms"
        avg_str = f"**{a['avg_ms']:.2f} ms**"
        max_str = f"{a['max_ms']:.2f} ms"
        p50_str = f"{a['p50_ms']:.2f} ms"
        p95_str = f"{a['p95_ms']:.2f} ms"
        api_rows.append(f"| {p_bold} | `{a['endpoint']}` | {status_str} | {a['sample_count']}/5 | {p_bytes_str} | {min_str} | {avg_str} | {max_str} | {p50_str} | {p95_str} |")
    api_table_md = "\n".join(api_rows)

    # DOM Table
    dom_rows = []
    for d in dom_data:
        page_bold = f"**{d['page_label']}**"
        res_str = f"{d['width']} × {d['height']}"
        render_str = f"{d['render_time_ms']:,.0f} ms"
        dom_bytes_str = f"{d['dom_size_bytes']:,} B"
        btns = d["interactive_elements"]["buttons"]
        inps = d["interactive_elements"]["inputs"]
        hdgs = d["interactive_elements"]["headings"]
        tot = d["interactive_elements"]["total_est"]
        title_str = f"`{d['title']}`"
        dom_rows.append(f"| {page_bold} | {d['viewport_label']} | {res_str} | {render_str} | {dom_bytes_str} | {btns} | {inps} | {hdgs} | {tot} | {title_str} | `{d['assertion_status']}` |")
    dom_table_md = "\n".join(dom_rows)
    bundle_rows = "\n".join(
        f"| **{entry['product']}** | `{entry['asset']}` | {entry['bytes']:,} B | {entry['gzip_bytes']:,} B |"
        for entry in bundle_data
    )

    content = f"""# Measured Product UX Baseline Report

**Status:** MEASURED; ROUTE ASSERTIONS PASSED; NO PERFORMANCE SLO APPROVED  
**Measured at:** {generated_at}  
**Applies to:** COIN Platform (`coin.expsolution.io`) and EDU Platform (`edu.expsolution.io`)  
**Parent Gate:** Phase 2 Foundation Entry Gate (`p0-measured-ux-baseline`)  
**Source of Truth:** Generated from `measured_api_baseline.json`, `measured_dom_baseline.json`, and `measured_bundle_baseline.json`.

---

## 1. Overview and Methodology

Empirical baselines were captured from the local COIN and EDU backend services, configured frontend URLs, and current Vite build artifacts. These are measurements, not performance acceptance thresholds. No SLA/SLO has been approved by this report.

Measurements encompass:
1. **API Response Latencies & Payload Sizes:** Five successful JSON responses per endpoint, recording every HTTP status, payload size, and latency sample.
2. **Frontend Asset Bundle Sizes:** Every current built asset, with raw and deterministic gzip byte counts.
3. **Headless Chrome Navigation & DOM:** Google Chrome and Playwright on standard (`1280x800`) and large (`1440x900`) desktop viewports. Route identity, page title, expected view, authenticated Studio session, and browser runtime errors are asserted before measurements are recorded. `NORA_COIN_BASELINE_URL` and `NORA_EDU_BASELINE_URL` select the frontend URLs; use the current Vite dev-server URLs to measure workspace source rather than a potentially stale deployed vhost.

> **Methodology & Percentile Calculation Note:**
> - Percentiles ($P_{50}, P_{95}$) are computed using linear interpolation across sample sets ($N=5$).
> - Five sequential samples are a small local baseline and do not establish production-tail latency or load stability.
> - Measurements and route assertions do not certify public deployment, broad browser compatibility, or a performance SLO.

---

## 2. API Endpoint Latency and Payload Baseline

Measured against running microservices: COIN (`127.0.0.1:18012`) and EDU (`127.0.0.1:18022`).

| Product | Endpoint | HTTP Status | Samples | Payload Size | Latency (Min) | Latency (Avg) | Latency (Max) | P50 | P95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
{api_table_md}

---

## 3. Frontend Bundle Distribution Baseline

Sizes are measured from every file in the current Vite `dist/assets` trees. Gzip bytes use deterministic gzip compression (`mtime=0`). No bundle-size budget is implied.

| Product | Asset | Bytes | Gzip bytes |
|---|---|---:|---:|
{bundle_rows}

---

## 4. Headless Chrome DOM Render Timings & Structure

Navigation duration is measured through `networkidle`; it is not FCP/LCP. API measurements always target the local backends on ports 18012/18022; DOM URLs are recorded per page and can target Vite dev servers or local vhosts.

| Page | Viewport | Resolution | Navigation Duration | DOM Size | Buttons | Inputs | Headings | Total Est. Nodes | Title | Assertions |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
{dom_table_md}

Authenticated EDU Studio requires a valid user from `NORA_EDU_BASELINE_UID` and verifies `/api/me` returns that user. The generator uses the backend session signing helper; it does not embed the signing secret.

---

## 5. Interpretation

These values are a reproducible local baseline only. Performance targets, acceptable regressions, and production SLOs must be agreed separately; this report does not infer arbitrary thresholds.
"""
    return content

def main():
    generated_at = datetime.now(timezone.utc).isoformat()
    api_data = measure_apis()
    dom_data = measure_dom()
    bundle_data = measure_bundles()
    for record in (*api_data, *dom_data, *bundle_data):
        record["generated_at"] = generated_at

    api_json_path = BASE_DIR / "nora/check/measured_api_baseline.json"
    dom_json_path = BASE_DIR / "nora/check/measured_dom_baseline.json"
    bundle_json_path = BASE_DIR / "nora/check/measured_bundle_baseline.json"
    ux_md_path = BASE_DIR / "nora/check/measured_ux_baseline.md"

    # Save JSON files
    with open(api_json_path, "w", encoding="utf-8") as f:
        json.dump(api_data, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {api_json_path}")

    with open(dom_json_path, "w", encoding="utf-8") as f:
        json.dump(dom_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {dom_json_path}")

    with open(bundle_json_path, "w", encoding="utf-8") as f:
        json.dump(bundle_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {bundle_json_path}")

    # Generate and save Markdown
    md_content = generate_markdown(api_data, dom_data, bundle_data, generated_at)
    with open(ux_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Saved {ux_md_path}")
    print("\n=== Baseline synchronization complete! ===")

if __name__ == "__main__":
    main()
