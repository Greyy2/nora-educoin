# D6 — Binance official AI-agent stack (r1-1)

Run date: 2026-09-28. Tool calls: 20 (budget met). Research firewall: web evidence only.
Confidence: H = official/primary source or 2+ independent sources; M = single reputable secondary; L = press-release reprint, SEO or aggregator source, or unclear attribution.
Class: F = fact, M = metric, P = pricing/monetization, D = date, G = gap/inference.

## (a) Findings

| claim | URL | publisher | pub_date | confidence | class |
|---|---|---|---|---|---|
| Binance launched **Agent OS** on 2026-08-20. It is a developer platform that connects AI apps to Binance trading, market data, wallet, payments and chain. | https://techcrunch.com/2026/08/20/binance-now-lets-ai-agents-trade-but-keeping-them-in-check-is-largely-up-to-users/ | TechCrunch | 2026-08-20 | H | F/D |
| Agent OS components: MCP server, Binance APIs, Binance Wallet Agentic Hub, Binance x402, payment facilitator API, Skill Hub and subaccounts. It supports ChatGPT, Claude Code, Codex and Cursor. | same as above + https://www.prnewswire.com/apac/news-releases/binance-introduces-agent-os-to-connect-ai-applications-to-financial-infrastructure-302865254.html | TechCrunch / PR Newswire APAC | 2026-08-20 / page dated 2026-09-02 (APAC re-release; dates conflict) | H | F |
| Official URLs: binance.com/agent-os; MCP endpoint https://agent.binance.com/mcp/agentic; docs https://developers.binance.com/en/docs/agent-native/mcp-server | PR Newswire (above) | Binance via PR Newswire | 2026-09-02 | H | F |
| Agent OS sits under **"Binance Intelligence"**, Binance's strategic initiative for AI products. Quote from Jeff Li, VP Product. | PR Newswire (above) | Binance | 2026-09 | H | F |
| Agentic Wallet caps: swaps $50k/day, DeFi $100k/day, **x402 payments $20/day**. Trading subaccounts have no separate cap. Withdrawals are blocked by default. | TechCrunch (above) | TechCrunch | 2026-08-20 | H | F |
| Binance says it has "limited visibility" into how agents make decisions. Users carry the risk. | TechCrunch (above) | TechCrunch | 2026-08-20 | H | F |
| Competitors: Kraken (Mar 2026), Coinbase (Jun 2026) and OKX (2026) launched similar agent platforms. | TechCrunch (above) | TechCrunch | 2026-08-20 | M | F |
| **AI Agent Skills v1** launched 2026-03-03 (updated 03-10) with 7 skills: Spot, Query Address Info, Query Token Info, Crypto Market Rank, Meme Rush, Trading Signal, Query Token Audit. Named frameworks include OpenClaw and Claude. | https://www.binance.com/en/support/announcement/detail/bafb9dda6cbb47d5882a4090c31d4c64 | Binance | 2026-03-03 | H | F/D |
| A second wave added **13 new skills**: COIN-M futures, options, algo execution, fiat, payments, yield and RWA. | https://www.binance.com/en/academy/articles/binance-ai-agent-skills-hub-13-new-skills ; https://fxnewsgroup.com/forex-news/cryptocurrency/binance-launches-13-new-ai-agent-skills/ | Binance Academy / FX News Group | date not retrieved | M | F |
| **Skills Hub listing** at binance.com/en/skills. The fetch reported "23 skills", but only 20 were enumerated. All are Binance-official and "security-reviewed before listing". The page shows **no install counts, ratings or prices**. | https://www.binance.com/en/skills | Binance | fetched 2026-09-28 | H (listing) / M (count) | F/G |
| GitHub repo binance/binance-skills-hub has about 1,000 stars, 233 forks, 61 PRs and 166 commits. Third parties can submit a skill with a SKILL.md through a PR. It says it is for "any agent, any framework, any chain". It has no monetization mechanism. | https://github.com/binance/binance-skills-hub | GitHub/Binance | fetched 2026-09-28 | H | M/F |
| **Wallet Agentic Hub** lists 12 official tools: Agentic Wallet, Meme Rush, Token Info, Advanced Signal, Address Info, Security Audits, Tokenized Securities, Market Rank, Prediction Market (predict.fun), x402 Payment, DeFi, and Perp Trading (coming soon). It shows no usage metrics or prices. The wallet uses MPC keyless custody with user-set limits. | https://web3.binance.com/en/agentic-hub ; https://developers.binance.com/en/docs/products/agentic-wallet/welcome | Binance | fetched 2026-09-28 | H | F |
| **Binance x402** launched 2026-05-19. It is a Binance Pay facilitator for HTTP-402 payments on BNB Chain in U, USDT, USD1 and USDC (eip3009, permit2). Its stated purpose is to let developers and merchants *monetize APIs, data and agent tools*. No facilitator fee was disclosed. | https://blockchain.news/news/binance-x402-http-native-payments-bnb-chain ; https://fxnewsgroup.com/forex-news/cryptocurrency/binance-introduces-binance-x402-enabling-http-native-payments-on-bnb-chain/ | Blockchain.News / FXNG | 2026-05-19 | M | F/D |
| **Binance AI Pro** (beta) launched 2026-03-25. It is an AI trading agent in an isolated virtual subaccount with no withdrawal permission. It supports ChatGPT, Claude, Qwen, MiniMax and Kimi. **Beta price $9.99/mo (list $29.99)** with 5M credits/month and a 7-day free trial. | https://www.analyticsinsight.net/press-release/binance-beta-launches-binance-ai-pro-bringing-ai-agentic-trading-to-users | Analytics Insight (press release) | 2026-03 | M | P/D |
| An unnamed Binance AI tool (live market + account data in one interface) "surpassed **280,000 daily calls** within weeks of launch". The article cites a Binance announcement; which product this is remains unclear. | https://en.cryptonomist.ch/2026/09/17/binance-ai-trading-tool/ | The Cryptonomist | 2026-09-17 | L-M | M |
| An AI Assistant widget gives token summaries (BSC, SOL, BASE) covering sentiment, ratings and timeline. | search snippet (Medium, Feb 2026) | Medium | 2026-02 | L | F |
| Binance has 300M+ registered users. | TechCrunch (above) | TechCrunch | 2026-08-20 | H | M |
| **Copy trading payouts to lead traders**: Spot gets 10% profit share + 10% fee commission. Futures gets up to 30% profit share + 10% fee commission. New leads get 15% for 1 week through the Growth Plan. Becoming a lead requires >500 USDT and KYC. | https://www.binance.com/en/support/faq/binance-futures-copy-trading-lead-trader-growth-plan-3160c961b2734d1cbb5342d1e86c6cdb ; https://coinbureau.com/review/binance-copy-trading-review | Binance / Coin Bureau | 2026 | M-H | P |
| A third-party 90-day study found 72.45% of Binance lead traders delivered positive follower PnL (+572,979.94 USDT total). Follower event win rate was 66.5%. | https://yieldfund.com/is-copy-trading-profitable-a-90-day-multi-exchange-study | YieldFund | undated | L | M |
| **Binance Link (broker) program**: 30–50% trading-fee rebate on orders sent with your Link ID through the API. Applies only to new users (no referral code, VIP < 3) who sign up after you join. Rebate data is exposed through the API. | https://www.binance.com/en/link ; https://www.binance.com/en/support/faq/how-to-apply-for-binance-link-program-api-rebate-2ae5b076d3834e1480f78c19898b213f | Binance | evergreen | H | P |
| Binance.US has a separate API partner program for automated trading platforms. | https://support.binance.us/en/articles/9843317-introducing-the-binance-us-api-partner-program-for-automated-trading-platforms | Binance.US | n/a | M | P |
| **BNB Hack: AI Trading Agents** (with CMC and Trust Wallet), $36k pool: $24k autonomous track, $6k strategy track, $6k special prizes. Ran 2026-06-03 to 07-06. Extras: CMC Pro credits and Trust Wallet Reference Agent listing. | https://chainwire.org/2026/06/03/bnb-chain-launches-36000-hackathon-to-advance-on-chain-ai-trading-agents/ ; https://blockchain.news/news/bnb-hackathon-ai-trading-agents-winners | Chainwire / Blockchain.News | 2026-06-03 | H | P/D |
| **"Build the Era"** hackathon (2026-08-05) seeks the official **BNB Agent Studio marketplace**. Prize pool >$40k; main winner gets 30k USDT plus adoption as a standalone product. Submissions closed 2026-09-09; winners due 2026-11-05. | https://www.bnbchain.org/en/blog/build-the-era-build-the-official-bnb-agent-studio-marketplace ; https://chainwire.org/2026/08/05/bnb-chain-launches-build-the-era-hackathon-to-find-the-official-bnb-agent-studio-marketplace/ | BNB Chain / Chainwire | 2026-08-05 | H | P/D |
| **>200,000 AI agents are registered on BSC under ERC-8004**, about 60% of registered agents across 26 networks, according to BNB Chain. Its reference agent categories are monitoring, grid, health-factor and yield. | same as above | BNB Chain (self-reported) | 2026-08-05 | M | M |
| Trading bots: Binance offers 8 bot types (Spot Grid, DCA, Rebalancing, Algo…). One source says "74% of new bot users in 2026 start with grid or DCA". No official "X million bots" figure was found. | https://www.binance.com/en/trading-bots ; https://www.binance.com/en/square/post/322020070064370 | Binance / Binance Square (UGC) | 2026 | L (74%) | M/G |
| Bot and copy-trade volume counts toward VIP spot volume. | Binance VIP announcement (search result) | Binance | n/a | M | F |

## (b) Named Binance agents / skills / bots / products

| Name | Type | Niche | What (≤12 words) | Monetization & price | Usage/revenue metric | Date | URL | Confidence |
|---|---|---|---|---|---|---|---|---|
| Agent OS | official | Dev platform | Connects AI agents to Binance trading, wallet, payments, data | Free; Binance earns trading fees | n/a (300M+ exchange users) | 2026-08-20 | https://binance.com/agent-os | H |
| Binance MCP server (remote) | official | Infra | Remote MCP endpoint for agent tools | Free | n/a | 2026-08-20 | https://agent.binance.com/mcp/agentic | H |
| Binance Skills Hub | official (open to PRs) | Skill registry | Catalogue of ~20–23 Binance agent skills | Free, open source | ~1,000 GH stars, 233 forks | 2026-03-03 | https://www.binance.com/en/skills | H |
| binance (Spot/Futures/Convert skill) | official | CEX trading | Spot, USDⓈ-M futures, convert via binance-cli | Trading fees | n/a | 2026-03 | https://www.binance.com/en/skills | H |
| binance-onchain-copy-trader | official | Copy trading | Builds address-monitor→signal→order pipelines with TP/SL | On-chain fees | n/a | 2026 | https://www.binance.com/en/skills | H |
| binance-trading-signal / trading-signal | official | Signals | Smart-money signals, custom strategies, backtesting, reports | Free | n/a | 2026-03 | https://www.binance.com/en/skills | H |
| binance-leaderboard | official | Analytics | On-chain wallet PnL leaderboard, Gem Hunter | Free | n/a | 2026 | https://www.binance.com/en/skills | H |
| meme-rush | official | Meme launches | Real-time Pump.fun/Four.meme launches, AI narratives | Free | n/a | 2026-03 | https://www.binance.com/en/skills | H |
| query-token-audit | official | Security | Detects scam/honeypot contracts | Free | n/a | 2026-03 | https://www.binance.com/en/skills | H |
| binance-sports-ai-analyzer | official | Prediction | World Cup match predictions + prediction market trading | Market fees | n/a | 2026 | https://www.binance.com/en/skills | H |
| square-post | official | Social | Agent publishes posts/articles/video to Binance Square | Free | n/a | 2026 | https://www.binance.com/en/skills | H |
| p2p / fiat / onchain-pay / payment-assistant | official | Fiat/payments | P2P ads, onramp, QR/PIX payments | Payment/spread fees | n/a | 2026 | https://www.binance.com/en/skills | H |
| Agentic Wallet | official | Wallet | MPC keyless agent wallet with user spend limits | Swap fees; caps $50k/$100k/day | n/a | ~2026-05 | https://web3.binance.com/en/agentic-hub | H |
| Binance x402 | official | Agent payments | Binance Pay facilitator for HTTP-402 stablecoin payments | Fee undisclosed; enables per-call API sales | n/a | 2026-05-19 | (fxnewsgroup / blockchain.news) | M |
| Binance AI Pro (beta) | official | Retail AI trader | User-configured AI agent trading in isolated subaccount | $9.99/mo beta (list $29.99), 7-day trial | n/a | 2026-03-25 | https://www.binance.com/ | M |
| Unnamed Binance AI data/account tool | official | Assistant | Live market + account data in one interface | Free? | 280,000 daily calls | 2026-09-17 | https://en.cryptonomist.ch/2026/09/17/binance-ai-trading-tool/ | L-M |
| AI Assistant widget | official | Research | AI token summaries (sentiment, ratings, timeline) | Free | n/a | 2026-02 | (Medium snippet) | L |
| Trading Bots (Grid, DCA, Rebalancing, Algo…) | official | Automation | 8 built-in bot types | Trading fees | "74% new bot users start grid/DCA" (UGC) | 2026 | https://www.binance.com/en/trading-bots | L |
| Copy Trading (Spot/Futures) | official platform, 3rd-party lead traders | Social trading | Followers copy lead traders | Lead: 10% spot / ≤30% futures profit share + 10% fee commission | 72.45% leads positive, +572,979.94 USDT, 90 days (3rd-party) | 2026 | https://www.binance.com/en/copy-trading/be-leader | M |
| Binance Link (broker) program | official program | Distribution/monetization | Brokers/apps earn rebates on referred API trading | 30–50% fee rebate | n/a | evergreen | https://www.binance.com/en/link | H |
| BNB Agent Studio marketplace (future) | 3rd-party winner → official | Agent marketplace | Hackathon-chosen agent trading marketplace on BSC | 30k USDT prize + adoption | 200k+ ERC-8004 agents on BSC | winners 2026-11-05 | https://www.bnbchain.org/en/blog/build-the-era-build-the-official-bnb-agent-studio-marketplace | H |

## (c) Public listing URLs to scrape
- https://www.binance.com/en/skills — official Skills Hub list. It has no counts, ratings or prices.
- https://www.binance.com/en/skills/detail/binance-web3/binance-agentic-wallet — URL pattern for a skill detail page (`/en/skills/detail/<group>/<skill>`).
- https://web3.binance.com/en/agentic-hub — Wallet Agentic Hub, 12 tools, no metrics.
- https://github.com/binance/binance-skills-hub (plus `/tree/main/skills`) — stars, forks, PRs. Open PRs are the only place third-party skill submissions would show up.
- https://www.binance.com/en/copy-trading — **the only public Binance listing with per-agent/trader earnings data**: lead-trader PnL, ROI, AUM and copier counts. It is JS-rendered, so it needs a headless browser.
- https://www.binance.com/en/trading-bots — the bot marketplace (strategy lists with ROI and copy counts are likely; not verified this run).
- https://www.bnbchain.org/en/hackathons/smart-money-era?tab=prizes — hackathon submissions and prizes.

## (d) Leads
1. The copy-trading and trading-bot marketplace pages probably expose per-strategy ROI and copier counts. These are the best "earning money" proxies on Binance. Scrape them.
2. After 2026-11-05, check the BNB Agent Studio marketplace winner. It would be the first public third-party agent marketplace in the Binance ecosystem.
3. Pair x402 with Skills Hub: a small team could sell a paid data or signal skill per call via x402 on BNB Chain. The facilitator fee and the $20/day agent-wallet cap on x402 both need checking.
4. Binance Link rebates of 30–50% are the most concrete revenue path for a third-party agent that routes users' API trades. The "new users only" and "VIP<3" conditions limit it.
5. Binance AI Pro at $9.99–29.99/mo sets a retail price anchor for AI trading agents. Binance is competing directly with third parties here.
6. Find the source of the 280k daily calls figure (a Binance announcement around Sept 2026) and the date of the 13-skill launch.
7. The TechCrunch comparison of Kraken, Coinbase and OKX agent platforms is useful for the OKX-vs-Binance decision.

## (e) Not found (this run)
- Any public third-party agent/skill marketplace on Binance with install counts, ratings or prices. The Skills Hub is official-only, open-source and free.
- Official metrics for Agent OS: agents connected, API/agent trading volume, skill installs.
- An official "X million bots created" count or bot trading volume.
- The Binance x402 facilitator fee. The exact launch date of the 13-skill wave.
- Binance Square AI features, "Bibi" assistant branding, Binance Alpha AI-agent token lists or metrics (not searched; budget spent).
- Any Binance-run grant program for Agent OS builders (only BNB Chain hackathons found).
