# D6/D8 r2 (lead) — Exchange copy-trading, bot & signal marketplaces (OKX + Binance), headless capture of public pages 2026-09-28

Sources: https://www.okx.com/trading-bot/marketplace ; https://www.okx.com/trading-bot/signal-marketplace ; https://www.binance.com/en/copy-trading ; https://www.binance.com/en/trading-bots | public pages, own API responses | accessed 2026-09-28 | confidence high (as displayed)

## OKX bot counts by type (strategy-summary API; likely cumulative created/running, semantics not documented)
- grid: 1,037,463
- contract_grid: 972,495
- contract_dca: 646,687
- spot_dca: 276,453
- infinite_grid: 12,466
- recurring: 206,113
- smart_portfolio: 56,868
- twap: 22,917
- iceberg: 57,958
- stop_order: 5,871,519
- trigger: 539,965
- move_order_stop: 573,339
- arbitrage: 36,697
- moon_grid: 23,070
- smart_iceberg: 31,342
- signal_bot: 113,190

## OKX Bot Marketplace — lead bots (600 listed; top 6 by default sort captured)

| type | inst | creator | PnL USDT | PnL % | followers | follower assets USDT | profit share |
|---|---|---|---|---|---|---|---|
| contract_dca | ETH-USDT-SWAP | Used-WebSocket-Lilac | 1,148,663 | 638.8 | 10055 | 3,048,581 | 30% |
| contract_dca | ETH-USDT-SWAP | Clever-Bandwidth-Pea | 757,656 | 305.7 | 7705 | 2,206,391 | 30% |
| contract_dca | ETH-USDT-SWAP | Used-WebSocket-Lilac | 910,747 | 382.5 | 3127 | 623,159 | 30% |
| contract_dca | ETH-USDT-SWAP | The nightisbeautiful | 607,856 | 336.9 | 2354 | 320,773 | 30% |
| contract_dca | ETH-USDT-SWAP | Mist will disperse | 1,037,425 | 610.2 | 2327 | 318,578 | 30% |
| contract_dca | ETH-USDT-SWAP | Mist will disperse | 765,897 | 366.6 | 967 | 105,697 | 30% |

## OKX Signal Marketplace — 31 signal channels (first page)

| channel | creator | 30D backtested APY | follower win rate | AUM USDT | followers | profit share | subscription fee |
|---|---|---|---|---|---|---|---|
| [AM] Occultation MIX | AM Management | 14.7% | 51.9% | 26,780 | 20200 | 20% | 0.0 (profit_sharing) |
| [AM] Occultation | AM Management | -10.2% | 50.5% | 102,516 | 50002 | 20% | 0.0 (profit_sharing) |
| [Kira] BTC多指标加权趋势策略（固定仓位） | Kirihito | 304.2% | 100.0% | 2,363 | 68 | 30% | 0.0 (profit_sharing) |
| [CoinKarma]BTC Overall LIQ+LIQ 3X (峙樺特優化) | CoinKarma | 392.5% | 80.9% | 30,147 | 1176 | 10% | 0.0 (profit_sharing) |
| [mossin] Nagnats BTC-ETH | Mossin_Nagant | 1218.1% | 43.8% | 960 | 417 | 20% | 0.0 (profit_sharing) |
| [IntellyBot] BTC | IntellyBot | 233.5% | 37.4% | 95,359 | 14512 | 20% | 0.0 (profit_sharing) |

## Binance Trading Bots — active count & value (landing-page/introduction API)

| strategyType | active | total value USD |
|---|---|---|
| 1 Spot grid (likely) | 85,346 | 173,785,833 |
| 2 Futures grid (likely) | 41,065 | 109,794,914 |
| 3 type 3 — unlabeled (possibly algo/arbitrage) | 1,858 | 8,749,134,936 |
| 10 Futures DCA (likely) | 1,590 | 963,212 |

## Binance Futures Copy Trading — lead portfolios shown on public page (13 unique)

| section | lead | copiers/cap | tags | 30D PnL USD | ROI | AUM USD | 30D MDD | days |
|---|---|---|---|---|---|---|---|---|
| High PNL | Benny_256 | 78 / 200 | TradFi,Master | 1,205,022.11 | 138.20% | 1,534,190.61 | 19.93% | 39 |
| High PNL | Luke Alpha | 197 / 200 | Cadet | 986,756.52 | 16.90% | 7,048,471.73 | 11.18% | 15 |
| High PNL | 币圈心灵导师 | 157 / 200 | TradFi,Champion | 571,721.08 | 557.19% | 319,150.84 | 60.58% | 35 |
| High PNL | Feed-Creator-4bc0690bb | 334 / 400 | TradFi,Master | 524,691.97 | 124.77% | 1,070,869.48 | 23.14% | 406 |
| High ROI | 妙脆 | 570 / 600 | Master | 39,378.07 | 7,875.61% | 392,710.63 | 71.91% | 13 |
| High ROI | DAmorné | 365 / 400 | TradFi,API,Master | 22,786.86 | 4,557.37% | 165,296.14 | 1.52% | 18 |
| High ROI | 百辉财经 | 570 / 800 | TradFi,API,Master | 21,748.48 | 4,349.69% | 744,447.51 | 17.92% | 19 |
| High ROI | BTC拖拉机 | 368 / 400 | TradFi,API,Champion | 18,087.31 | 3,617.46% | 318,840.26 | 15.98% | 19 |
| High Copiers' PNL | 羊汤资本-阿汤哥 | 199 / 400 | Legend | 2,921.10 | 7.31% | 4,040,813.34 | 8.82% | 544 |
| High Copiers' PNL | 戊土校尉 | 46 / 400 | TradFi,Master | 14,554.02 | 46.60% | 752,473.71 | 18.48% | 894 |
| Most Copied | 星辰社区-意钦 | 959 / 1000 |  | 1,843.69 | 8.65% | 833,648.22 | 19.09% | 315 |
| Most Copied | 玄冥二老 | 798 / 800 | TradFi,API | 1,446.65 | 29.43% | 558,307.82 | 0.00% | 232 |
| Most Copied | 七大爷 | 686 / 800 | Master | 80,649.15 | 11.07% | 881,359.91 | 8.61% | 587 |
| Most Copied | 鎏渊 | 599 / 600 | TradFi | 20,304.01 | 5.13% | 1,017,929.06 | 78.41% | 95 |

Notes: 'API' tag on Binance = portfolio traded via API (bot/algorithm). Lead-trader profit share per D6 digest: 10% spot, up to 30% futures. OKX bot/signal creators earn profit share 10–30% (as listed).