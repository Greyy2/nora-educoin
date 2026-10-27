# BÁO CÁO DRY-RUN ĐỐI CHIẾU 66 ALPHA ID TRÙNG GIỮA EDU VÀ COIN

**Thời điểm tạo:** /home/vmc03/norabt/.backup/baseline_snapshot_20261026_143328
**Tổng số ID trùng:** 66
**Trùng khớp 100%:** 66
**Có sai khác:** 0

## 1. Nguyên tắc Xử lý Đề xuất cho Owner Phê duyệt

1. **EDU:** Giữ nguyên 100% toàn bộ bản ghi alpha thuộc EDU data root.
2. **COIN:** Chỉ giữ lại các bản ghi thuộc Allowlist được phê duyệt (Top OKX, Proxima). Các bản ghi trùng còn lại chỉ được chuyển sang vùng cách ly (`nora/coin/data/alpha/_quarantine/`) SAU KHI Owner chốt danh sách.
3. **Bảo toàn User:** Không hợp nhất tài khoản user cùng tên giữa EDU và COIN; mỗi bên dùng store riêng biệt.

## 2. Bảng Đối chiếu Chi tiết 66 Bản ghi Trùng

| STT | Alpha ID | Tên Chiến lược | Trạng thái Đối chiếu | SHA-256 Code | Symbols | Timeframe |
|---|---|---|---|---|---|---|
| 1 | `0873864b8db7` | DEMA Turbo Compound (1Y Fast Trend - x1.51 Vốn) | **IDENTICAL (Trùng khớp 100%)** | `0b98d5f8f136...` | BTC,ETH,SOL... | 24h |
| 2 | `090730ae35b8` | Fail-Fast Volatility Breakout (SL 2.4% + Macro Trend) | **IDENTICAL (Trùng khớp 100%)** | `8db8d1a47407...` | BTC,ETH,SOL... | 24h |
| 3 | `0caaa527c1c3` | Kiểm tra engine 1m (nến xanh/đỏ) | **IDENTICAL (Trùng khớp 100%)** | `684a0ec2d2ef...` | BTC,ETH,SOL | 1m |
| 4 | `0d51ba8d2012` | OBV Volume Accumulation + RSI Momentum | **IDENTICAL (Trùng khớp 100%)** | `64be35b1cccd...` | BTC,ETH,SOL... | 24h |
| 5 | `0f8f9e67fe25` | Statistical Trend Channel Guard (Optimized) | **IDENTICAL (Trùng khớp 100%)** | `1a4fbacd5288...` | BTC,ETH,SOL... | 24h |
| 6 | `136b5e410cae` | Williams %R Extreme Elasticity | **IDENTICAL (Trùng khớp 100%)** | `af66979b3466...` | BTC,ETH,SOL... | 24h |
| 7 | `14e3b934b1e5` | ROC Momentum Exhaustion with Take-Profit | **IDENTICAL (Trùng khớp 100%)** | `e2da23ba1546...` | BTC,ETH,SOL... | 24h |
| 8 | `15567e02a806` | Triple EMA Trend Alignment (Optimized) | **IDENTICAL (Trùng khớp 100%)** | `468198f89be8...` | BTC,ETH,SOL... | 24h |
| 9 | `18e87aa868ad` | Fast Dynamic Channel Breakout (18D + Macro Trend) | **IDENTICAL (Trùng khớp 100%)** | `d120800459df...` | BTC,ETH,SOL... | 24h |
| 10 | `1a6eb53421cf` | Kiểm tra engine 1m (EMA 9/21) | **IDENTICAL (Trùng khớp 100%)** | `ee7475aa88c5...` | BTC,ETH,SOL | 1m |
| 11 | `270e6e28416f` | EMA Trend Rider (Rising Slope - Optimized) | **IDENTICAL (Trùng khớp 100%)** | `766be5389cc0...` | BTC,ETH,SOL... | 24h |
| 12 | `29b85425e324` | e2e-check-delete-me | **IDENTICAL (Trùng khớp 100%)** | `9b01b4580b50...` | BTC | 24h |
| 13 | `303d4b713dda` | Macro Trend Filtered Breakout (EMA 105 Filter) | **IDENTICAL (Trùng khớp 100%)** | `09b1764e6144...` | BTC,ETH,SOL... | 24h |
| 14 | `33312a2f4dfc` | Standard Deviation Dynamic Channel Breakout (v2.0 Regime Filtered) | **IDENTICAL (Trùng khớp 100%)** | `c320d9dbef1d...` | BTC,ETH,SOL... | 24h |
| 15 | `3cfcc2d296a2` | Donchian Lower Channel Exit | **IDENTICAL (Trùng khớp 100%)** | `e12fb56ef4c0...` | BTC,ETH,SOL... | 24h |
| 16 | `443dbac7bb78` | Bollinger Mid + RSI + ADX Filter | **IDENTICAL (Trùng khớp 100%)** | `93d1c82ae3e5...` | BTC,ETH,SOL... | 24h |
| 17 | `4d4ef78d5b96` | e2e-check-delete-me2 | **IDENTICAL (Trùng khớp 100%)** | `9b01b4580b50...` | BTC | 24h |
| 18 | `4f28285aa44c` | Dual EMA + ADX Trend Strength Filter | **IDENTICAL (Trùng khớp 100%)** | `b12c9e5dcfed...` | BTC,ETH,SOL... | 24h |
| 19 | `541c55834f56` | Daily Range Expansion (High - Low) / Close | **IDENTICAL (Trùng khớp 100%)** | `2c97555121ad...` | BTC,ETH,SOL... | 24h |
| 20 | `5e52d3fdf71f` | Bollinger Band Overextension Exit | **IDENTICAL (Trùng khớp 100%)** | `3cc60ff6a0b1...` | BTC,ETH,SOL... | 24h |
| 21 | `6055aa8f661e` | Triple Filter: EMA + MACD + RSI | **IDENTICAL (Trùng khớp 100%)** | `ea790a2836dc...` | BTC,ETH,SOL... | 24h |
| 22 | `60d7e4b533f3` | Bollinger Bands Lower Touch & Bounce | **IDENTICAL (Trùng khớp 100%)** | `bc5297b0e1d6...` | BTC,ETH,SOL... | 24h |
| 23 | `6afa7f774655` | RSI Rebound with Fast SMA Filter | **IDENTICAL (Trùng khớp 100%)** | `5538fc8adc65...` | BTC,ETH,SOL... | 24h |
| 24 | `6d1e2d27aa25` | EMA Trend + RSI Dip Buying (Trend Pullback) | **IDENTICAL (Trùng khớp 100%)** | `33f977345fee...` | BTC,ETH,SOL... | 24h |
| 25 | `6dd0d9796870` | Donchian Breakout + Trend Alignment (Optimized) | **IDENTICAL (Trùng khớp 100%)** | `3d5dc219c653...` | BTC,ETH,SOL... | 24h |
| 26 | `6ee5f67569d4` | On-Balance Volume (OBV) Trend Breakout | **IDENTICAL (Trùng khớp 100%)** | `ca78d1ceb817...` | BTC,ETH,SOL... | 24h |
| 27 | `715e56a6dd33` | Linear Regression Channel Deviation | **IDENTICAL (Trùng khớp 100%)** | `993282e70778...` | BTC,ETH,SOL... | 24h |
| 28 | `717c1890c59e` | Weighted Moving Average (WMA) Crossover (Optimized) | **IDENTICAL (Trùng khớp 100%)** | `8815f3554614...` | BTC,ETH,SOL... | 24h |
| 29 | `79b717cb3d33` | ADX + Directional Movement (+DI / -DI) | **IDENTICAL (Trùng khớp 100%)** | `2a3562b1df3c...` | BTC,ETH,SOL... | 24h |
| 30 | `7f3486d63ca8` | Dual Oscillator Climax Exit | **IDENTICAL (Trùng khớp 100%)** | `26bf8e0983a9...` | BTC,ETH,SOL... | 24h |
| 31 | `7f3beda7b859` | Fixed Multiple ATR Volatility Stop (Optimized) | **IDENTICAL (Trùng khớp 100%)** | `480c0c4f634b...` | BTC,ETH,SOL... | 24h |
| 32 | `7f67e9aed0aa` | Stochastic & RSI Confluence System | **IDENTICAL (Trùng khớp 100%)** | `7c81cf2e33a3...` | BTC,ETH,SOL... | 24h |
| 33 | `89379cc0ab52` | Stochastic Oscillator (%K, %D) Bull Cross | **IDENTICAL (Trùng khớp 100%)** | `ee67c4f580d1...` | BTC,ETH,SOL... | 24h |
| 34 | `895d6637de0e` | Triple Exponential Moving Average (TEMA) | **IDENTICAL (Trùng khớp 100%)** | `f68375f86fbd...` | BTC,ETH,SOL... | 24h |
| 35 | `8a47cdbcc942` | Fast Dip Harvester (3M DCA Dynamic - CAGR 108%) | **IDENTICAL (Trùng khớp 100%)** | `0eb932dea2e0...` | BTC,ETH,SOL... | 24h |
| 36 | `8d9ab6723937` | Dual-Condition Asymmetric Exit | **IDENTICAL (Trùng khớp 100%)** | `a24e6e78a23f...` | BTC,ETH,SOL... | 24h |
| 37 | `967f3c0c7803` | Keltner Channel + MACD Confirmation | **IDENTICAL (Trùng khớp 100%)** | `339d5b45f3b1...` | BTC,ETH,SOL... | 24h |
| 38 | `ab14198417bd` | ADX Trend Decay Early Warning Exit (Optimized) | **IDENTICAL (Trùng khớp 100%)** | `096beddff2bf...` | BTC,ETH,SOL... | 24h |
| 39 | `abf6596900b0` | Chiến lược đầu tay của e2e_edu_061299 | **IDENTICAL (Trùng khớp 100%)** | `7d08027aa019...` | BTC | 24h |
| 40 | `alpha_1m_01_rsidynamic` | RSI Dynamic Scalper 1m | **IDENTICAL (Trùng khớp 100%)** | `d5276b54e1ba...` | BTC,ETH | 1m |
| 41 | `alpha_1m_02_fastematre` | Fast EMA Trend Scalper 1m | **IDENTICAL (Trùng khớp 100%)** | `efc73283c962...` | BTC,ETH | 1m |
| 42 | `alpha_1m_03_bollingerb` | Bollinger Volatility Breakout 1m | **IDENTICAL (Trùng khớp 100%)** | `2628b5ab3a3f...` | BTC,ETH | 1m |
| 43 | `alpha_1m_04_donchiantu` | Donchian Turtle Channel 1m | **IDENTICAL (Trùng khớp 100%)** | `0b8f7440e717...` | BTC,ETH | 1m |
| 44 | `alpha_1m_05_macdimpuls` | MACD Impulse Momentum 1m | **IDENTICAL (Trùng khớp 100%)** | `0d775a418f6e...` | BTC,ETH | 1m |
| 45 | `alpha_proxima_research` | Proxima Universal Breakout (Research) | **IDENTICAL (Trùng khớp 100%)** | `37cbf60e5a84...` | BTC | 1m |
| 46 | `b474e5e9620d` | Bollinger Upper Band Breakout (Optimized) | **IDENTICAL (Trùng khớp 100%)** | `b6a8f7671260...` | BTC,ETH,SOL... | 24h |
| 47 | `b4b65cd3493f` | Commodity Channel Index (CCI) Snapback | **IDENTICAL (Trùng khớp 100%)** | `1fbcd5baadb9...` | BTC,ETH,SOL... | 24h |
| 48 | `b96bafe57445` | Normalized ATR (NATR) Volatility Breakout | **IDENTICAL (Trùng khớp 100%)** | `b4987c2b0356...` | BTC,ETH,SOL... | 24h |
| 49 | `bb2c87ed4585` | RSI + Bollinger Bands Oversold Reversal | **IDENTICAL (Trùng khớp 100%)** | `b75b624ff93e...` | BTC,ETH,SOL... | 24h |
| 50 | `bf519617d973` | Double Exponential Moving Average (DEMA - Optimized) | **IDENTICAL (Trùng khớp 100%)** | `b086b3c0b434...` | BTC,ETH,SOL... | 24h |
| 51 | `c33cc317bbeb` | Multi-Day Cumulative Return Dip Buying | **IDENTICAL (Trùng khớp 100%)** | `3e39a3f50a6c...` | BTC,ETH,SOL... | 24h |
| 52 | `c4cbe096ff37` | Absolute Momentum 10-Day Threshold | **IDENTICAL (Trùng khớp 100%)** | `f7e87d1880b6...` | BTC,ETH,SOL... | 24h |
| 53 | `c74830c79a3a` | Keltner Channel Trend (KEMA) | **IDENTICAL (Trùng khớp 100%)** | `dd0c0ef94056...` | BTC | 24h |
| 54 | `ca6f14e5f692` | Kiểm tra engine 1m (EMA 3/8 nhanh) | **IDENTICAL (Trùng khớp 100%)** | `d5b2ac6c9a9b...` | BTC,ETH,SOL | 1m |
| 55 | `cb750cb1eb10` | EMA Golden Cross + Volume Spike Confluence | **IDENTICAL (Trùng khớp 100%)** | `84bd83c20002...` | BTC,ETH,SOL... | 24h |
| 56 | `cef36afa8d13` | Linear Regression Slope Trend | **IDENTICAL (Trùng khớp 100%)** | `6ce97acf42fd...` | BTC,ETH,SOL... | 24h |
| 57 | `dcad7e2d6b12` | Dual EMA Crossover (Golden Cross) | **IDENTICAL (Trùng khớp 100%)** | `c76865cba693...` | BTC,ETH,SOL... | 24h |
| 58 | `e84534eab0a7` | Chiến lược đầu tay của e2e_edu_77fab9 | **IDENTICAL (Trùng khớp 100%)** | `7d08027aa019...` | BTC | 24h |
| 59 | `efa90f74cd08` | Donchian Channel Breakout (Turtle Trading) | **IDENTICAL (Trùng khớp 100%)** | `9642ad27aaca...` | BTC,ETH,SOL... | 24h |
| 60 | `efb1fbe2db86` | Volatility Expansion Channel (StdDev 1.51 + Macro Trend) | **IDENTICAL (Trùng khớp 100%)** | `205a3ddb655e...` | BTC,ETH,SOL... | 24h |
| 61 | `f261549d9efa` | ROC Momentum Surge | **IDENTICAL (Trùng khớp 100%)** | `13dc7f500cf6...` | BTC,ETH,SOL... | 24h |
| 62 | `f4e211e9510d` | Rolling 30-Day Multi-Week High Breakout | **IDENTICAL (Trùng khớp 100%)** | `06696cdb75bc...` | BTC,ETH,SOL... | 24h |
| 63 | `f8428a494dbc` | Money Flow Index (MFI) Volume Reversion | **IDENTICAL (Trùng khớp 100%)** | `4b1483403753...` | BTC,ETH,SOL... | 24h |
| 64 | `f9d56824ee69` | Chandelier Exit (ATR Trailing Stop) | **IDENTICAL (Trùng khớp 100%)** | `519b7d216a85...` | BTC,ETH,SOL... | 24h |
| 65 | `fa8c9b6d589c` | Rolling Z-Score Statistical Reversion | **IDENTICAL (Trùng khớp 100%)** | `8101fead0f63...` | BTC,ETH,SOL... | 24h |
| 66 | `fa9587a97fa9` | Trend Alignment Momentum (Optimized) | **IDENTICAL (Trùng khớp 100%)** | `1f8b2cd8f72c...` | BTC,ETH,SOL... | 24h |
