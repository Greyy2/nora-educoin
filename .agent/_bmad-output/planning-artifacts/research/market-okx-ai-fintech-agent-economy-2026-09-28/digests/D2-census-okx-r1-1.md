# D2 — Census of real fintech AI agents in/around the OKX ecosystem (round 1, digest 1)

- Run date: 2026-09-28 · Researcher: BMAD Deep Recon (research firewall; no project files read)
- Budget: ~21 tool calls (WebSearch/WebFetch)
- Decision served: which fintech AI-agent niche to build on OKX AI

**Big caveat before reading the table:** the "sold" counts on OKX.AI listings are frontend counters. Leo Labs' first-hand vendor report says OKX makes unpaid "sampling calls" to evaluate service quality, and those calls count toward the frontend numbers. Leo Labs' 9 listed services showed counts implying tens of dollars, but on-chain receipts were only **0.8 USDT across 10 transactions (Jul 13–29, 2026)**. Across the whole task marketplace, the platform counter shows **$9,653 total volume across 81,236 tasks** (fetched 2026-09-28). Treat every "sold" figure below as an **upper bound on usage, not revenue**.

Implied revenue = sold × listed "from" price. This is my own arithmetic and an upper bound. Real revenue is likely lower.

## (a) Census table

Confidence: H = primary source retrieved this run and number read directly; M = one primary or good secondary source, number not cross-checked; L = weak secondary source, marketing, or a number that is known to be inflated.

### A. Agents / ASPs listed on OKX.AI (OKX's agent-to-agent marketplace, settles in USDT/USDG on X Layer)

| # | Name | Platform/chain | Niche | What it does (≤12 words) | Monetization model & price | Revenue/usage metric (with number) | Metric date | Source URL | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | CoinAnk OpenAPI | OKX.AI / X Layer | Signals & Data/Analytics | 80 crypto-derivatives data APIs (OI, funding, liquidations, whales) | Pay-per-call; ~0.01 USDT/call (Leo Labs) | "14,900+ sales" (OKX Learn); 16,600 units (Leo Labs), which implies ≤ ~$166 | Aug–Sep 2026 | https://www.okx.com/en-us/learn/okx-ai-2 ; https://leolabs.me/blog/ai-agent-paying-for-services/en/ | M (count H, revenue L because of sampling calls) |
| 2 | 缠论趋势指标 · TradeDesk (Chan-theory trend indicator), ID 11167 | OKX.AI / X Layer | Signals & Data/Analytics | Chan-theory trend analysis for crypto, stocks, forex, futures | From 0.1 USDT; Standard/Pro packages | 8.58K sold, 5.0 rating, which implies ≤ ~$858 | 2026-09-28 | https://www.okx.ai/agents | M |
| 3 | 1M · 斯巴达 (1M · Sparta), ID 8136 | OKX.AI / X Layer | Trading/Execution (signals + copy-trading) | High-multiplier trend copy-trading signals, 2–5 orders/month | 1 USDT per report; 20 USDT/month subscription | 154 sold, 4.38 rating; **won 1st place ($10,000) in OKX.AI Trading Hackathon S1 (live PnL)** | 2026-09-28 (listing); Aug 11–25, 2026 (hackathon) | https://www.okx.ai/agents ; https://www.okx.ai/hackathon ; https://www.okx.ai/tasks | H |
| 4 | Barker Yield Agent, ID 2012 | OKX.AI / X Layer | DeFi Yield/Portfolio mgmt | Stablecoin yield indices, AI advisor, risk signals | From 0.001 USDT | 373 sold, 4.9 rating (≤ ~$0.37 at the floor price) | 2026-09-28 | https://www.okx.ai/agents | M |
| 5 | Asia Pulse, ID 5537 | OKX.AI / X Layer | Signals & Data/Analytics | Asian crypto/equity intelligence: Korean markets, funding, on-chain | From 0.03 USDT | 29 sold, 5.0 rating | 2026-09-28 | https://www.okx.ai/agents | M |
| 6 | Polydesk, ID 5427 | OKX.AI / X Layer | Prediction markets | Ranks Polymarket LP-reward opportunities | Pay per use (price not shown) | 23 sold, 4.5 rating | 2026-09-28 | https://www.okx.ai/agents | M |
| 7 | CertiK (OKX.AI service) | OKX.AI / X Layer | Risk/Security/Audit | Token security scans, risk scoring, transaction analysis | 0.001 USDT per call | none public | listing Jul–Sep 2026 | https://www.okx.com/en-us/learn/okx-ai-2 ; https://en.cryptonomist.ch/2026/09/09/okx-ai-agent-marketplace/ | M |
| 8 | Argus | OKX.AI / X Layer | Risk/Security/Audit | Smart-contract risk scanner | 0.1 USDT per call | 4,650 units (≤ ~$465) | ~Jul 2026 | https://leolabs.me/blog/ai-agent-paying-for-services/en/ | L–M |
| 9 | ChainSentry | OKX.AI / X Layer | Risk/Security/Audit | BSC token risk due diligence (task-market job) | 0.05 USDT per task | 1 task visible, in progress; no aggregate | 2026-09-28 | https://www.okx.ai/tasks | L |
| 10 | Saena Signal Ops | OKX.AI / X Layer | Signals & Data/Analytics | BTC market research brief | 0.05 USDT per task | 1 task visible; no aggregate | 2026-09-28 | https://www.okx.ai/tasks | L |
| 11 | Bell Ringer | OKX.AI / X Layer | Signals & Data/Analytics | "Anti-FOMO" analysis of NVDA/TSLA and US tech tokens | Free (tasks listed at 0) | 2 tasks visible (1 completed); no revenue | 2026-09-28 | https://www.okx.ai/tasks | L |
| 12 | Newsliquid (NewsLiquid) | OKX.AI / X Layer | Signals & Data/Analytics | Market news, social data, X influencer/audience profiling | Pay-per-call (price not disclosed) | none public (named launch partner) | Jul–Sep 2026 | https://www.okx.com/en-us/learn/okx-ai-2 | M |
| 13 | CoinMW | OKX.AI / X Layer | Signals & Data/Analytics | Aggregates public data from X, Instagram, TikTok, Reddit, YouTube | Pay-per-call | none public | Sep 2026 | https://en.cryptonomist.ch/2026/09/09/okx-ai-agent-marketplace/ | M |
| 14 | AgentFund, ID 6023 | OKX.AI / X Layer | Trading/Execution | Watches X Layer Uniswap v4 and ERC-20 flows; user-approved trade signals | Pay-per-call (price not retrieved) | none public (detail page returned 404 to fetch) | Sep 2026 (search index) | https://www.okx.ai/agents/6023 | L |
| 15 | Moss AI, ID 2327 | OKX.AI / X Layer | Trading/Execution | Turns natural-language trading style into self-evolving trading agent (30+ params) | Pay-per-call (price not retrieved) | none public (detail page 404 to fetch) | Sep 2026 (search index) | https://www.okx.ai/agents/2327 | L |
| 16 | ShieldSuite, ID 4959 | OKX.AI / X Layer | Risk/Security/Audit (inferred from name only; function **not verified**) | Not retrieved | Not retrieved | none public | Sep 2026 (search index) | https://www.okx.ai/agents/4959 | L |
| 17 | TinyDock | OKX.AI / X Layer | Other (agent infra: sandboxed code execution) | Runs Python/Node in Firecracker microVMs for other agents | 0.01 USDT per run | none public | Sep 2026 | https://www.okx.com/en-us/learn/okx-ai-2 | M |
| 18 | PixelBrief | OKX.AI / X Layer | Other (brand kit generation; non-fintech baseline) | Generates brand kits | 0.02 USDT | 21,690 units (≤ ~$434), the top count in Leo Labs' snapshot | ~Jul 2026 | https://leolabs.me/blog/ai-agent-paying-for-services/en/ | L–M |
| 19 | Leo Labs (Agent ID 3977; 9 services incl. BaZi reading) | OKX.AI / X Layer | Other | Solo builder's services; BaZi = 385 units @ 0.5 USDT | 0.003–1 USDT per call | **Actual on-chain revenue: 0.8 USDT / 10 tx** across 25 days | Jul 13–29, 2026 | https://leolabs.me/blog/ai-agent-paying-for-services/en/ | H (first-hand, on-chain verifiable) |
| 20 | Pools Sentine[l] | OKX.AI Trading Hackathon | Trading/Execution | Live-trading agent (strategy details not retrieved) | Not retrieved | 2nd place ($7,000) on live PnL; ≥300 USDT capital | Aug 11–25, 2026 | https://www.okx.ai/hackathon | M |
| 21 | 磐衡量化 (Panheng Quant) | OKX.AI Trading Hackathon | Trading/Execution | Quant live-trading agent | Not retrieved | 3rd place ($4,500) on live PnL | Aug 11–25, 2026 | https://www.okx.ai/hackathon | M |

### B. X Layer / OKX hackathon agents (live status not independently confirmed)

| # | Name | Platform/chain | Niche | What it does (≤12 words) | Monetization model & price | Revenue/usage metric (with number) | Metric date | Source URL | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| 22 | XSight (by @Krava491) | X Layer | Trading/Execution + Payments/x402 | Autonomous trading agent that charges per API call via x402 | x402 pay-per-call (price not retrieved) | none public; won "Best x402 implementation" at X Layer Arena | 2026 (tweet; exact date not retrieved) | https://x.com/XLayerOfficial/status/2048021007047573638 | L–M |
| 23 | Helios (@0xheliosfi) | X Layer | DeFi Yield/Portfolio mgmt | Self-sustaining multi-agent DeFi economy (four sovereign agents) | Not retrieved | none public; won "Most Active Agent" at X Layer Arena | 2026 | https://x.com/XLayerOfficial/status/2048021007047573638 | L–M |
| 24 | omni_lp (@omni_lp) | X Layer | DeFi Yield/Portfolio mgmt | 24/7 Uniswap V3 concentrated-liquidity rebalancing agent | Not retrieved | none public; won "Best Uniswap Integration" | 2026 | https://x.com/XLayerOfficial/status/2048021007047573638 | L–M |

### C. OKX first-party agent infrastructure (context: rails, not competitors)

| # | Name | Platform/chain | Niche | What it does (≤12 words) | Monetization model & price | Revenue/usage metric (with number) | Metric date | Source URL | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| 25 | OKX.AI marketplace (aggregate) | X Layer | Payments/x402 infra (marketplace) | Agent-to-agent marketplace: agent listings, task market, staked-arbiter disputes | Take rate not disclosed; USDT/USDG settlement | 10,000+ agent IDs; 4,000+ approved listings; 2,700+ active agents on one day; 20,000+ tasks (to Aug 10). **Task counter: $9,653 total volume, 81,236 tasks, 78,078 completed** | Aug 10, 2026; 2026-09-28 | https://www.okx.com/en-us/learn/okx-ai-2 ; https://www.okx.ai/tasks | H (counters) |
| 26 | OnchainOS (AI toolkit, Agentic Wallet, x402) | 60+ chains; x402 gas-free on X Layer | Payments/x402 infra | Wallet, DEX routing (500+ DEXs), market data and x402 for agents | Developer platform | 1.2B daily API calls; $300M daily trading volume; 12M monthly wallet users. These are platform-wide figures, not AI-agent-only | ~Mar 2026 | https://blockeden.xyz/blog/2026/03/07/okx-onchain-os-ai-agent-toolkit/ | M (secondary source repeating OKX's numbers) |
| 27 | OKX Agent Trade Kit (okx-trade-mcp / okx-trade-cli) | OKX CEX (MCP, local) | Trading/Execution | Open-source MCP/CLI: 167 tools for spot, swap, futures, options, bots | Free; OKX earns trading fees | GitHub: 450 stars, 70 forks | 2026-09-28 | https://github.com/okx/agent-trade-kit | H |

### D. Agent tokens and launchpads with fee revenue (not OKX-native; OKX listing **not verified this run**)

| # | Name | Platform/chain | Niche | What it does (≤12 words) | Monetization model & price | Revenue/usage metric (with number) | Metric date | Source URL | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| 28 | AIXBT | Base (Virtuals) | Signals & Data/Analytics | AI crypto-narrative/alpha signal agent | Token-gated access; treasury trading fees | Treasury trading-fee revenue $50k–$200k/month **at peak**; market cap ~$18–28M | early–Aug 2026 | https://dev.to/friendlygeorge/i-analyzed-150-agent-tokens-heres-what-actually-makes-money-its-not-tokens-3ho6 | L (blog, unsourced) |
| 29 | Virtuals Protocol | Base/Solana | Launchpad/Token infra | Tokenized agent launchpad; agent GDP | Launch and trading fees | 17,000+ agents; cumulative protocol revenue >$39.5M; 23,514 active wallets; $479M aGDP | Feb 2026 (wallets/aGDP); 2026 (revenue) | https://blockeden.xyz/blog/2026/03/07/okx-onchain-os-ai-agent-toolkit/ ; https://dev.to/friendlygeorge/i-analyzed-150-agent-tokens-heres-what-actually-makes-money-its-not-tokens-3ho6 | L–M |

**Row count: 29** (21 OKX.AI agents/ASPs, 3 X Layer hackathon agents, 3 OKX infra/aggregate rows, 2 external token agents). This is below the 30–40 target. Only about 12 rows carry a numeric usage figure, and only one (Leo Labs) has verified on-chain revenue.

## (b) General findings

- OKX AI beta went live Jun 30 / Jul 1, 2026, after closed testing with ~50 early ASPs. It has an agent marketplace plus a task marketplace, and pays out in stablecoins | https://cointelegraph.com/news/okx-ai-marketplace-autonomous-agent-economy ; https://thepaypers.com/crypto-web3-and-cbdc/news/okx-launches-marketplace-for-ai-agents-to-transact | Cointelegraph / The Paypers | Jul 2026 | H
- Settlement is in USDT or USDG. Standard services use instant pay-per-call; complex work uses escrow; disputes go to a staked evaluator network. **No platform take rate is disclosed** | https://www.okx.com/en-us/learn/okx-ai | OKX | 2026-07-01 | H
- Named launch/ecosystem partners: AWS, Ethereum Foundation dAI, Solana, XMTP, Opentensor, AltLayer, SlowMist, CertiK, NewsLiquid, CoinAnk, DAPPOS, Aethir, Kite AI, GenLayer, GOAT Network, Pieverse, XO, Orbofi, Starchild, NeoSoul, Unibase, Chiliz, Foregate, Algebra Finance, StraitsX | https://www.okx.com/en-us/learn/okx-ai | OKX | 2026-07-01 | H
- Traction by Aug 10, 2026: 10,000+ agent identities, 4,000+ approved listings, 2,700+ agents active in one day, 20,000+ tasks | https://www.okx.com/en-us/learn/okx-ai-2 | OKX | ~Aug–Sep 2026 | H
- Share of recorded sales by category: Software services 36%, Art creation 34%, Lifestyle ~14%, **Finance ~14%**. Fintech is not the biggest category by sales count | https://www.okx.com/en-us/learn/okx-ai-2 ; https://en.cryptonomist.ch/2026/09/09/okx-ai-agent-marketplace/ | OKX / The Cryptonomist | 2026-09-09 | M–H
- **Money volume is tiny:** the task marketplace counter shows $9,653 total volume across 81,236 tasks, about $0.12 per task | https://www.okx.ai/tasks | OKX.AI | fetched 2026-09-28 | H (counter as displayed)
- Frontend "sold" counts include unpaid OKX quality-sampling calls. One vendor's 9 services earned 0.8 USDT on-chain in 25 days while showing much higher counts | https://leolabs.me/blog/ai-agent-paying-for-services/en/ | Leo Labs (independent builder) | ~Aug 2026 | H (first-hand)
- Listing prices cluster at 0.001–1 USDT per call. The only visible subscription is 1M · Sparta at 20 USDT/month | https://www.okx.ai/agents ; https://www.okx.com/en-us/learn/okx-ai-2 | OKX.AI | 2026-09-28 | H
- Among visible finance/trading listings, TradeDesk (Chan-theory indicator, 8.58K sold) and CoinAnk (14.9K–16.6K) lead by count. Signals/data APIs are the highest-volume fintech sub-niche | https://www.okx.ai/agents | OKX.AI | 2026-09-28 | M
- OKX.AI Trading Hackathon S1 (Jul 31–Aug 25, 2026; $40K pool): ranked on live PnL % plus net PnL, minimum 300 USDT capital, accounting on OnchainOS or Agent Trade Kit. Winners: 1M · Sparta ($10K), Pools Sentine[l] ($7K), 磐衡量化 ($4.5K); ranks 4–40 get $500 each | https://www.okx.ai/hackathon | OKX.AI | Aug 2026 | H
- An earlier "OKX AI Genesis Hackathon" ($100K pool) targeted Agentic Service Providers; winner announcements began Aug 3 | https://x.com/XLayerOfficial/status/2081674886662299692 | X Layer (official X) | ~Jul 2026 | M
- Agent Trade Kit is an open-source MCP server plus CLI (MIT), 167 tools across 11 modules, runs locally with keys on the user's device; 450 stars | https://github.com/okx/agent-trade-kit | OKX GitHub | 2026-09-28 | H
- OnchainOS reports 1.2B daily API calls, $300M daily volume, 12M monthly wallet users, and gas-free x402 on X Layer. These are platform-wide figures, not agent-attributed | https://blockeden.xyz/blog/2026/03/07/okx-onchain-os-ai-agent-toolkit/ | BlockEden | 2026-03-07 | M
- Across the wider agent-token market, fewer than 5 of ~150 Virtuals agent tokens had external dollar revenue entering 2026 | https://dev.to/friendlygeorge/i-analyzed-150-agent-tokens-heres-what-actually-makes-money-its-not-tokens-3ho6 | DEV Community (blog) | 2026 | L

## (c) Leads (not pursued, out of budget)

- The OKX.AI agent detail pages (/agents/{id}) returned 404 to a plain fetch; they look client-rendered. A headless browser or an OKX.AI API would give per-agent sold counts, services and reviews for the 4,000+ listings. The finance and trading categories should be scraped by sold count.
- On-chain check: pull USDT/USDG transfers into known ASP wallets on the X Layer explorer (OKLink) to turn "sold" counts into real revenue. CoinAnk, TradeDesk and 1M · Sparta come first.
- Ranks 4–40 of Hackathon S1 (37 more live-PnL trading agents), plus the OKX AI Genesis Hackathon winner list (from Aug 3, 2026).
- An unnamed OKX.AI listing does quant rule-based signals and funding-fee monitoring on OKX USDT perps in conservative/neutral/aggressive tiers (seen in a search snippet). Needs a name.
- Launch partners with likely listings but no metrics: SlowMist (security), GenLayer (dispute resolution), Pieverse (x402 infra), Kite AI, DAPPOS, Starchild, Orbofi, Unibase, StraitsX (stablecoin/payments).
- X Layer Arena full winners list (tweet 2048021007047573638, "special prize winners").
- Pinata "OKX OnchainOS Agent Template" (https://pinata.cloud/blog/announcing-the-okx-onchainos-agent-template/). Possibly downstream agents.
- DefiLlama fees pages for AIXBT/Virtuals, plus OKX spot-listing verification for agent tokens. Not done this run.
- OKX Ventures AI-agent portfolio. Not searched this run.

## (d) Looked for but not found

- **Is there an official OKX agent marketplace with public listings? YES:** OKX.AI (https://www.okx.ai/agents, https://www.okx.ai/tasks), public since ~Jul 1, 2026. What was **not** found is a public per-agent *revenue* leaderboard. Only "sold" counts (which include sampling calls) and a platform-wide task volume counter are shown.
- The platform take rate or fee schedule on OKX.AI: not disclosed in any source retrieved.
- A Dune or DefiLlama dashboard for OKX.AI or x402 volume on X Layer: not found this run.
- Any OKX-ecosystem agent with publicly verified AUM/TVL under management: not found.
- A public user or active-account count for Agent Trade Kit (beyond GitHub stars): not found.
- OKX Ventures portfolio AI agents with revenue: not searched (budget).
- Compliance/KYC agents on OKX.AI: none seen in visible listings.
