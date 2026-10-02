# D5 — Market, unit economics, risk & regulation (round 1, agent 1)

Accessed: 2026-09-28 for all sources. Budget: ~22 tool calls, 14 distinct sources.
Confidence scale: H = primary/official, recent; M = reputable secondary or primary with caveats; L = marketing, aggregator, unsourced, or snippet-only (not fetched).
Note: several claims below come from search-result snippets and were not fetched in full; they are marked (snippet).

## (a) Findings

### Pricing / unit economics
- CoinGecko API: Demo free (10k calls/mo, 100/min); Basic $35/mo (100k); Analyst $129 (500k); Lite $499 (2M); Pro $999 (5–15M); overage $0.0005/call ($250 per 500k). No standalone pay-per-call/x402 option listed. | https://www.coingecko.com/en/api/pricing | CoinGecko | live page | accessed 2026-09-28 | H | pricing
- Nansen offers x402 pay-per-call in USDC on Base/Solana at ~$0.01–$0.05 per call, no subscription or approval gate (snippet; launched ~Apr 2026). | https://docs.nansen.ai/getting-started/agentic-payments/x402-payments ; https://www.crowdfundinsider.com/2026/04/274494-blockchain-analytics-firm-nansen-enhances-onchain-data-access-with-pay-per-call-model/ | Nansen / Crowdfund Insider | 2026-04 | accessed 2026-09-28 | M | pricing
- A public GitHub issue on nansen-cli is titled "Your x402 numbers for the last 30 days (4,302 calls, 19-258 paying wallets)". That suggests even a top-brand data API draws modest x402 volume. The page returned 404 when fetched, so the numbers are unverified. | https://github.com/nansen-ai/nansen-cli/issues/625 | GitHub (unknown poster) | 2026 | accessed 2026-09-28 | L | metric
- GoPlus token security API has a free tier (30 calls/min). Paid Pro/Ultra/Enterprise plans are bought with credits, payable in GPS token or fiat. No public price list was found, so pricing appears to be by quote/token. | https://docs.gopluslabs.io/reference/api-overview ; https://gopluslabs.io/en/token-security-api | GoPlus | live | accessed 2026-09-28 | M | pricing
- Banana Gun: ~$52M annualized revenue (4-week rolling, late Mar 2026), of which ~$21M goes to tokenholders. 40% of fees are shared with BANANA holders (snippet; the source reads like a press release). | https://northpennnow.com/news/2026/mar/02/16b-trading-platform-banana-gun-ships-largest-infrastructure-overhaul-of-2026-across-six-blockchains/ ; https://defillama.com/protocol/banana-gun | North Penn Now / DefiLlama | 2026-03 | accessed 2026-09-28 | M-L | metric
- Giza ARMA (DeFi yield agent): 10% performance fee on realized yield only (snippet). | https://medium.com/@0xjacobzhao/a-new-paradigm-for-stablecoin-yields-agentfi-to-xenofi-9792a83a8e28 ; https://arma.xyz/ | Medium / ARMA | 2025–26 | accessed 2026-09-28 | M | pricing
- Giza/ARMA wind-down: announced 2026-02-26, retired by 2026-03-23. DefiLlama-cited all-time protocol revenue was $127,490, trailing 12-month $56,685, and trailing 30-day $0 as of 2026-09-18. Peak TVL cited as ~$4.85M. This is a leading DeFi-agent brand earning little from its performance fee. | https://ownyourmind.ai/projects/giza/ ; https://defillama.com/protocol/giza | Own Your Mind (review site, cites DefiLlama) | 2026-09-18 | accessed 2026-09-28 | M | metric/risk

### Builder earnings / concentration
- x402 on Base: 100M+ cumulative transactions by Q1 2026. $1+ transactions are 95% of value transferred, up from 49% in early 2025; the 10¢–$1 share collapsed from 46% to 4%. A meme coin (PING) drove the Q4 2025 surge, with volumes up 10,000% in a single week. Tester-to-payer conversion improved 4x over six months. | https://www.chainalysis.com/blog/x402-agentic-payments-adoption/ | Chainalysis | 2026-06-03 | accessed 2026-09-28 | H | metric
- x402 Census (independent open dataset, 2026-08-23 to 09-25, 0.35% sample): ~73k payments/day on Base, worth ~$125k/day, but heavily contaminated by non-x402 EIP-3009 traffic. The recurring "machine economy" is 63.9% of payments but only 1.0% of dollars, with sub-cent median tickets. About 15 payees appear on at least half the days. The busiest endpoints project to only ~$1.1k and ~$5.4k gross per month. Sellers persist (~58%) and buyers do not (~6%). | https://github.com/savecharlie/x402-census | independent GitHub (unvetted) | 2026-09-25 | accessed 2026-09-28 | M-L | metric
- Secondary snippet: "1,396 active sellers generating $65K in [30-day] volume" at ~$0.05/tx. That averages about $47 per seller per month, and the source was not verified. | https://nevermined.ai/blog/stablecoin-payments-ai-agents-statistics | Nevermined (vendor blog) | 2026 | accessed 2026-09-28 | L | metric
- Virtuals: aGDP ~$479M claimed in early 2026 across 18,000+ agents. The "Revenue Network" pays up to $1M/month to ACP selling agents, which is a subsidy/incentive rather than organic demand. Protocol revenue is cited at $39.5M (snippet, aggregator). | https://www.prnewswire.com/news-releases/virtuals-protocol-launches-first-revenue-network-to-expand-agent-to-agent-ai-commerce-at-internet-scale-302686821.html ; https://blockeden.xyz/blog/2026/04/21/agdp-agent-gdp-virtuals-protocol-ai-blockchain-valuation-primitive-tvl-displacement/ | PR Newswire (issuer PR) / BlockEden | 2026-02 / 2026-04 | accessed 2026-09-28 | L-M | metric

### Risk
- Blockaid H1 2026: $1.1B lost across 212 onchain exploits, more than all of 2025. Infra/operational compromises were 15% of incidents but ~76% of losses (signing workflows, credential management, governance). The Bankr ~$216k exploit is called the "first ever" AI-agent exploit. Agent deployment is growing ~10x per year, and multiple agent incidents are expected in H2 2026, with prompt injection as the lead vector, then tool-use abuse and unauthorized signing. | https://www.theblock.co/post/409944/crypto-hacks-hit-record-high-in-h1-2026-as-losses-top-1-billion-blockaid-says ; https://blockaid.io/h1-report-2026 | The Block / Blockaid | 2026-07 | accessed 2026-09-28 | H-M | risk
- Grok/Bankrbot: an attacker used a Morse-code prompt on X to get Grok to tag bankrbot, which moved 3B DRB tokens (~$150–200k) from a wallet because Bankr trusted the LLM's natural-language output as an instruction. | https://oecd.ai/en/incidents/2026-05-04-4a73 | OECD.AI incident monitor | 2026-05-04 | accessed 2026-09-28 | M | risk
- Prompt injection embedded in websites and search results is being used to trick agents into making crypto payments. | https://www.securityweek.com/prompt-injection-attacks-trick-ai-agents-into-making-crypto-payments/ | SecurityWeek | 2026 | accessed 2026-09-28 | M | risk
- AI-agent token drawdown: VIRTUAL fell more than 80% (86% from its Jan-2025 ATH) at the trough. AIXBT market cap was ~$18–28M in Aug 2026, far below its peak. New agent launches on Virtuals plummeted during the drawdown (snippets, mixed-quality sources). | https://www.tradingview.com/news/cointelegraph:4ea6e5590094b:0-new-agent-launches-on-virtuals-plummet-amid-ai-token-drawdown/ ; https://changelly.com/blog/best-ai-agent-crypto-coins-to-buy/ | Cointelegraph via TradingView / Changelly | 2025–26 | accessed 2026-09-28 | L-M | risk

### Regulatory
- GENIUS Act: it takes effect on the earlier of 2027-01-18 (18 months after enactment) or 120 days after final rules. NPRMs came from FinCEN/OFAC (AML/sanctions, 2026-04-08), OCC, FDIC (2026-04-07) and Treasury (issuance/offer/sale, Federal Register 2026-08-18). | https://home.treasury.gov/news/press-releases/sb0435 ; https://www.federalregister.gov/documents/2026/08/18/2026-16796/genius-act-regulations-on-payment-stablecoin-issuance-offer-and-sale ; https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-3.html | US Treasury / Federal Register / OCC | 2026-04 to 2026-08 | accessed 2026-09-28 | H | regulatory
- US AI trading: as of mid-2026, no AI-specific SEC or CFTC rule is in force, and existing adviser/broker/CEA frameworks apply. A CFTC staff advisory (Dec 2024) reminds registrants their obligations still apply. On 2026-06-23, Reps. Foster and Sherman sent SEC Chair Atkins a request for information on agentic trading, citing Robinhood Agentic Trading and adviser/broker status questions. | https://foster.house.gov/sites/evo-subsites/foster-evo.house.gov/files/evo-media-document/foster_sherman-request-for-information-re-agentic-trading-6.23.2026.pdf ; https://www.cftc.gov/PressRoom/PressReleases/9013-24 ; https://astraea.law/insights/ai-trading-agent-cftc-registration | US House / CFTC / law-firm blog | 2024-12 to 2026-06 | accessed 2026-09-28 | M-H | regulatory
- EU: a CASP running an agent that executes client transactions falls under MiCA Art. 66 (conduct) and Art. 70 (safeguarding). The AI Act's high-risk provisions apply from 2026-08-02 and require human oversight. Commission Art. 6 high-risk guidelines slipped, with drafts in consultation from 2026-05-19. ESMA's 2026-02-26 supervisory briefing extends MiFID II algo-trading expectations to AI systems. | https://cointegrity.substack.com/p/who-is-the-client-when-the-client ; https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica | Cointegrity (substack analysis) / ESMA | 2026 | accessed 2026-09-28 | M | regulatory

## (b) Pricing benchmark table

| Product | Niche | Price model | Price | Source URL | Date |
|---|---|---|---|---|---|
| CoinGecko API | Market data | Subscription + overage | Free 10k/mo; $35 / $129 / $499 / $999 per mo; overage $0.0005/call | https://www.coingecko.com/en/api/pricing | live 2026-09-28 |
| Nansen API (x402) | Onchain analytics | Pay-per-call USDC (x402) | ~$0.01–$0.05/call | https://docs.nansen.ai/getting-started/agentic-payments/x402-payments | 2026-04 (snippet) |
| GoPlus Token Security | Token risk | Freemium + credits (GPS/fiat), enterprise quote | Free 30 calls/min; paid price not public | https://docs.gopluslabs.io/reference/api-overview | live 2026-09-28 |
| Banana Gun | Trading bot | Per-trade fee, 40% shared with token | ~$52M annualized rev (Mar 2026); fee % not verified this run | https://defillama.com/protocol/banana-gun | 2026-03 |
| Giza ARMA | DeFi yield agent | Performance fee | 10% of realized yield (wound down Mar 2026) | https://arma.xyz/ | 2025–26 |
| x402 median recurring ticket | Agent API market | Pay-per-call | sub-cent median; ~$0.002–$0.02/call on top endpoints | https://github.com/savecharlie/x402-census | 2026-09-25 |
| Webacy / De.Fi / Blockaid / Birdeye / Moralis / Photon / Maestro | various | — | NOT RETRIEVED this run | — | — |

## (c) Risk incidents table

| Incident | Date | Loss / impact | Source URL |
|---|---|---|---|
| Grok + Bankrbot Morse-code prompt injection | ~2026-05 | 3B DRB, ~$150–216k | https://oecd.ai/en/incidents/2026-05-04-4a73 ; https://www.theblock.co/post/409944/crypto-hacks-hit-record-high-in-h1-2026-as-losses-top-1-billion-blockaid-says |
| H1 2026 onchain exploits (aggregate) | 2026 H1 | $1.1B across 212 exploits; 76% of losses from infra/key/signing compromise | https://blockaid.io/h1-report-2026 |
| Prompt injection via web/search tricking agents into payments | 2026 | Unquantified | https://www.securityweek.com/prompt-injection-attacks-trick-ai-agents-into-making-crypto-payments/ |
| Giza ARMA wind-down (business failure) | 2026-02-26 to 03-23 | Revenue $127k all-time; $0 in the last 30 days | https://ownyourmind.ai/projects/giza/ |
| AI-agent token collapse (VIRTUAL, AIXBT) | 2025–2026 | VIRTUAL -80–86% from ATH; AIXBT mcap ~$18–28M (Aug 2026) | https://www.tradingview.com/news/cointelegraph:4ea6e5590094b:0-new-agent-launches-on-virtuals-plummet-amid-ai-token-drawdown/ |
| x402 volume inflated by meme/test/non-x402 traffic | Q4 2025 to 2026 | PING spike +10,000% in a week; EIP-3009 contamination | https://www.chainalysis.com/blog/x402-agentic-payments-adoption/ ; https://github.com/savecharlie/x402-census |
| AIXBT dashboard compromise; Freysa; ElizaOS memory injection | 2025 | NOT RETRIEVED this run (training-data belief only) | — |

## (d) Vietnam regulation summary

- **Law on Digital Technology Industry** (passed 2025-06-14; mostly effective 2026-01-01, incentive provisions from 2025-07-01). It is the first law to recognise digital assets as lawful property under the Civil Code, which gives ownership, transfer and inheritance rights. It also sets core AI governance principles. Sources: https://www.dfdl.com/insights/legal-and-tax-updates/vietnam-landmark-law-on-digital-technology-industry-new-frameworks-for-ai-digital-assets/ ; https://www.vietnam-briefing.com/news/vietnam-passes-first-ever-law-on-digital-technology-industry.html/ (M, law-firm/secondary; primary text on thuvienphapluat not fetched).
- **Resolution 05/2025/NQ-CP** (effective 2025-09-09; 5-year pilot crypto market):
  - Only licensed CASPs may operate.
  - Licensing requirements: a Vietnamese enterprise with at least VND 10,000bn (~$378M) charter capital, fully paid in VND; foreign ownership capped at 49%; at least 65% held by institutions, with at least 35% from two banks, securities firms, fund managers, insurers or tech firms that have 2 years of profits.
  - Trading settles in VND. Stablecoins that act as currency substitutes, security tokens and CBDCs are excluded.
  - New token offerings may only be made to foreign investors.
  - Tax is 0.1% of transaction value, collected by the provider.
  - Domestic investors get 6 months after the first licence to move to licensed platforms. After that, using unlicensed exchanges risks administrative or criminal sanctions.
  - Sources: https://vietnam.acclime.com/news-insights/vietnams-crypto-pilot-a-cautious-green-light/ (2025-09-26, M) ; https://asialegal.vn/resolution-no-05-2025-nq-cp-on-pilot-of-crypto-assets-market-in-vietnam/ (M)
- **Status:** reportedly 7 applicants and 5 passed initial assessment, but no final licence as of 2026-08-30 (snippet; CryptoRank returned 403 on fetch). https://cryptorank.io/news/feed/b7225-nine-months-seven-applicants-zero-licences-vietnams-crypto-waiting-game (L-M)
- **Implications for a Vietnamese team selling agent services globally** (inference, not a legal opinion):
  - The pilot's licensing regime targets operating a crypto trading market or service for investors. The capital bar makes it impossible for a small team to hold a licence.
  - No source retrieved addresses Vietnamese firms selling software, data or API services to foreign customers and being paid in stablecoin. That remains an open legal question.
  - Receiving USDC is itself a grey area, because stablecoins are excluded from the pilot.
  - Custodial or execution products aimed at Vietnamese retail users are the highest-risk design once the 6-month transition begins.
  - Non-custodial data/risk APIs sold offshore look lowest-risk, but this is unverified.

## (e) Leads
- DefiLlama fee pages for Banana Gun, Maestro, Photon, Axiom and Virtuals: to confirm revenue and fee % (not fetched).
- Blockaid H1 2026 full PDF: AI-agent section details.
- Nansen x402 case study (https://nansen.ai/post/how-nansen-enabled-pay-per-call-onchain-data-access-with-x402-and-payai) and the nansen-cli issue #625 (404): actual x402 revenue for a major brand.
- Foster/Sherman RFI letter (PDF): the specific questions SEC may address on agentic trading.
- thuvienphapluat.vn primary texts of Law 71/2025/QH15 (Digital Technology Industry) and Resolution 05/2025/NQ-CP; any 2026 decree on digital-asset service classification or foreign-currency receipt rules.
- Virtuals ACP dashboard (per-agent revenue distribution); Olas mech marketplace stats.
- Major Matters x402 tracker (https://majormatters.co/x402).

## (f) Looked for but not found (this run)
- Public list prices for Webacy, De.Fi, Blockaid, Birdeye, Moralis; paid tiers for GoPlus.
- Verified per-trade fee % for Banana Gun, Maestro, Photon (training belief: ~0.5–1%; unverified).
- Almanak fee structure.
- Olas agent/mech earnings distribution; Virtuals ACP per-agent earnings distribution (only aggregate aGDP and subsidy figures found).
- Primary incident write-ups for AIXBT dashboard compromise, Freysa, ElizaOS memory-injection research, and MCP/API-key leaks (training-data beliefs only; not evidenced this run).
- Any Vietnamese rule covering local companies selling crypto-related software/API services offshore, or receiving stablecoin payments.
