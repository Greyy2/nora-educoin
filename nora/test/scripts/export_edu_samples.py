"""Xuất 50 mẫu giáo dục (frontend/src/components/education/educationSamples.js) ra data/education/samples.json để job backend đọc.

Cùng trường với bản JS: key, name, category, difficulty, position (tuỳ chọn), summary, code.
Chạy:  ops/run_limited.sh --no-lock -- test/scripts/export_edu_samples.py [--check]
  --check  không ghi, thoát mã 1 nếu samples.json đã cũ so với file JS (dùng trong CI).
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import lint_edu_samples as L  # noqa: E402

sys.path.insert(0, L._NORA)
from backend.models.storage import alpha_education_samples

OUT = alpha_education_samples()
FIELDS = ("key", "name", "category", "difficulty", "position", "summary", "code")


def build():
    out = []
    for s in L.load_samples():
        row = {k: s[k] for k in FIELDS if k in s}
        out.append(row)
    return out


def main():
    text = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur != text:
            print("samples.json đã cũ: chạy lại export_edu_samples.py")
            sys.exit(1)
        print("samples.json khớp educationSamples.js")
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"đã ghi {OUT} ({len(json.loads(text))} mẫu)")


if __name__ == "__main__":
    main()
