import json
from pathlib import Path

rec = json.loads(Path("nora/edu/data/alpha/user/0873864b8db7.json").read_text(encoding="utf-8"))
ch = rec.get("contract_history", [])
print(f"Contract history length: {len(ch)}")
for i, item in enumerate(ch):
    snap = item.get("result_snapshot")
    if snap:
        print(f"Item {i} keys: {list(snap.keys())}")
        if "result" in snap:
            res = snap["result"]
            print(f"snap[result] type={type(res)}")
            if isinstance(res, dict):
                print(f"snap[result] keys: {list(res.keys())}")
                if "metrics" in res:
                    print(f"res[metrics] keys: {list(res['metrics'].keys())}")
        if "metrics" in snap:
            print(f"snap[metrics] type={type(snap['metrics'])}")
            if isinstance(snap["metrics"], dict):
                print(f"snap[metrics] keys: {list(snap['metrics'].keys())}")
