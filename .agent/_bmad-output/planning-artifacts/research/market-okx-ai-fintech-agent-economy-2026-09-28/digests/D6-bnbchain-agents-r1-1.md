# D6 — BNB Chain / Binance-ecosystem agents & trading bots (round 1, digest 1)

Run date: 2026-09-28. Research firewall: no project files read. All numbers retrieved this run.
Primary quantitative source: DefiLlama API, pulled 2026-09-28:
- BSC revenue: `https://api.llama.fi/overview/fees/bsc?dataType=dailyRevenue&excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true` (BSC-only share of each protocol)
- BSC fees: same without `dataType` (fees = gross paid by users; revenue = kept by protocol)
- All-chain revenue/fees overview (`/overview/fees?dataType=dailyRevenue`) and `/summary/fees/<slug>` for single protocols.
"30d" = trailing 30 days ending ~2026-09-27. Unless noted, the $ figures are **BSC-only revenue**.

## (a) Table

| # | Name | Chain | Niche | What (≤12 words) | Monetization & price | Revenue/usage metric | Metric date | URL | Confidence | AI/LLM-driven? |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | GMGN | BSC + Sol/ETH/Base/others | Trading/Execution | Web/TG meme trading terminal: sniping, copy-trade, smart-money tracking | Per-trade fee (% of swap) | BSC revenue 30d **$10.65M** (24h $105.6k); BSC 1y $94.4M; all-chain 30d rev $42.6M | 2026-09-27 | https://gmgn.ai | High (DefiLlama) | unclear (brands "GMGN AI"; core is execution + analytics) |
| 2 | Flap.sh | BSC (+X Layer, Monad, Robinhood Chain) | Launchpad/Token infra | Bonding-curve token launchpad; #1 BSC fee generator | Trade/launch fees | BSC revenue 30d **$9.09M**; BSC fees 30d $38.8M (largest on BSC) | 2026-09-27 | https://flap.sh | High | no |
| 3 | fomo Wallet | BSC + Sol/Base/ETH/Monad | Trading/Execution | Social mobile trading app for memecoins | Per-trade fee | BSC revenue 30d **$2.96M**; all-chain rev 30d $31.1M | 2026-09-27 | https://fomo.family | High | no |
| 4 | Binance Alpha | BSC (+ETH, Base, others) | Launchpad/Token infra | Binance Wallet early-token trading/airdrop venue | Trade fees | BSC revenue 30d **$1.88M**; BSC 1y $17.5M | 2026-09-27 | https://www.binance.com/en/alpha | High | no |
| 5 | Predict.fun | BSC | Prediction markets | YZi-backed prediction market; deposits earn Venus yield | Trading fees | BSC fees 30d **$5.56M**, revenue 30d **$1.16M**; 1y rev $7.2M; >$1.8B cum. volume, >130k users (Apr 2026) | 2026-09-27 / Apr 2026 | https://predict.fun | High (fees) / Med (users) | no |
| 6 | Genius.fun | BSC | Launchpad/Token infra | Bonding-curve launchpad graduating to PancakeSwap Infinity | Trade/creator fees | BSC revenue 30d **$882k**; fees 30d $3.42M (new: 1y = 30d) | 2026-09-27 | https://genius.fun | High | no |
| 7 | Aster (Perps) | Off-chain matching / BSC & Aster chain | Trading/Execution | Perp DEX up to 1001x; "agent-ready" MCP server + Agent Skills | Trading fees | All-chain fees 30d **$5.90M** (revenue not pulled); agent MCP/Skills launched 2026-03-06 | 2026-09-27 / 2026-03-06 | https://www.asterdex.com | High (fees) / Med (agent launch, X post via search) | partial (agent integration, not an AI product itself) |
| 8 | MetaMask Wallet (swaps on BSC) | BSC + multi | Wallet/Assistant | Wallet swap-fee revenue on BSC | Swap fee | BSC revenue 30d $384k | 2026-09-27 | https://metamask.io | High | no |
| 9 | Axiom | BSC + Solana | Trading/Execution | YC-backed web trading terminal; added BSC | Per-trade fee | BSC revenue 30d **$223k**; BSC fees 30d $448k; all-chain rev 30d $18.2M | 2026-09-27 | https://axiom.trade | High | no |
| 10 | PancakeSwap Prediction | BSC | Prediction markets | BNB/CAKE up-down price prediction rounds | House fee | BSC revenue 30d $216k; 1y $5.0M | 2026-09-27 | https://pancakeswap.finance/prediction | High | no (has an "AI prediction" variant — unverified this run) |
| 11 | four.meme | BSC | Launchpad/Token infra | BSC's original meme launchpad; "Agentic Mode" AI agents launch memes | Launch/trade fees | BSC revenue 30d **$204k** vs 1y **$81.4M** (sharp decline) ; Agentic Mode launched ~2026-03 | 2026-09-27 / Mar 2026 | https://four.meme | High (rev) / Med (agent) | partial (Agentic Mode, Agent Skill framework, LLM chat-trading roadmap) |
| 12 | Maestro | BSC (largest chain) + ETH/Sol/others | Trading/Execution | Telegram trading/sniping bot | 1% per trade; premium subscription | BSC revenue 30d **$152k**; BSC 1y $6.9M; all-chain rev 30d $1.35M | 2026-09-27 | https://www.maestrobots.com | High | no |
| 13 | TermiX | BSC + Base | Payments/infra (agent commerce) | Agent-to-agent job marketplace/escrow settlement (Agent.family) | 1–3% protocol fee | DefiLlama category "AI Agents": BSC rev 30d **$145k**, all-chain 30d $227k, 1y $498k; 34k agents listed; $1M YZi Labs investment (May 2026) | 2026-09-27 / 2026 | https://www.agent.family | High (rev) / Med (agents) | yes |
| 14 | Base App | BSC + Base | Wallet/Assistant | Coinbase's social wallet; swap fees on BSC | Swap fee | BSC revenue 30d $111k | 2026-09-27 | https://base.app | High | no |
| 15 | OPINION (Opinion Labs) | BSC | Prediction markets | Orderbook prediction market, YZi-backed, raised $20M | Trading fees | BSC revenue 30d **$43.6k** vs 1y **$17.5M** (collapse or tracking change); $7B Dec-2025 volume; $653M weekly vol (Feb 2026, ~20% global share) | 2026-09-27 / Feb 2026 | https://opinion.trade | High (DefiLlama) / Med (vol) | no |
| 16 | Rabby Wallet | BSC + multi | Wallet/Assistant | Wallet swap fees on BSC | Swap fee | BSC revenue 30d $29k | 2026-09-27 | https://rabby.io | High | no |
| 17 | o1.exchange Trading Terminal | BSC + multi | Trading/Execution | Multi-chain trading terminal | Per-trade fee | BSC revenue 30d $13.3k; all-chain 30d $56k | 2026-09-27 | https://o1.exchange | High | no |
| 18 | NTM.ai | BSC | Other (SoFi) | Social-fi app tagged "SoFi" on DefiLlama | Fees | BSC revenue 30d $11.3k; 1y $156k | 2026-09-27 | https://ntm.ai | Med (identity not verified) | unclear |
| 19 | copyfomo | BSC + Sol/Base | Trading/Execution | Telegram copy-trading bot | Per-trade fee | BSC revenue 30d $8.1k; all-chain 30d $141k (new) | 2026-09-27 | (DefiLlama slug copyfomo) | High | no |
| 20 | Banana Gun | ETH/Sol/Base/BSC… | Trading/Execution | Telegram sniping bot | Per-trade fee | BSC revenue 30d **$0**; all-chain 30d $6.9k; 1y $2.69M — effectively exited BSC | 2026-09-27 | https://bananagun.io | High | no |
| 21 | Terminal | BSC + Sol/ETH/Base | Trading/Execution | Telegram trading bot | Per-trade fee | BSC revenue 30d $1.2k; all-chain 30d $2.63M | 2026-09-27 | (DefiLlama slug terminal) | High | no |
| 22 | Ave.ai | BSC + multi | Signals & Data | DEX analytics + trading terminal ("AI" brand) | Trade fees | BSC revenue 30d ~$1; BSC 1y $558k; all-chain 30d $35k | 2026-09-27 | https://ave.ai | High | unclear |
| 23 | Myriad Markets | BSC (migrated) | Prediction markets | Prediction market with order book + CLI tools for AI agents | Trading fees | BSC revenue 30d $176; 1y $57.7k | 2026-09-27 | https://myriad.markets | High (rev) / Med (agent CLI) | partial (agent CLI) |
| 24 | Binance Agent OS / Agentic Wallet / Skills Hub | Binance CEX + BNB Chain | Wallet/Assistant (agent infra) | Lets AI agents (ChatGPT/Claude Code) trade via Binance under user limits | Free; Binance earns trading fees | Launched 2026-08-20 (Agentic Wallet Apr 2026); 300M+ Binance registered users (reach, not usage) | 2026-08-20 | https://www.binance.com/en/skills | Med (TechCrunch via search) | yes |
| 25 | Pieverse (x402b) | BSC | Payments/infra | x402 facilitator for gasless agent payments with compliant receipts | Facilitator/payment fees; token | ~500k tx in one week (+10,780% vs prior 4 wks); $10M raised; 920k monthly users on BNB Chain dashboard | Oct 2025 (tx) / 2026-09 (users) | https://pieverse.io | Med | yes (agent payments) |
| 26 | OptimAI | opBNB | Other (AI agent / data) | AI agent network (BNB AI dashboard rank #1) | Token/points | 67.4k DAU, 488k WAU, 593k MAU | 2026-09-28 (page) | https://www.bnbchain.org/en/solutions/ai-agent | Med (BNB Chain self-reported) | yes |
| 27 | SwarmBase | opBNB | Launchpad/Token infra (agent platform) | AI agent platform | unclear | 154k DAU, 252k WAU, 419k MAU | 2026-09-28 | same | Med | yes |
| 28 | ARK DeFAI | BSC | Trading/Execution (DeFAI) | DeFAI agent | unclear | 14.2k DAU, 103k WAU, 200k MAU | 2026-09-28 | same | Med | yes |
| 29 | Alaya AI / DGrid AI / Dataline / Decentralized Intelligence / Cubed / Rugtector | opBNB/BSC | Signals & Data / Risk (Rugtector) / infra | AI data & infra projects listed on BNB AI dashboard | unclear (mostly token/points) | MAU: Alaya 1.69M, Cubed 506k, Rugtector 111k, DGrid 91k, Decentr. Intelligence 84k, Dataline 60k | 2026-09-28 | same | Med (wallet-activity, likely incentive-driven) | yes |
| 30 | ERC-8004 agent registry on BNB Chain (BNBAgent SDK, 8004scan, Agent0) | BSC | Launchpad/Token infra (identity) | Agent identity/reputation standard; BNB Chain has most agents | Free infra | ~39k ERC-8004 agents on BNB (vs 28–30k Base/ETH); peak 523k agent tx/day (Mar 10) and $18.1M agent DEX volume/day (Mar 11) | Mar–2026 (reported mid-2026) | https://www.bnbchain.org/en/solutions/ai-agent | Med | yes |

Rows: 30 (row 29 bundles 6 dashboard projects).

## (b) Findings

- **Money on BSC is in execution + launchpads, not "AI agents".** Top BSC revenue (30d to 2026-09-27): GMGN $10.65M, Flap.sh $9.09M, fomo $2.96M, Binance Alpha $1.88M, Predict.fun $1.16M, Genius.fun $0.88M. Every one is a trading terminal / launchpad / prediction market; none is LLM-driven. (DefiLlama BSC revenue API.)
- **Only one DefiLlama "AI Agents" protocol earns meaningfully on BSC: TermiX** — $145k BSC revenue 30d ($227k all-chain), agent-to-agent job escrow at 1–3% fee. Other BSC "AI Agents" entries (Calculus 1y $9.7k, Xeleb 1y $6.3k, Holoworld launchpad 1y ~$5) are negligible. For comparison Virtuals (Base) all-chain 30d rev $597k. (DefiLlama; KuCoin/Bitget news on TermiX mainnet and YZi $1M.)
- **Telegram bots are shrinking on BSC.** Maestro still earns $152k/30d on BSC (1y $6.9M), Banana Gun $0 on BSC, Terminal $1.2k; web terminals (GMGN, Axiom, fomo) took share. Axiom's BSC revenue ($223k/30d) is small vs its Solana base.
- **Launchpad rotation is brutal:** four.meme 1y BSC revenue $81.4M but only $204k in last 30d; Flap.sh now dominates. OPINION similar: 1y $17.5M, 30d $43.6k (could be decline or DefiLlama adapter change — verify). Predict.fun is the live prediction-market earner ($5.6M fees/30d).
- **Prediction markets are the BNB growth category:** $30B cumulative volume by ~Mar 2026; Opinion did $7B in Dec 2025; Predict.fun integrated in Binance Wallet and acquired Probable; Myriad ships CLI tools for AI agents (blockchain.news; The Defiant/Messari via search).
- **Binance is building agent rails, which is both opportunity and threat:** Agent OS (2026-08-20), Agentic Wallet (Apr 2026), Skills Hub, x402 facilitator API; users connect ChatGPT/Claude Code with per-agent permissions in subaccounts (TechCrunch, 2026-08-20). Aster (perps, $5.9M fees/30d) went "agent-ready" with an MCP server + Agent Skills (2026-03-06). Four.meme added Agent Skill framework + Agentic Mode (Mar 2026).
- **Agent count ≠ revenue:** BNB Chain leads ERC-8004 registrations (~39k agents; 1 in 3 on-chain agents) with peak $18.1M/day agent DEX volume (Mar 2026), but no agent product except TermiX shows DefiLlama-tracked revenue > $100k/30d. Dashboard MAUs (OptimAI 593k, Alaya 1.69M) are wallet-activity counts, likely incentive/airdrop-driven.
- **x402 on BNB:** Pieverse x402b ~500k tx in one week (Oct 2025) — usage burst around token TGE; no revenue number found.
- Implication (analyst inference, not evidence): the paying traders on BNB pay per-trade fees to execution venues (terminal/bot/launchpad/prediction). An AI agent that plugs into Binance Skills / Aster MCP / Predict.fun and monetizes by trade fee or referral rebate aligns with where money already flows; standalone "AI agent" tokens/platforms on BSC show little revenue.

Sources: DefiLlama API (above); https://www.bnbchain.org/en/solutions/ai-agent ; https://thedefiant.io/news/defi/bnb-smart-chain-becomes-home-to-most-erc-8004-ai-agents ; https://crypto.news/bnb-chain-leads-all-blockchains-for-ai-agents/ ; https://www.bitget.com/news/detail/12560605493294 ; https://www.kucoin.com/news/flash/chainaware-and-termix-partner-to-scale-ai-agent-economy-on-bnb-chain ; https://www.kucoin.com/news/flash/pieverse-to-launch-x402b-protocol-on-bnb-chain-with-gas-free-payments-and-auditable-receipts ; https://x.com/Aster_DEX/status/2029904876768207289 ; https://thedefiant.io/news/defi/top-bnb-chain-prediction-market-opinion-raises-usd20-million ; https://blockchain.news/news/bnb-chain-prediction-markets-30b-volume-milestone ; https://practicalcrypto.net/en/prediction-markets/predict-fun.html ; https://www.kucoin.com/news/flash/four-meme-to-launch-agentic-mode-ai-agent-meme-product-on-bnb-chain ; https://www.bitget.com/news/detail/12560605234239 ; https://techcrunch.com/2026/08/20/binance-now-lets-ai-agents-trade-but-keeping-them-in-check-is-largely-up-to-users/ ; https://blockchain.news/news/binance-agent-os-ai-integration ; https://www.altcoinbuzz.io/bitcoin-and-crypto-guide/binance-wallet-launches-meme-rush-for-fair-token-discoveries/

## (c) Leads (not pursued, budget)
- Aster Perps revenue (not just fees) and share of volume via API/agents: `/summary/fees/aster-perps?dataType=dailyRevenue`.
- AEGIS "AI Trading on AsterDEX" (tradewithaegis.com) — AI trading agent on Aster; no metrics retrieved.
- Binance Agent OS adoption numbers (agents connected, volume) — none published in retrieved snippets.
- Opinion 30d collapse on DefiLlama: check adapter/methodology vs Dune.
- Dune dashboards for ERC-8004 agents on BSC (agent DEX volume trend after March peak).
- Unibase, ChainGPT, MyShell on BNB — no revenue data found; ChainGPT is marketed as DeFAI with trading bots.
- BSC copy-trading/TG bots listed by CoinCodeCap (Dbotx, MevX, AutoSnipe, BullX) — check DefiLlama/Dune for BSC volume.
- Binance Wallet Meme Rush (with four.meme) volume; Genius.fun ownership/relationship to "Genius" trading terminal.
- PancakeSwap "AI prediction" market product revenue split.

## (d) Not found / unverified
- Sigma bot, Debot/Dbotx on BSC: no DefiLlama BSC entries or metrics retrieved.
- MyShell on BNB: no DefiLlama entry; no metrics.
- BNB Chain MCP server usage numbers: not found (BNBAgent SDK listed, no usage).
- Revenue for any BNB Chain dashboard AI project (OptimAI, SwarmBase, ARK DeFAI, Pieverse): none found.
- Binance Alpha "AI agent token fee revenue" specifically: not found; only Binance Alpha aggregate revenue.
- GMGN/Axiom BSC user counts: not retrieved (revenue only).
