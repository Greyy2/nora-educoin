# Measured Product UX Baseline Report

**Status:** MEASURED; ROUTE ASSERTIONS PASSED; NO PERFORMANCE SLO APPROVED  
**Measured at:** 2026-10-24T16:57:33.686961+00:00  
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
> - Percentiles ($P_50, P_95$) are computed using linear interpolation across sample sets ($N=5$).
> - Five sequential samples are a small local baseline and do not establish production-tail latency or load stability.
> - Measurements and route assertions do not certify public deployment, broad browser compatibility, or a performance SLO.

---

## 2. API Endpoint Latency and Payload Baseline

Measured against running microservices: COIN (`127.0.0.1:18012`) and EDU (`127.0.0.1:18022`).

| Product | Endpoint | HTTP Status | Samples | Payload Size | Latency (Min) | Latency (Avg) | Latency (Max) | P50 | P95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **COIN** | `/api/home/summary` | `200 OK` | 5/5 | 136 B | 1.44 ms | **75.73 ms** | 372.38 ms | 1.61 ms | 298.25 ms |
| **COIN** | `/api/studio/market/regime` | `200 OK` | 5/5 | 9,419 B | 3.89 ms | **4.18 ms** | 4.69 ms | 4.02 ms | 4.63 ms |
| **COIN** | `/api/health` | `200 OK` | 5/5 | 84 B | 1.60 ms | **1.65 ms** | 1.71 ms | 1.65 ms | 1.70 ms |
| **COIN** | `/api/me` | `200 OK` | 5/5 | 13 B | 1.47 ms | **1.67 ms** | 2.20 ms | 1.51 ms | 2.10 ms |
| **EDU** | `/api/home/summary` | `200 OK` | 5/5 | 138 B | 1.67 ms | **82.18 ms** | 403.91 ms | 1.73 ms | 323.50 ms |
| **EDU** | `/api/edu/market` | `200 OK` | 5/5 | 190,080 B | 5.23 ms | **87.67 ms** | 415.67 ms | 5.83 ms | 333.71 ms |
| **EDU** | `/api/studio/jobs` | `200 OK` | 5/5 | 11 B | 1.69 ms | **2.24 ms** | 4.13 ms | 1.81 ms | 3.67 ms |
| **EDU** | `/api/health` | `200 OK` | 5/5 | 83 B | 1.35 ms | **1.37 ms** | 1.39 ms | 1.37 ms | 1.39 ms |
| **EDU** | `/api/me` | `200 OK` | 5/5 | 13 B | 1.41 ms | **1.53 ms** | 1.68 ms | 1.50 ms | 1.66 ms |

---

## 3. Frontend Bundle Distribution Baseline

Sizes are measured from every file in the current Vite `dist/assets` trees. Gzip bytes use deterministic gzip compression (`mtime=0`). No bundle-size budget is implied.

| Product | Asset | Bytes | Gzip bytes |
|---|---|---:|---:|
| **COIN** | `AlphaCatalog-BP0ghX2y.js` | 21,789 B | 8,111 B |
| **COIN** | `AreaLine-CVUSDMgj.js` | 4,870 B | 2,258 B |
| **COIN** | `AssistChip-DV-pJPtz.js` | 466,333 B | 156,085 B |
| **COIN** | `Backtest-D9MAs46j.css` | 4,905 B | 1,363 B |
| **COIN** | `Backtest-DjDLY8A6.js` | 192,512 B | 48,667 B |
| **COIN** | `Histogram-Cvee6wgM.js` | 2,027 B | 1,132 B |
| **COIN** | `History-CBXf_hjP.js` | 8,236 B | 2,991 B |
| **COIN** | `Home-DmObc2cc.js` | 9,388 B | 3,329 B |
| **COIN** | `KaTeX_AMS-Regular-BQhdFMY1.woff2` | 28,076 B | 28,104 B |
| **COIN** | `KaTeX_AMS-Regular-DMm9YOAa.woff` | 33,516 B | 33,526 B |
| **COIN** | `KaTeX_AMS-Regular-DRggAlZN.ttf` | 63,632 B | 34,543 B |
| **COIN** | `KaTeX_Caligraphic-Bold-ATXxdsX0.ttf` | 12,368 B | 7,728 B |
| **COIN** | `KaTeX_Caligraphic-Bold-BEiXGLvX.woff` | 7,716 B | 7,662 B |
| **COIN** | `KaTeX_Caligraphic-Bold-Dq_IR9rO.woff2` | 6,912 B | 6,935 B |
| **COIN** | `KaTeX_Caligraphic-Regular-CTRA-rTL.woff` | 7,656 B | 7,611 B |
| **COIN** | `KaTeX_Caligraphic-Regular-Di6jR-x-.woff2` | 6,908 B | 6,931 B |
| **COIN** | `KaTeX_Caligraphic-Regular-wX97UBjC.ttf` | 12,344 B | 7,676 B |
| **COIN** | `KaTeX_Fraktur-Bold-BdnERNNW.ttf` | 19,584 B | 13,327 B |
| **COIN** | `KaTeX_Fraktur-Bold-BsDP51OF.woff` | 13,296 B | 13,258 B |
| **COIN** | `KaTeX_Fraktur-Bold-CL6g_b3V.woff2` | 11,348 B | 11,371 B |
| **COIN** | `KaTeX_Fraktur-Regular-CB_wures.ttf` | 19,572 B | 13,254 B |
| **COIN** | `KaTeX_Fraktur-Regular-CTYiF6lA.woff2` | 11,316 B | 11,339 B |
| **COIN** | `KaTeX_Fraktur-Regular-Dxdc4cR9.woff` | 13,208 B | 13,171 B |
| **COIN** | `KaTeX_Main-Bold-Cx986IdX.woff2` | 25,324 B | 25,352 B |
| **COIN** | `KaTeX_Main-Bold-Jm3AIy58.woff` | 29,912 B | 29,932 B |
| **COIN** | `KaTeX_Main-Bold-waoOVXN0.ttf` | 51,336 B | 30,563 B |
| **COIN** | `KaTeX_Main-BoldItalic-DxDJ3AOS.woff2` | 16,780 B | 16,808 B |
| **COIN** | `KaTeX_Main-BoldItalic-DzxPMmG6.ttf` | 32,968 B | 19,700 B |
| **COIN** | `KaTeX_Main-BoldItalic-SpSLRI95.woff` | 19,412 B | 19,388 B |
| **COIN** | `KaTeX_Main-Italic-3WenGoN9.ttf` | 33,580 B | 20,004 B |
| **COIN** | `KaTeX_Main-Italic-BMLOBm91.woff` | 19,676 B | 19,654 B |
| **COIN** | `KaTeX_Main-Italic-NWA7e6Wa.woff2` | 16,988 B | 17,016 B |
| **COIN** | `KaTeX_Main-Regular-B22Nviop.woff2` | 26,272 B | 26,300 B |
| **COIN** | `KaTeX_Main-Regular-Dr94JaBh.woff` | 30,772 B | 30,787 B |
| **COIN** | `KaTeX_Main-Regular-ypZvNtVU.ttf` | 53,580 B | 31,483 B |
| **COIN** | `KaTeX_Math-BoldItalic-B3XSjfu4.ttf` | 31,196 B | 18,992 B |
| **COIN** | `KaTeX_Math-BoldItalic-CZnvNsCZ.woff2` | 16,400 B | 16,423 B |
| **COIN** | `KaTeX_Math-BoldItalic-iY-2wyZ7.woff` | 18,668 B | 18,633 B |
| **COIN** | `KaTeX_Math-Italic-DA0__PXp.woff` | 18,748 B | 18,722 B |
| **COIN** | `KaTeX_Math-Italic-flOr_0UB.ttf` | 31,308 B | 19,125 B |
| **COIN** | `KaTeX_Math-Italic-t53AETM-.woff2` | 16,440 B | 16,466 B |
| **COIN** | `KaTeX_SansSerif-Bold-CFMepnvq.ttf` | 24,504 B | 14,590 B |
| **COIN** | `KaTeX_SansSerif-Bold-D1sUS0GD.woff2` | 12,216 B | 12,239 B |
| **COIN** | `KaTeX_SansSerif-Bold-DbIhKOiC.woff` | 14,408 B | 14,381 B |
| **COIN** | `KaTeX_SansSerif-Italic-C3H0VqGB.woff2` | 12,028 B | 12,051 B |
| **COIN** | `KaTeX_SansSerif-Italic-DN2j7dab.woff` | 14,112 B | 14,071 B |
| **COIN** | `KaTeX_SansSerif-Italic-YYjJ1zSn.ttf` | 22,364 B | 14,269 B |
| **COIN** | `KaTeX_SansSerif-Regular-BNo7hRIc.ttf` | 19,436 B | 12,359 B |
| **COIN** | `KaTeX_SansSerif-Regular-CS6fqUqJ.woff` | 12,316 B | 12,279 B |
| **COIN** | `KaTeX_SansSerif-Regular-DDBCnlJ7.woff2` | 10,344 B | 10,367 B |
| **COIN** | `KaTeX_Script-Regular-C5JkGWo-.ttf` | 16,648 B | 10,686 B |
| **COIN** | `KaTeX_Script-Regular-D3wIWfF6.woff2` | 9,644 B | 9,667 B |
| **COIN** | `KaTeX_Script-Regular-D5yQViql.woff` | 10,588 B | 10,534 B |
| **COIN** | `KaTeX_Size1-Regular-C195tn64.woff` | 6,496 B | 6,450 B |
| **COIN** | `KaTeX_Size1-Regular-Dbsnue_I.ttf` | 12,228 B | 6,394 B |
| **COIN** | `KaTeX_Size1-Regular-mCD8mA8B.woff2` | 5,468 B | 5,491 B |
| **COIN** | `KaTeX_Size2-Regular-B7gKUWhC.ttf` | 11,508 B | 6,092 B |
| **COIN** | `KaTeX_Size2-Regular-Dy4dx90m.woff2` | 5,208 B | 5,231 B |
| **COIN** | `KaTeX_Size2-Regular-oD1tc_U0.woff` | 6,188 B | 6,136 B |
| **COIN** | `KaTeX_Size3-Regular-CTq5MqoE.woff` | 4,420 B | 4,360 B |
| **COIN** | `KaTeX_Size3-Regular-DgpXs0kz.ttf` | 7,588 B | 4,274 B |
| **COIN** | `KaTeX_Size4-Regular-BF-4gkZK.woff` | 5,980 B | 5,927 B |
| **COIN** | `KaTeX_Size4-Regular-DWFBv043.ttf` | 10,364 B | 5,931 B |
| **COIN** | `KaTeX_Size4-Regular-Dl5lxZxV.woff2` | 4,928 B | 4,951 B |
| **COIN** | `KaTeX_Typewriter-Regular-C0xS9mPB.woff` | 16,028 B | 15,993 B |
| **COIN** | `KaTeX_Typewriter-Regular-CO6r4hn1.woff2` | 13,568 B | 13,591 B |
| **COIN** | `KaTeX_Typewriter-Regular-D3Ib7_Hf.ttf` | 27,556 B | 16,279 B |
| **COIN** | `Live-D9AVTkwy.js` | 270,570 B | 80,293 B |
| **COIN** | `Login-DJ4Qgood.js` | 4,424 B | 1,682 B |
| **COIN** | `Portfolio-Bb-MUvF_.js` | 43,141 B | 12,942 B |
| **COIN** | `Portfolio-Bt8nnmMW.css` | 1,965 B | 757 B |
| **COIN** | `RunModes-DFSZMS_0.js` | 14,207 B | 5,570 B |
| **COIN** | `Studio-DQ24yUHa.js` | 134,900 B | 38,358 B |
| **COIN** | `Term-BKeyjPL_.js` | 10,941 B | 4,694 B |
| **COIN** | `UnderwaterStrip-BOouvlDR.js` | 2,072 B | 1,131 B |
| **COIN** | `alpha-DMMZL9t9.css` | 30,112 B | 6,272 B |
| **COIN** | `home-DNjyhYFN.css` | 18,174 B | 4,396 B |
| **COIN** | `main-Bc4-yBUw.js` | 528,608 B | 163,476 B |
| **COIN** | `main-Dug7_6MH.css` | 95,876 B | 21,653 B |
| **COIN** | `useAsync-Ca9wOU0f.js` | 1,352 B | 676 B |
| **COIN** | `useJob-C7532LnQ.js` | 19,050 B | 7,274 B |
| **COIN** | `useResizableDrawer-DqBfltwK.js` | 786 B | 414 B |
| **EDU** | `CustomResult-Cy08Sv8P.js` | 535,285 B | 178,811 B |
| **EDU** | `CustomResult-DMMZL9t9.css` | 30,112 B | 6,272 B |
| **EDU** | `EduMarket-CROcOl4Q.js` | 8,523 B | 3,277 B |
| **EDU** | `EduStrategy-tqLCkm1N.js` | 2,040 B | 1,089 B |
| **EDU** | `EduUser-BmFSlL39.js` | 3,166 B | 1,258 B |
| **EDU** | `Home-DiWCEi72.js` | 8,761 B | 3,257 B |
| **EDU** | `KaTeX_AMS-Regular-BQhdFMY1.woff2` | 28,076 B | 28,104 B |
| **EDU** | `KaTeX_AMS-Regular-DMm9YOAa.woff` | 33,516 B | 33,526 B |
| **EDU** | `KaTeX_AMS-Regular-DRggAlZN.ttf` | 63,632 B | 34,543 B |
| **EDU** | `KaTeX_Caligraphic-Bold-ATXxdsX0.ttf` | 12,368 B | 7,728 B |
| **EDU** | `KaTeX_Caligraphic-Bold-BEiXGLvX.woff` | 7,716 B | 7,662 B |
| **EDU** | `KaTeX_Caligraphic-Bold-Dq_IR9rO.woff2` | 6,912 B | 6,935 B |
| **EDU** | `KaTeX_Caligraphic-Regular-CTRA-rTL.woff` | 7,656 B | 7,611 B |
| **EDU** | `KaTeX_Caligraphic-Regular-Di6jR-x-.woff2` | 6,908 B | 6,931 B |
| **EDU** | `KaTeX_Caligraphic-Regular-wX97UBjC.ttf` | 12,344 B | 7,676 B |
| **EDU** | `KaTeX_Fraktur-Bold-BdnERNNW.ttf` | 19,584 B | 13,327 B |
| **EDU** | `KaTeX_Fraktur-Bold-BsDP51OF.woff` | 13,296 B | 13,258 B |
| **EDU** | `KaTeX_Fraktur-Bold-CL6g_b3V.woff2` | 11,348 B | 11,371 B |
| **EDU** | `KaTeX_Fraktur-Regular-CB_wures.ttf` | 19,572 B | 13,254 B |
| **EDU** | `KaTeX_Fraktur-Regular-CTYiF6lA.woff2` | 11,316 B | 11,339 B |
| **EDU** | `KaTeX_Fraktur-Regular-Dxdc4cR9.woff` | 13,208 B | 13,171 B |
| **EDU** | `KaTeX_Main-Bold-Cx986IdX.woff2` | 25,324 B | 25,352 B |
| **EDU** | `KaTeX_Main-Bold-Jm3AIy58.woff` | 29,912 B | 29,932 B |
| **EDU** | `KaTeX_Main-Bold-waoOVXN0.ttf` | 51,336 B | 30,563 B |
| **EDU** | `KaTeX_Main-BoldItalic-DxDJ3AOS.woff2` | 16,780 B | 16,808 B |
| **EDU** | `KaTeX_Main-BoldItalic-DzxPMmG6.ttf` | 32,968 B | 19,700 B |
| **EDU** | `KaTeX_Main-BoldItalic-SpSLRI95.woff` | 19,412 B | 19,388 B |
| **EDU** | `KaTeX_Main-Italic-3WenGoN9.ttf` | 33,580 B | 20,004 B |
| **EDU** | `KaTeX_Main-Italic-BMLOBm91.woff` | 19,676 B | 19,654 B |
| **EDU** | `KaTeX_Main-Italic-NWA7e6Wa.woff2` | 16,988 B | 17,016 B |
| **EDU** | `KaTeX_Main-Regular-B22Nviop.woff2` | 26,272 B | 26,300 B |
| **EDU** | `KaTeX_Main-Regular-Dr94JaBh.woff` | 30,772 B | 30,787 B |
| **EDU** | `KaTeX_Main-Regular-ypZvNtVU.ttf` | 53,580 B | 31,483 B |
| **EDU** | `KaTeX_Math-BoldItalic-B3XSjfu4.ttf` | 31,196 B | 18,992 B |
| **EDU** | `KaTeX_Math-BoldItalic-CZnvNsCZ.woff2` | 16,400 B | 16,423 B |
| **EDU** | `KaTeX_Math-BoldItalic-iY-2wyZ7.woff` | 18,668 B | 18,633 B |
| **EDU** | `KaTeX_Math-Italic-DA0__PXp.woff` | 18,748 B | 18,722 B |
| **EDU** | `KaTeX_Math-Italic-flOr_0UB.ttf` | 31,308 B | 19,125 B |
| **EDU** | `KaTeX_Math-Italic-t53AETM-.woff2` | 16,440 B | 16,466 B |
| **EDU** | `KaTeX_SansSerif-Bold-CFMepnvq.ttf` | 24,504 B | 14,590 B |
| **EDU** | `KaTeX_SansSerif-Bold-D1sUS0GD.woff2` | 12,216 B | 12,239 B |
| **EDU** | `KaTeX_SansSerif-Bold-DbIhKOiC.woff` | 14,408 B | 14,381 B |
| **EDU** | `KaTeX_SansSerif-Italic-C3H0VqGB.woff2` | 12,028 B | 12,051 B |
| **EDU** | `KaTeX_SansSerif-Italic-DN2j7dab.woff` | 14,112 B | 14,071 B |
| **EDU** | `KaTeX_SansSerif-Italic-YYjJ1zSn.ttf` | 22,364 B | 14,269 B |
| **EDU** | `KaTeX_SansSerif-Regular-BNo7hRIc.ttf` | 19,436 B | 12,359 B |
| **EDU** | `KaTeX_SansSerif-Regular-CS6fqUqJ.woff` | 12,316 B | 12,279 B |
| **EDU** | `KaTeX_SansSerif-Regular-DDBCnlJ7.woff2` | 10,344 B | 10,367 B |
| **EDU** | `KaTeX_Script-Regular-C5JkGWo-.ttf` | 16,648 B | 10,686 B |
| **EDU** | `KaTeX_Script-Regular-D3wIWfF6.woff2` | 9,644 B | 9,667 B |
| **EDU** | `KaTeX_Script-Regular-D5yQViql.woff` | 10,588 B | 10,534 B |
| **EDU** | `KaTeX_Size1-Regular-C195tn64.woff` | 6,496 B | 6,450 B |
| **EDU** | `KaTeX_Size1-Regular-Dbsnue_I.ttf` | 12,228 B | 6,394 B |
| **EDU** | `KaTeX_Size1-Regular-mCD8mA8B.woff2` | 5,468 B | 5,491 B |
| **EDU** | `KaTeX_Size2-Regular-B7gKUWhC.ttf` | 11,508 B | 6,092 B |
| **EDU** | `KaTeX_Size2-Regular-Dy4dx90m.woff2` | 5,208 B | 5,231 B |
| **EDU** | `KaTeX_Size2-Regular-oD1tc_U0.woff` | 6,188 B | 6,136 B |
| **EDU** | `KaTeX_Size3-Regular-CTq5MqoE.woff` | 4,420 B | 4,360 B |
| **EDU** | `KaTeX_Size3-Regular-DgpXs0kz.ttf` | 7,588 B | 4,274 B |
| **EDU** | `KaTeX_Size4-Regular-BF-4gkZK.woff` | 5,980 B | 5,927 B |
| **EDU** | `KaTeX_Size4-Regular-DWFBv043.ttf` | 10,364 B | 5,931 B |
| **EDU** | `KaTeX_Size4-Regular-Dl5lxZxV.woff2` | 4,928 B | 4,951 B |
| **EDU** | `KaTeX_Typewriter-Regular-C0xS9mPB.woff` | 16,028 B | 15,993 B |
| **EDU** | `KaTeX_Typewriter-Regular-CO6r4hn1.woff2` | 13,568 B | 13,591 B |
| **EDU** | `KaTeX_Typewriter-Regular-D3Ib7_Hf.ttf` | 27,556 B | 16,279 B |
| **EDU** | `Login-B7obnKkR.js` | 4,300 B | 1,624 B |
| **EDU** | `MyProfile-2IbAXtzN.js` | 16,831 B | 4,260 B |
| **EDU** | `Studio-cg3nmGpp.js` | 120,382 B | 35,554 B |
| **EDU** | `eduUi-B9xwiAXx.js` | 975 B | 578 B |
| **EDU** | `home-DNjyhYFN.css` | 18,174 B | 4,396 B |
| **EDU** | `main-BDJM29y4.css` | 93,551 B | 21,221 B |
| **EDU** | `main-Bwx6qtwx.js` | 465,788 B | 142,619 B |

---

## 4. Headless Chrome DOM Render Timings & Structure

Navigation duration is measured through `networkidle`; it is not FCP/LCP. API measurements always target the local backends on ports 18012/18022; DOM URLs are recorded per page and can target Vite dev servers or local vhosts.

| Page | Viewport | Resolution | Navigation Duration | DOM Size | Buttons | Inputs | Headings | Total Est. Nodes | Title | Assertions |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| **COIN Home** | Large Desktop | 1440 × 900 | 1,283 ms | 138,550 B | 8 | 0 | 5 | 44 | `Nora COIN` | `PASS` |
| **COIN Home** | Standard Desktop | 1280 × 800 | 1,266 ms | 138,550 B | 8 | 0 | 5 | 44 | `Nora COIN` | `PASS` |
| **COIN Login** | Large Desktop | 1440 × 900 | 677 ms | 134,066 B | 2 | 1 | 5 | 35 | `Nora COIN` | `PASS` |
| **COIN Login** | Standard Desktop | 1280 × 800 | 688 ms | 134,066 B | 2 | 1 | 5 | 35 | `Nora COIN` | `PASS` |
| **EDU Home** | Large Desktop | 1440 × 900 | 1,394 ms | 134,889 B | 8 | 0 | 5 | 43 | `Nora EDU` | `PASS` |
| **EDU Home** | Standard Desktop | 1280 × 800 | 1,405 ms | 134,889 B | 8 | 0 | 5 | 43 | `Nora EDU` | `PASS` |
| **EDU Login** | Large Desktop | 1440 × 900 | 684 ms | 131,079 B | 2 | 1 | 5 | 35 | `Nora EDU` | `PASS` |
| **EDU Login** | Standard Desktop | 1280 × 800 | 720 ms | 131,079 B | 2 | 1 | 5 | 35 | `Nora EDU` | `PASS` |
| **EDU Studio (Authenticated)** | Large Desktop | 1440 × 900 | 2,783 ms | 335,870 B | 45 | 1 | 0 | 230 | `Nora EDU` | `PASS` |
| **EDU Studio (Authenticated)** | Standard Desktop | 1280 × 800 | 2,762 ms | 335,537 B | 45 | 1 | 0 | 230 | `Nora EDU` | `PASS` |

Authenticated EDU Studio requires a valid user from `NORA_EDU_BASELINE_UID` and verifies `/api/me` returns that user. The generator uses the backend session signing helper; it does not embed the signing secret.

---

## 5. Interpretation

These values are a reproducible local baseline only. Performance targets, acceptable regressions, and production SLOs must be agreed separately; this report does not infer arbitrary thresholds.
