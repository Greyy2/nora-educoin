# Cross-engine differential test: Nora vs NautilusTrader (2.0.0rc6)
Same bars + precomputed EMA-cross signals -> Nora `PositionTracker`/`PositionManager+SimVenue` and a Nautilus `BacktestEngine` (L1 bar execution, NETTING/MARGIN). Results and verdict: `REPORT.md`.
1. `cd nora; PYTHONDONTWRITEBYTECODE=1 backend/utils/ops/run_limited.sh --no-lock -- test/scripts/nautilus_diff/export_data.py` (writes `out/`, not committed), then `.../run_nora.py [ohlc|adaptive]` (intrabar_path; adaptive writes `*_adaptive.json`)
2. Nautilus venv (`uv venv ~/.venvs/nautilus --python 3.14; uv pip install --pre nautilus_trader pandas pyarrow`): `systemd-run --user --scope --slice=nora.slice -p MemoryMax=4G ~/.venvs/nautilus/bin/python -I test/scripts/nautilus_diff/run_nautilus.py fine|okx [0|1=adaptive H/L order] [datasets] [stages]`
3. `~/.venvs/nora/bin/python test/scripts/nautilus_diff/compare.py fine|okx [_adaptive]` -> markdown table + `results_<inst><suffix>.json`
