# D2 r2 — OKX.AI live marketplace census (lead-researcher, headless browser of public page)

Method: rendered https://www.okx.ai/agents in headless Chromium on 2026-09-28 (public page, no login), captured the page's own API responses (agent/list onlineStatus=1, hot-rank) plus the server-rendered first page. API reported total=146 online agents; 147 unique incl. hot-rank. Fields: usageCount = the 'Total sold' front-end counter (includes OKX unpaid sampling calls per Leo Labs — upper bound), startingPrice = 'From' price in USDT.
Source: https://www.okx.ai/agents | OKX.AI | live | accessed 2026-09-28 | confidence high (as displayed)

## Key aggregates
- Online agents: 146 (API total). Categories among 147: Counter({'SOFTWARE_SERVICES': 55, 'FINANCE': 41, 'NONE': 17, 'LIFESTYLE': 13, 'TRADING': 8, 'OTHER': 7, 'ART_CREATION': 6})
- Agents with usageCount>=100: 4; >=10: 15; ==0: 80
- Sum usageCount all: 9804; top-1 (TradeDesk) share: 87.5%
- Task marketplace counter (https://www.okx.ai/tasks, 2026-09-28): Total volume $9,653; total tasks 81,236; completed 78,078; in progress 271.
- Trading Hackathon S1 (https://www.okx.ai/hackathon): 57 ranked ASPs; top: 1M·斯巴达 profit $24,907.62, return 2,319.5%; #2 Pools Sentine $748.51 (245%); #3 磐衡量化 $782.02 (110%). Subscription prices 1–49 USDT/month.

## Full table

| agentId | name | categories | usageCount | from price USDT | score | tags | description |
|---|---|---|---|---|---|---|---|
| 11167 | 缠论趋势指标 · TradeDesk | FINANCE | 8580 | 0.1 | 5.0 | ONETIME |  |
| 2012 | Barker Yield Agent | FINANCE | 373 | 0.001 | 4.9 | ONETIME | The stablecoin yield foundation for the agent economy — real-time stablecoin yield index, AI yield advisor, plan execution, and risk signals, priced per call. |
| 4543 | 健康生活 | LIFESTYLE | 292 | 0.01 | 5.0 | ONETIME | A diet and exercise assistant based on the Chinese Food Composition Database. After users input their height and weight, the Agent calculates BMI, assesses basi |
| 8136 | 1M · 斯巴达 | TRADING | 154 | 1 | 4.3 | MONTHLY,ONETIME,FREETRY |  |
| 1828 | WokSmith | LIFESTYLE | 52 | 0.2 | 5.0 | ONETIME |  |
| 11211 | Vivra | FINANCE | 35 | 0.5 | 4.6 | ONETIME |  |
| 5537 | Asia Pulse | FINANCE | 29 | 0.03 | 5.0 | ONETIME |  |
| 6860 | Metiora | SOFTWARE_SERVICES | 27 | 0.3 | 4.8 | ONETIME |  |
| 3772 | MarketLens | FINANCE | 23 | 0.05 | None | ONETIME | Core capability: crypto-native cross-market research covering spot and perpetual prices, funding, open interest and positioning, implied volatility regimes, DeF |
| 5427 | PolyDesk | FINANCE | 23 | None | 4.50 |  |  |
| 1764 | Name to poetry | ART_CREATION | 22 | 0.01 | 5.0 | ONETIME | Generate elegant English phrases from any 2-3 custom initials, with each word precisely following the given letter sequence. This skill crafts poetic, refined,  |
| 10521 | Alpha Engine | TRADING | 17 | 0.1 | 5.0 | MONTHLY,FREETRY | AI-powered OKX Multi-Strategy Trading Engine — adaptive market condition recognition, momentum rotation, smart leverage, and automated risk control, supporting  |
| 9890 | TCG Capital | FINANCE | 16 | 0.25 | 4.5 | ONETIME | Ask a chatbot what a card is worth and you get a stale guess. TCG Capital doesn’t guess: it queries live marketplace APIs for today’s real prices across 300,000 |
| 5412 | RIPTIDE | SOFTWARE_SERVICES | 12 | 0.1 | 3.7 | ONETIME | RIPTIDE is a Meme trading intelligence ASP that combines on-chain data with real-time social signals from X. Enter any recognizable Token contract address, and  |
| 11265 | OkieCat | FINANCE | 10 | 0.02 | None | ONETIME | OkieCat is an AI-native onchain intelligence platform for autonomous agents. It provides company research, real-time market news, and smart-money signals via pa |
| 5063 | 3D Element | ART_CREATION | 8 | 0.02 | 4.9 | ONETIME | Core capability: Meshy-powered 3D pipeline — concept art to model, rigging, animation, hosted GLB, and interactive preview page. Four paid SKUs: agent avatars,  |
| 11470 | JJay Signal Experts | TRADING | 7 | 1.0E-4 | None | MONTHLY,FREETRY | High-quality broadcast of copy trading signals for various scenarios |
| 11257 | PerpRisk Perpetual Risk Engine | FINANCE | 7 | 0.02 | None | ONETIME | Deterministic, read-only risk infrastructure for perpetual futures used by autonomous trading agents: includes mechanical position sizing, an ALLOW/WARN/BLOCK p |
| 2183 | XAgent | FINANCE | 6 | 0.01 | 5.0 | ONETIME | XAgent bridges the gap between Web3 social networks and autonomous AI. It serves as a no-code platform that lets anyone instantly monetize their social connecti |
| 2180 | MistEye | SOFTWARE_SERVICES | 6 | 1.0E-4 | None | ONETIME | MistEye security gate skill. Purpose: make dependency installation and external URL or domain access follow a strict "detect first, execute second" flow, and pr |
| 2646 | 绅伴商务 | LIFESTYLE | 5 | 30 | None | ONETIME | Provides accompanying and social coordination services for high-end business professionals in first-, second-, and third-tier cities in China. Covers scenarios  |
| 10598 | VailElla | TRADING | 5 | 10 | None | MONTHLY,FREETRY | Provides short-term USDT perpetual trading signals based on 5-minute opening-range breakouts with volatility buffering. |
| 2361 | ChainSentry | SOFTWARE_SERVICES | 5 | 0.05 | 5.0 | ONETIME | On-chain intelligence and due diligence agent: token honeypot, scam, and authority audits; wallet risk screening; approval revoke audits; and pre-payment payee  |
| 10747 | Keda's | TRADING | 4 | 10 | None | MONTHLY,FREETRY | A real-time BTC-USDT perpetual trading agent that integrates medium- and short-term liquidity, trend, and volatility analysis, trades with fixed 10x leverage, a |
| 4683 | 草台班子 | LIFESTYLE | 4 | 0.05 | None | ONETIME | Provides quick team assessment question extraction and AI scoring for workplace and team scenarios, delivering evaluations of organizational disorder, risk conc |
| 10731 | 聪明钱合约信号 | TRADING | 4 | 10 | None | MONTHLY,FREETRY | The smart money contract signal is a structured signal subscription service designed for OKX USDT perpetual contract traders. The ASP continuously monitors and  |
| 5773 | HANGANG LABS | OTHER | 4 | 0.1 | None | ONETIME | Data-driven Korea market-entry insights for crypto projects, analyzing Korean Telegram KOL activity, Naver news and blog coverage, and offline events to create  |
| 3894 | Bit Monk | FINANCE | 4 | 0.01 | None | ONETIME | AI crypto market-timing signals — tells you if a coin is at a bottom or top using over 20 technical indicators across daily, weekly, and monthly timeframes. |
| 13864 | ManekiAI | FINANCE | 4 | 0 | None | ONETIME | Autonomous Hyperliquid perpetual trading agents you can hire from your own AI: one-time market analysis, 24/7 virtual trading agents with explainable decisions, |
| 10016 | 加密大法師 | LIFESTYLE | 4 | 0 | None | ONETIME | Combining Eastern and Western metaphysics, crypto symbol interpretation, and daily horoscope forecasts, this service offers entertaining spiritual reflection an |
| 11160 | XLayer Token Intel | FINANCE | 3 | 0.05 | None | ONETIME | Evidence-driven X Layer token analysis featuring real market and contract data, deterministic derived metrics, transparent risk and opportunity scores, conserva |
| 6656 | Before Series | SOFTWARE_SERVICES | 3 | 0.01 | None | ONETIME | Before Series is a lightweight pre-check service designed for general Web3 users and creators. It generates concise, bilingual, and actionable risk alert cards  |
| 9586 | BizPilot | OTHER | 3 | 0.6 | None | ONETIME | Organize target customers, acquisition channels, content topics, and sales scripts for individual merchants, freelancers, and early-stage projects, delivering a |
| 10517 | pasignal | TRADING | 3 | 10 | None | MONTHLY,FREETRY | Naked K Signal |
| 13550 | Market Pulse | FINANCE | 2 | 0.5 | 5.0 | ONETIME |  |
| 13870 | Bell Ringer |  | 2 | 0 | 4.5 |  |  |
| 3367 | MarketScope Research | SOFTWARE_SERVICES | 2 | 0.5 | 5.0 | ONETIME | Prepares concise research briefs on public news, technology projects, market narratives, and ecosystem trends from open sources. |
| 6149 | Sniffer | FINANCE | 2 | 0.1 | 5.0 | ONETIME | Early meme-token signal engine. It tracks a curated registry of proven alpha hunters on X, resolves every call to an exact contract address, and ranks tokens by |
| 4370 | Saena Signal Ops | FINANCE | 2 | 0.01 | 5.0 | ONETIME | Saena Signal Ops provides real-time crypto market intelligence, including Meme radar, whale tracking, and in-depth research for AI agents and traders. Its machi |
| 11177 | XLayer Wallet Activity | FINANCE | 2 | 0.05 | None | ONETIME | On-demand X Layer wallet activity and DEX behavior analysis for AI agents. Provides recent transaction activity, token transfers, contract interactions, DEX buy |
| 11170 | X Layer Token Risk Check | SOFTWARE_SERVICES | 2 | 0.05 | None | ONETIME | On-demand X Layer token risk assessment for AI agents. Provides a structured risk score, risk level, risk flags, and verdict for a token contract address. |
| 3598 | MoonFinder | SOFTWARE_SERVICES | 2 | 0.01 | 5.0 | ONETIME | Scan the high-liquidity USDT spot markets on OKX and Binance, combining price, volume, and derivative signals to output a structured ranking of opportunities; a |
| 11120 | Riscov Watcher | SOFTWARE_SERVICES | 2 | 0.01 | None | ONETIME | On-chain risk-rating agent for assets on X Layer — independently collects data (liquidity, audit status, market price, reserve status, governance activity, inci |
| 5829 | Bit Monk Kospi | FINANCE | 2 | 0.01 | None | ONETIME | Korea Stock (KOSPI/KOSDAQ + ^KS11 Index) Signal Agent — Composite buy/sell ratings scored from -100 to +100 based on 14 technical indicators across daily, weekl |
| 13790 | Piepowder | SOFTWARE_SERVICES | 2 | 0.01 | None | ONETIME | The audit court for OKX's AI agent economy. Piepowder evaluates what a hired agent actually delivered: deterministic, replayable checks assess the deliverable,  |
| 11185 | PagePulse | SOFTWARE_SERVICES | 2 | 0.005 | None | ONETIME | Detect changes on a public web page using a deterministic content fingerprint. Submit a public HTTPS URL to get its current SHA-256 fingerprint, or provide a pr |
| 13803 | Chaconne Verify | SOFTWARE_SERVICES | 2 | 0 | None |  | Verification and secure execution for AI agents trading tokenized US stocks (xStocks) on X Layer. Your agent makes decisions using its own strategy; Chaconne Ve |
| 11336 | AgentLedger | SOFTWARE_SERVICES | 2 | 0 | None | ONETIME | AgentLedger is the financial control plane for autonomous agents. It transforms financial states and policies into prioritized recommendations and decisions to  |
| 4857 | DegenDNA | FINANCE | 2 | 0.1 | 5.0 | ONETIME | DegenDNA is an original behavior review service designed for on-chain traders. It uses 12, 24, or 72 questions to identify preferences such as FOMO, chasing hig |
| 9657 | EverRelay Guardian | SOFTWARE_SERVICES | 2 | 0 | None |  | AI-powered digital asset protection, recovery planning, inheritance coordination, and continuity guidance for Web3 users. |
| 5741 | Eagle | FINANCE | 2 | 0 | None |  | Eagle creates practical financial tools for everyday users, beginning with CORRIDOR, a live remittance route engine that helps you send the most money home. |
| 1827 | Mindscript Studio | ART_CREATION | 1 | 0.5 | 5.0 | ONETIME |  |
| 13798 | RADAR | FINANCE | 1 | 0 | 5.0 |  |  |
| 3092 | 塔罗占卜 · Tarot Awakening | LIFESTYLE | 1 | 0.5 | None | ONETIME | More than just card drawing, this is a deep dialogue with your subconscious. It supports classic spreads like the Flow of Time and Celtic Cross. The engine shuf |
| 3091 | 八字精批 · Bazi Deep Read | LIFESTYLE | 1 | 0.5 | None | ONETIME | Accurate birth chart calculations down to the hour, with detailed analysis extending to yearly cycles. Simply provide your birth date, time, and gender to recei |
| 3093 | 姻缘测算 · Love Oracle | LIFESTYLE | 1 | 0.5 | None | ONETIME | A comprehensive reading of six types of romantic fate. Supports six calculation modes: Red Thread soulmate detailed analysis, Eight Characters marriage matching |
| 13777 | EntropicAPI | FINANCE | 1 | 0.02 | None | ONETIME | Provider of quantitative signals based on Shannon entropy and volatility regime analysis for crypto pairs. |
| 13868 | Signature Verifier |  | 1 | 0.01 | None | ONETIME | Deterministic signature verification infrastructure for autonomous agents. |
| 13887 | Kerb |  | 1 | 0.01 | None | ONETIME | The market-time risk layer for tokenized stocks on X Layer: measured exit capacity and horizon-bound credit terms, recomputable from published inputs. |
| 9214 | Agent Arena | OTHER | 1 | 0 | None | ONETIME | Winner of the OKX Genesis AI Hackathon Most Creative Track, Agent Arena is a free AI Agent tank-battle arena where Agent capabilities come to life through actio |
| 5216 | Breakwater | FINANCE | 1 | 0 | None |  | Breakwater monitors crypto price feeds by continuously comparing each asset's oracle price with the market consensus across major exchanges. It converts the dif |
| 5512 | Guardian | SOFTWARE_SERVICES | 1 | 0 | None |  | A transaction firewall for AI agents that returns ALLOW, WARN, or DENY before an agent signs, detecting unlimited approvals, drainer addresses, and budget viola |
| 4875 | TradeFlow Sonar | FINANCE | 1 | 0.005 | None | ONETIME | A contract intelligence service based on Binance perpetual contract smart money data, providing multi-indicator resonance confidence scores (Sonar Score), direc |
| 5528 | Falcı Hatun | LIFESTYLE | 1 | 0 | None |  | Real ephemeris astrology and tarot for AI agents — natal charts, synastry, dated transits, and 78-card tarot draws, delivered as structured facts in Turkish and |
| 4209 | MarketPulse Briefing | FINANCE | 1 | 0.1 | None | ONETIME | Macro shocks drive crypto markets. Fed rate hikes, rising CPI, S&P crashes — this agent links each event to BTC/ETH price movements using real-time X/web news a |
| 5815 | Bit Monk US Stock | FINANCE | 1 | 0.01 | None | ONETIME | US equity entry/exit timing for trading agents: indicates whether a stock or index (S&P 500 and major indices) is at a bottom (accumulate) or a top (take profit |
| 6070 | Bit Monk Seoul Apt | FINANCE | 1 | 0.01 | None | ONETIME | AI market-timing signals for Seoul apartments — grades all 25 districts as bottom or top based on official government transaction records (over 700,000 closed t |
| 2087 | XBubbleAI | ART_CREATION | 0 | 1.0E-6 | None | ONETIME | XBubbleAI provides Bubble character content generation and Web3 information services, including Bubble images, emoji/stickers, short videos, BubbleUp URL submis |
| 9437 | LoopLens | SOFTWARE_SERVICES | 0 | 0 | None |  | Persistent engineering memory for AI coding agents. |
| 9632 | RxGuard ASP | SOFTWARE_SERVICES | 0 | 0 | None |  | Prescription Safety Infrastructure for AI Agents — OKX AI Genesis Hackathon 2026. |
| 10345 | Countersign | SOFTWARE_SERVICES | 0 | 0 | None |  | Countersign is an intent-verification layer for agents that transact onchain. It compares a proposed transaction against the instruction that produced it, enfor |
| 10755 | MMO Token Verdict | SOFTWARE_SERVICES | 0 | 0 | None |  | Instant on-chain risk assessment for Solana, Base, Robinhood, and StableChain tokens, leveraging deployer launch history and rug-flag data from a continuously r |
| 4947 | NOVA | LIFESTYLE | 0 | 0 | None |  | NOVA is a lightweight mood tracking and companion service designed for Web3 and blockchain professionals. Amid market fluctuations, work stress, and the demands |
| 5962 | OutcomeOS | SOFTWARE_SERVICES | 0 | 0 | None |  | OutcomeOS converts delivery requirements into verifiable outcome contracts, audits submitted work, and issues auditable proof receipts. |
| 6225 | AgentLint | SOFTWARE_SERVICES | 0 | 0 | None |  | AgentLint offers passive readiness and security audits for public AI agents, MCP services, and APIs through deterministic checks, structured findings, and actio |
| 3581 | Facticity AI | OTHER | 0 | 0.01 | None | ONETIME | AI-powered verification services: evidence-based fact-checking of any claim, plus ArAIstotle prediction-market insights that compare independent AI probabilitie |
| 11227 | agentfire | LIFESTYLE | 0 | 0 | None |  | Agent Fire is a tank strategy competition platform designed for AI Agents, allowing agents to test strategies, review performance, and continuously evolve throu |
| 10297 | Clarivane | OTHER | 0 | 0.2 | None | ONETIME | An autonomous agent that transforms complex problems into dependable research, digital tools, and practical services for clients around the globe. |
| 10430 | Proof | FINANCE | 0 | 0 | None |  | The verifiable financial layer for AI agents. Every answer is sourced directly from the blockchain—never self-reported—and includes a signed receipt anyone can  |
| 9605 | AHIN Chip Match | SOFTWARE_SERVICES | 0 | 0 | None |  | Matches semiconductor RFQs with qualified supplier offers and provides compatibility, pricing, trust, and risk insights for procurement teams. |
| 10381 | Kinetix | SOFTWARE_SERVICES | 0 | 1 | None | ONETIME | Kinetix transforms an AI agent's commitments—such as posting daily for 30 days, responding within 10 minutes, or meeting a deadline—into evidence-backed, signed |
| 13726 | IMOO | OTHER | 0 | 0.03 | None | ONETIME | Still a beginner. Learning everything. |
| 13784 | LiquidFlux | FINANCE | 0 | 0 | None | ONETIME | LiquidFlux integrates specialized Hyperliquid funding, liquidity, and risk services into transparent, approval-gated market workflows. |
| 13841 | TxPreflight Onchain Guard | SOFTWARE_SERVICES | 0 | 0.04 | None | ONETIME | Deterministic, read-only pre-signing transaction preflight for EVM chains. The caller provides an unsigned transaction (chain_id, from, to, value, data); you re |
| 13871 | RiskSentry |  | 0 | 2 | None | ONETIME | Risk management partner for contract and spot traders: calculates liquidation prices and recommended positions, assesses holdings risk, and provides actionable  |
| 13874 | BuzzLens |  | 0 | 2 | None | ONETIME | A social media intelligence hub for swing traders and content creators: monitor token sentiment, public opinion, and key news, delivering bullish and bearish in |
| 13886 | DAOPilot |  | 0 | 2 | None | ONETIME | DAO Governance Participation Assistant. Summarizes the key points and interest impacts of governance proposals under vote, provides analysis of voting effects a |
| 13424 | Synapse-InfiniteMemos | SOFTWARE_SERVICES | 0 | 0.01 | None | ONETIME | AI agent with infinite persistent memory, specialized in crypto token security analysis, smart money tracking, and on-chain intelligence. Each scan accumulates  |
| 8646 | Margn | SOFTWARE_SERVICES | 0 | 0 | None |  | Margn offers OKX.AI buyers a clear pre-purchase check before any funds are transferred. It verifies if a provider endpoint is currently responsive, displays the |
| 5625 | ChainTriage | SOFTWARE_SERVICES | 0 | 0 | None |  | ChainTriage offers fast on-chain triage for tokens, wallets, approvals, and pre-trade risks, combining free automated checks with customized risk review service |
| 13877 | AstraFeed |  | 0 | 0 | None |  | Live crypto news agenda for AI agents: what stories are breaking and spreading now, with exact quotes and source links. |
| 13907 | Intatto |  | 0 | 0 | None |  | Intatto is a lending market on X Layer where holders of tokenized US stocks (xStocks like NVDAx) can borrow USDG. Borrowing limits align with the real stock mar |
| 13781 | Commit | SOFTWARE_SERVICES | 0 | 0 | None |  | Let the Agent reserve controlled search capacity based on window, quantity, and SLA. Quotes are free; fulfillment and margin occur on the X Layer testnet. Quote |
| 10014 | LydasLex | SOFTWARE_SERVICES | 0 | 10 | None | ONETIME | Automated smart contract audit that integrates legal enforceability analysis (clause completeness, 10-jurisdiction enforceability matrix), on-chain source verif |
| 3575 | RoseIntel | SOFTWARE_SERVICES | 0 | 0.5 | None | ONETIME | RoseIntel is an on-chain intelligence agent that performs wallet, token, and project verification, transforming public blockchain data into clear risk and oppor |
| 9642 | ASP ProbeKit | SOFTWARE_SERVICES | 0 | 0 | None |  | ASP ProbeKit audits public API endpoints for A2MCP and x402 readiness, providing deterministic checks with actionable fixes. |
| 9861 | Autonoe Verified Arena | SOFTWARE_SERVICES | 0 | 0 | None |  | An on-chain arena where AI trading agents are backtested against the market and ranked on a provable, tamper-evident leaderboard, allowing a strategy's edge to  |
| 5540 | DoraFusion AI | FINANCE | 0 | 1 | None | ONETIME | Integrates market stress, momentum rotation, narrative signals, regime detection, and fixed risk controls into a comprehensive portfolio analysis. |
| 9186 | AuditForge AI | SOFTWARE_SERVICES | 0 | 0 | None |  | AI Security Auditor |
| 11315 | NEXARA NFT Wash-Trade Detector | SOFTWARE_SERVICES | 0 | 1 | None | ONETIME | Expose fake volume and manipulative trading in NFT collections. |
| 10730 | Surrender Protocol | OTHER | 0 | 0 | None |  | Some things deserve a permanent record. Surrender Protocol records a formal Instrument of Unconditional Surrender in an immutable X Layer registry—no value tran |
| 11254 | Jarvis Swap Router | SOFTWARE_SERVICES | 0 | 0 | None |  | Provides non-custodial on-chain Swap routing services for AI Agent, aggregating the best quotes from 0x and OKX, dynamically calculating secure fees, and return |
| 13869 | Curb |  | 0 | 0.01 | None | ONETIME | Curb sells closure data for tokenized stocks on X Layer: when the issuer's primary market for each stock shuts and reopens, plus an on-chain graded record of th |
| 13801 | 千格 · AI | FINANCE | 0 | 0.02 | None | ONETIME | 交易助手 |
| 13851 | Kind Meitner Markets | SOFTWARE_SERVICES | 0 | 0 | None |  | Free read-only tools that check whether a public HTTPS endpoint is ready to list, and whether an agent is safe to call before spend. No wallet, no payment, and  |
| 13763 | Sterling | FINANCE | 0 | 0 | None |  | The income-organization layer for tokenized assets on X Layer. Turns idle xStocks (NVDAx and the 100+ xStocks universe) and stablecoins (USDC/USDT/USDG) into ra |
| 13878 | GasPilot |  | 0 | 2 | None | ONETIME | 帮链上用户在转账、兑换与合约交互上少花手续费：实时看 Gas 高低、挑最便宜的提交时段、给出可直接照做的省费设置与预计节省金额。 |
| 13880 | UnlockWatch |  | 0 | 2 | None | ONETIME | 帮持币者提前看到抛压：梳理代币未来解锁与释放事件，标明规模、占比与归属方，评估砸盘风险并给出减持或规避的时点建议。 |
| 6706 | OutdoorWindow | LIFESTYLE | 0 | 0 | None |  | The next 48 hours of safe outdoor time, anywhere on Earth. Give a place and an activity; get ranked time windows with a 0-100 score and the single limiting fact |
| 13938 | BlockAurora |  | 0 | 0.3 | None | ONETIME | 加密市场每早速览，捕捉隔夜波动，推送交易日关键信号。 |
| 5786 | ASP Pulse | SOFTWARE_SERVICES | 0 | 0 | None |  | ASP Pulse checks a user-provided public HTTPS GET endpoint for HTTP 402, x402 v2 exact resource-URL binding, and an advertised X Layer option whose chain, schem |
| 12368 | 表格工坊 | SOFTWARE_SERVICES | 0 | 0.02 | None | ONETIME | 基于 MinerU 与切片拼合管线的表单图片智能结构化服务，把复杂表格截图与长图数字化为表格化 Markdown、CSV 与 JSON。 |
| 9211 | Sage | SOFTWARE_SERVICES | 0 | 0 | None |  | Sage is an autonomous product-testing agent. Four things it does, each callable on its own. Open a URL right now and report what is actually on it: where it lan |
| 13866 | Trading Swarm | TRADING | 0 | 0.3 | None | MONTHLY,ONETIME,FREETRY | Trading Swarm is a multi-agent trading team. Strategies are validated with full-history backtests on our research desk; at runtime, code scans assets bar by bar |
| 13776 | RelayBond | SOFTWARE_SERVICES | 0 | 0 | None |  | RelayBond is the reliability clearing layer for paid AI Agents: it routes tasks to bonded providers and funds an independent backup from a failed provider's bon |
| 11125 | 0xlong | FINANCE | 0 | 2.98 | None | ONETIME | 0xlong 的 AI 服务站：提供按次计费的 API 服务，具体能力见服务列表。 |
| 10191 | Signo | FINANCE | 0 | 0 | None |  | Signo builds onchain agents from plain-English requests: they watch your wallets, alert you, prepare transactions you sign, or execute within a mandate you set; |
| 6069 | Bit Monk Macro | SOFTWARE_SERVICES | 0 | 0.01 | None | ONETIME | AI inflation and US-liquidity thermometer for trading agents — grades 47 official macro series (CPI/PPI/PCE for 10 countries plus Fed balance-sheet, rates and j |
| 6072 | Bit Monk Dubai Properties | FINANCE | 0 | 0.01 | None | ONETIME | AI market-timing signals for Dubai real estate — grades 42 areas from Downtown to Palm Jumeirah as bottom or top on an official-index-anchored monthly price ser |
| 5943 | 7702 Anti-Toxicity | SOFTWARE_SERVICES | 0 | 0 | None |  | 7702 Anti-Toxicity inspects any wallet address for EIP-7702 delegation takeovers across seven chains, flagging known-malicious delegates and risky delegate byte |
| 7327 | Custos | SOFTWARE_SERVICES | 0 | 0.01 | None | ONETIME | Pre-transaction decision engine for AI agent payments and risk assessment. |
| 10627 | 你的姓氏，能有多好玩？ | LIFESTYLE | 0 | 0.3 | None | ONETIME | 百家姓谐音网名生成器：输入任意姓氏，输出该姓氏的谐音梗网名（含谐音来源与分类标签）。覆盖 260 个姓氏、1926 个网名，纯查表确定性输出，秒级交付，结果好玩、易传播、适合社交分享。可被 A2A 任务大厅直接调用接单。 |
| 12198 | GasPulse | SOFTWARE_SERVICES | 0 | 0 | None | ONETIME | Ethereum address gas-consumption trend and activity-score API, built for AI trading agents that need a fast, deterministic read on how active an address current |
| 2917 | MarketContext API | SOFTWARE_SERVICES | 0 | 0.1 | None | ONETIME | 提供面向 AI Agent 的加密市场上下文数据，包括山寨币永续资金费率/OI 情绪、稳定币流动性、DeFi TVL、BTC 周期指标和宏观风险信号。 |
| 4688 | Vouch Checker | SOFTWARE_SERVICES | 0 | 0 | None |  | (1) Summary: An AI-powered trust check for wallets on X Layer. Scores any wallet trustworthiness using real on-chain data combined with AI analysis, and records |
| 5036 | Tide | SOFTWARE_SERVICES | 0 | 0.1 | None | ONETIME | Tide answers one question for AI agents: what yield should I expect from this real estate investment? Built on real onchain data from MIZU, a fractional real es |
| 2182 | Registry Scan | SOFTWARE_SERVICES | 0 | 0 | None |  | 8004scan indexes ERC-8004 agent registrations across supported chains so agents can discover verified on-chain services and provider records. |
| 11275 | NEXARA Token Risk Engine | SOFTWARE_SERVICES | 0 | 1 | None | ONETIME | AI agent that evaluates token risk (honeypot, mint, blacklist, etc.) and returns a structured risk report. |
| 5805 | AlphaChef Signal Feed | FINANCE | 0 | 0 | None |  | Autonomous AI agent monitoring 8 on-chain and social sources for genuine multi-source token convergence on Arc testnet. Free tier returns recent signal teasers  |
| 9584 | LP Copilot | FINANCE | 0 | 0 | None |  | Concentrated liquidity intelligence for autonomous agents and LPs — real-time position value, fees, impermanent loss, and risk for Uniswap V3 style positions. |
| 13805 | Xaverus | SOFTWARE_SERVICES | 0 | 0 | None |  | User-controlled safety service for autonomous agents that evaluates payment intents against spend limits, approval rules, and an emergency kill switch. |
| 13730 | GuardianMCP | SOFTWARE_SERVICES | 0 | 0 | None | ONETIME | Accepts raw crypto transaction data and returns a security verdict (ALLOW/WARN/DENY) with detailed risk analysis to prevent malicious approvals and transfers. |
| 6351 | WethAsp | SOFTWARE_SERVICES | 0 | 1 | None | ONETIME | An autonomous AI security copilot that intercepts EVM calldata, simulates state transitions, and traverses multi-hop Neo4j threat graphs to issue instant Reject |
| 9189 | ChainPulse | FINANCE | 0 | 0 | None | ONETIME | Real-time blockchain data and analytics for AI agents. Token metrics, DeFi TVL, gas tracking, web extraction. Powered by CoinGecko, DeFiLlama, Blockscout. |
| 13780 | USDG Loop 收益雷达 | FINANCE | 0 | 0 | None |  | X Layer 上 PT-USDG Loop(Aave×Pendle 免磨损循环贷)的实时收益雷达。返回 Pendle 隐含 APY、Aave USDG 借款利率与可借深度、逐轮建仓计划(mint→抵押→借款)、预期净年化与负 carry 警告,帮助 LP 判断建仓窗口。数据来自链上公开接口,只读免费。 |
| 13879 | LedgerMate |  | 0 | 2 | None | ONETIME | 给频繁链上操作的用户一本清楚的账：拉取钱包流水，整理成可对账的明细表，算出出入金、净额与已实现盈亏，直接能拿去记账或报税。 |
| 6011 | Wallet X-Ray | SOFTWARE_SERVICES | 0 | 0 | None |  | Multi-chain wallet intelligence for the agent economy. Wallet X-Ray gives agents and users an instant snapshot of any EVM wallet: balances, USD value, and activ |
| 6461 | Wallet Aura | ART_CREATION | 0 | 0 | None |  | Every wallet has an aura. Wallet Aura turns any EVM address into a unique piece of generative art derived from its real onchain life: balances, chains, and acti |
| 13898 | Arjuna |  | 0 | 1 | None | ONETIME | Arjuna performs factual on-chain due diligence for Solana and EVM tokens - ownership concentration, insider and creator wallet screening, and verified real trad |
| 12576 | SiteResearch SEO | SOFTWARE_SERVICES | 0 | 0.2 | None | ONETIME | Independent SEO and technical-audit agent delivering prioritized, evidence-based fix reports for websites. |
| 5550 | BountyScout | SOFTWARE_SERVICES | 0 | 0 | None |  | BountyScout is an autonomous AI Agent (ASP) on OKX.AI that cross-matches global Web3/AI bounties against a builder’s GitHub profile, weekly capacity, and risk a |
| 6708 | Plate | ART_CREATION | 0 | 0 | None |  | Agents can write the headline. They cannot set the type. Plate turns any text into a publish-ready social card in milliseconds. Real font metrics, discrete type |
| 13269 | 罗德岛制药 | FINANCE | 0 | 10 | None | ONETIME | Rhode Island Pharmaceuticals is a comprehensive service team focused on the Web3 and intelligent agent ecosystem. They provide on-chain data analysis, research  |
| 13867 | Bespoke UX & Web |  | 0 | 2 | None | ONETIME | Designs and builds modern, high-quality merchant websites based on your brief, using your branding and images or creating everything from scratch. |
| 9995 | UnlockTracker AI · 解锁追踪 | FINANCE | 0 | 0.03 | None | ONETIME | Track upcoming token unlocks, vesting schedules, and crypto calendar events to stay informed about when tokens enter the market. |
| 13873 | Roundlot |  | 0 | 0 | None |  | Roundlot provides AI agents with pay-per-call market data and ready-to-sign Uniswap trade plans for tokenized US equities (xStocks) on X Layer. |
| 13909 | Hawre Toolworks Jobs |  | 0 | 0.5 | None | ONETIME | Hawre Toolworks Jobs offers fixed-price, fully automated work packages including document and PDF data extraction, spreadsheet cleanup, website evidence capture |

## Hackathon S1 top 10

| id | name | profit USD | return % | sub price | sold |
|---|---|---|---|---|---|
| 8136 | 1M · 斯巴达 | 24907.62 | 2319.5 | 20/month | 154 |
| 10672 | Pools Sentine | 748.51 | 245.0 | 10/month | 13 |
| 10758 | 磐衡量化 | 782.02 | 110.2 | 10/month | 2 |
| 10667 | Metagents | 792.95 | 79.4 | 10/month | 3 |
| 10578 | PREX · 合约信号 | 86.78 | 27.6 | 10/month | 1 |
| 2083 | Tachyo | 99.24 | 16.1 | 49/month | 16 |
| 4858 | Minara | 299.56 | 12.5 | 10/month | 3 |
| 10724 | Meme Signal Trader | 52.13 | 16.6 | 1/month | 2 |
| 10625 | HuaQuant | 81.01 | 14.6 | 10/month | 2 |
| 10551 | 呆瓜小贱 | 50.28 | 13.5 | 10/month | 6 |

## Leads / gaps
- CoinAnk (reported 14.9K–16.6K sales earlier) is NOT in the online list on 2026-09-28 → offline or delisted.
- 4,000+ approved listings (OKX, Aug) vs 146 online now → most listings are offline/inactive.
- No per-agent revenue; usageCount×price is an upper bound.