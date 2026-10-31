#!/usr/bin/env python3
import json
from pathlib import Path

job_file = Path("nora/edu/data/cache/process/_mem/20261027_140306_60fd23.json")
data = json.loads(job_file.read_text())
res = data.get("result", {})
diag = res.get("diagnostics", {})
print("Diag keys:", list(diag.keys()))
print("pnl_structure:", diag.get("pnl_structure"))
metrics = res.get("metrics", {})
print("metrics keys:", list(metrics.keys()))
print("metrics test:", metrics.get("test"))
