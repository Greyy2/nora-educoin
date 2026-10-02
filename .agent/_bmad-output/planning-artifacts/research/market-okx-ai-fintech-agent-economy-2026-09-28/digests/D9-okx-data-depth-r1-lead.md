# D9 (lead) — OKX public API historical depth for regime/signal tests (BTC-USDT-SWAP), probed 2026-09-28

Source: https://www.okx.com/docs-v5/en/ endpoints called live via curl | OKX public REST | accessed 2026-09-28 | confidence high (direct probe)

| Data | Endpoint | Result |
|---|---|---|
| Candles 1H | /api/v5/market/history-candles | Available back to 2021 (page before 2022-01-01 returned 2021-12-27..31) |
| Funding rate | /api/v5/public/funding-rate-history | Latest page 2026-08-26..09-28; pages before 2026-06-01 empty -> ~3-4 months only |
| Open interest 1D | /api/v5/rubik/stat/contracts/open-interest-history | 100 rows/call; end=2025-06-01 returned 2025-02-21..05-31 -> long daily history |
| Open interest 1H | same | Latest 100 rows (~4 days); end=2026-06-01 empty -> short hourly window |
| Taker volume 1H | /api/v5/rubik/stat/taker-volume-contract | end=2026-06-01 returned 2026-05-27..31 -> at least ~4 months hourly |
| Taker volume 1D | same | 100 rows back to 2026-06-21 (older via end param not probed) |
| Long/short 1D | /api/v5/rubik/stat/contracts/long-short-account-ratio-contract | 100 rows back to 2026-06-21; 1H before 2026-06-01 empty |
| Order book | /api/v5/market/books | Snapshot only, no history |

Implication: E4 (regime-only lag) runnable now on years of candles. E5 at hourly resolution needs forward logging (OI/long-short/funding/books) or daily-resolution proxy; third-party historical vendors not evaluated.
