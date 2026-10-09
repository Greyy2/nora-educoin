<div align="center">

# NoraBT

**AI risk supervisor for OKX copy-trading bots & Crypto Perp Quantitative Pipeline**

> 📌 **Core Quantitative Pipeline & Studio:** Hệ thống nghiên cứu định lượng, Core Engine 1m, WFA, Monte Carlo, và Studio UI nằm tại thư mục [`nora/`](nora/README.md). Xem [Nora Documentation](nora/docs/bmad/README.md).

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-server-000000)
![OKX](https://img.shields.io/badge/OKX-public%20API-000000)
![x402](https://img.shields.io/badge/x402-X%20Layer-7B3FE4)

[Nora Core Pipeline](nora/README.md) · [Nora BMAD Docs](nora/docs/bmad/README.md) · [System overview](Agent/docs/SYSTEM_OVERVIEW.md) · [OKX AI report](Agent/docs/OKX_AI_REPORT.md)

</div>

---

## ✨ What it does

| | |
|---|---|
| 🔍 **Hidden losses** | Open positions marked to market, not just the closed book |
| 🎲 **Stress test** | 10,000-path Monte Carlo on the bot's own trades |
| 🧠 **Skill or luck** | Probabilistic / deflated Sharpe and the track record needed to trust it |
| 🌦 **Market fit** | Results in every market regime, including the untested ones |
| 🧩 **Portfolio** | Whether 2–8 bots are really diversified or move together |
| 🤖 **For agents** | The same engine exposed as MCP tools, pay-per-call with x402 |

## 🚀 Quick start

```bash
cp Agent/.env.example Agent/.env          # add your OKX API key / secret / passphrase
cd Agent/frontend && npm install && bash build.sh && cd ../..
docker compose -f Agent/docker/docker-compose.yml up -d --build
curl http://127.0.0.1:8770/healthz        # 200 = ready
```

| Service | Port | |
|---|---|---|
| Web app + API | `127.0.0.1:8770` | dashboard, bot reports, JSON API |
| MCP server | `127.0.0.1:8765/mcp` | tools for AI agents |

> Requires Docker, Node 18+ and an OKX API key (read-only is enough). All settings are documented in [`Agent/.env.example`](Agent/.env.example).

## 🖥 Use it

**Web.** Open `http://127.0.0.1:8770`, paste a lead trader's bot code in **Assess bot**, and read the report in three tabs: *Analyst Result*, *Premium Market* and *Other & Position*.

**API.**

```bash
curl -X POST http://127.0.0.1:8770/api/analyze -H 'content-type: application/json' \
     -d '{"code":"3EB985F124C18792"}'
```

**AI agents (MCP).**

```bash
claude mcp add --transport http norabt http://127.0.0.1:8765/mcp
```

| Tool | Returns |
|---|---|
| `list_assessed_bots` | Bots already scored |
| `get_assessment` | Saved risk report of one bot |
| `get_market` | Market analysis for one symbol |
| `assess_bot` | Full live assessment (fresh Monte Carlo) |
| `list_assets` · `list_bots` | What is available to assess |

x402 pay-per-call on X Layer is built in and turns on once the agent is listed on the OKX AI Marketplace.

## 📁 Project layout

```
Agent/
├── backend/     risk engine, web app, MCP server
├── frontend/    React dashboard
├── docker/      Dockerfile, compose, deployment runbook
├── docs/        system overview, OKX AI report, specs
└── none/        crawlers and tests
```

<sub>The repository also holds older, unrelated projects (`coins/`, `coin_service/`, `nora/`). NoraBT lives entirely in `Agent/`.</sub>
