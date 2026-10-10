"""P9.4b T0 baseline: sha256 of canonical JSON (sorted keys, floats as hex) of Nora outputs.
Usage (from nora/): python test/scripts/nautilus_diff/check_baseline.py [--write]
  --write  regenerate p94b_baseline.sha256 ; default: recompute and compare (exit 1 on mismatch).
Covers out/nora_*.json, out/ext/nora_*.json out/s9/nora_*.json (S9: s9_run_nora.py + s9_compare.py -> s9_results.json) and out/s10/nora_*.json (S10: s10_run_nora.py + s10_compare.py -> s10_results.json) and out/s11/nora_*.json (S11: s11_run_nora.py + s11_compare.py -> s11_results.json) (fields trades, final_equity, open_at_end, dca_rejected, funding_log,
rejected_for_risk, decisions) and the whole of results*.json / ext_results*.json (compare outputs).
Regenerate the inputs first with run_nora.py / ext_run_nora.py [ohlc|adaptive] and compare.py / ext_compare.py.
"""
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "p94b_baseline.sha256")
FIELDS = ("trades", "final_equity", "open_at_end", "dca_rejected", "funding_log", "rejected_for_risk", "decisions", "fills", "realized_equity")


def canon(o):
    if isinstance(o, float):
        return {"__f": o.hex()}
    if isinstance(o, dict):
        return {str(k): canon(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [canon(v) for v in o]
    return o


def sha(o):
    return hashlib.sha256(json.dumps(canon(o), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compute():
    res = {}
    for pat in ("out/nora_*.json", "out/ext/nora_*.json", "out/s9/nora_*.json", "out/s10/nora_*.json", "out/s11/nora_*.json", "out/s12/nora_*.json", "out/s15/nora_*.json"):
        for f in sorted(glob.glob(os.path.join(HERE, pat))):
            d = json.load(open(f))
            res[os.path.relpath(f, HERE)] = sha({k: d[k] for k in FIELDS if k in d})
    for pat in ("results*.json", "ext_results*.json", "s9_results*.json", "s10_results*.json", "s11_results*.json", "s12_results*.json", "s15_results*.json"):
        for f in sorted(glob.glob(os.path.join(HERE, pat))):
            res[os.path.relpath(f, HERE)] = sha(json.load(open(f)))
    return res


def main():
    cur = compute()
    if "--write" in sys.argv:
        with open(BASE, "w") as fh:
            fh.writelines(f"{h}  {k}\n" for k, h in sorted(cur.items()))
        print(f"wrote {len(cur)} hashes -> {BASE}")
        return 0
    ref = dict(l.strip().split("  ", 1)[::-1] for l in open(BASE) if l.strip())
    bad = [k for k in sorted(set(ref) | set(cur)) if ref.get(k) != cur.get(k)]
    for k in bad:
        print("MISMATCH", k, "(missing)" if k not in cur or k not in ref else "")
    print(f"{len(ref) - len(bad)}/{len(ref)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
