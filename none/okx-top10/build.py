#!/usr/bin/env python3
"""Build site/index.html from template.html + bots.json + summary.json (re-runnable)."""
import json, shutil, re, sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"


def blob(path):
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # keep the JSON valid but safe inside <script>
    return s.replace("</", "<\\/").replace("<!--", "\\u003c!--")


def main():
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    for token in ("{{DATA_JSON}}", "{{SUMMARY_JSON}}"):
        assert tpl.count(token) == 1, token
    html = tpl.replace("{{DATA_JSON}}", blob("bots.json")).replace(
        "{{SUMMARY_JSON}}", blob("summary.json"))
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(html, encoding="utf-8")
    print(f"site/index.html {len(html.encode('utf-8'))} bytes")
    for name in ("candles", "candles15"):
        src, dst = ROOT / name, SITE / name
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst)
            print(f"site/{name}: {len(list(dst.glob('*.json')))} files")
        else:
            print(f"site/{name}: source missing, skipped")


# ---------------------------------------------------------------- standalone mode
STEPS = {"1h": ("candles", 3600000), "15m": ("candles15", 900000)}
DROP = {"AXS"}  # no bot trades it


def _dec(v):
    q = Decimal(repr(float(v))).quantize(Decimal("1e-12"))
    s = format(q, "f")
    return len(s.split(".")[1].rstrip("0")) if "." in s else 0


def encode(bars, step):
    ts0 = bars[0][0]
    for i, b in enumerate(bars):
        assert b[0] == ts0 + i * step, "gap"
    d = max(_dec(v) for b in bars for v in b[1:])
    m = 10 ** d
    flat = [round(v * m) for b in bars for v in b[1:]]
    prev, out = 0, []
    for x in flat:
        out.append(x - prev)
        prev = x
    return [ts0, step, d, ",".join(map(str, out))]


def decode(e):
    ts0, step, d, ds = e
    m, acc, vals = 10 ** d, 0, []
    for x in ds.split(","):
        acc += int(x)
        vals.append(acc / m)
    return [[ts0 + i * step] + vals[4 * i:4 * i + 4] for i in range(len(vals) // 4)]


def build_candles():
    out, raw = {}, 0
    for tf, (dirname, step) in STEPS.items():
        out[tf] = {}
        for f in sorted((ROOT / dirname).glob("*.json")):
            sym = f.stem
            if sym in DROP:
                continue
            text = f.read_text()
            raw += len(text)
            bars = json.loads(text)
            if not bars:
                continue
            e = encode(bars, step)
            back = decode(e)
            assert len(back) == len(bars), (tf, sym)
            for a, b in zip(bars, back):
                assert a[0] == b[0]
                for x, y in zip(a[1:], b[1:]):
                    assert abs(x - y) <= 1e-9 * max(abs(x), 1e-12), (tf, sym, x, y)
            out[tf][sym] = e
    return out, raw


LOADER = ("    cache.set(key,new Promise(function(res){var e=CD[tf]&&CD[tf][sym];if(!e){res(null);return;}"
          "var ts=e[0],st=e[1],m=Math.pow(10,e[2]),p=e[3].split(','),n=p.length>>2,a=new Array(n),acc=0,i,k,r;"
          "for(i=0;i<n;i++){r=[ts+i*st,0,0,0,0];for(k=1;k<5;k++){acc+=+p[4*i+k-1];r[k]=acc/m;}a[i]=r;}"
          "res(a.length?a:null);}));\n")


def standalone(target):
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    for token in ("{{DATA_JSON}}", "{{SUMMARY_JSON}}"):
        assert tpl.count(token) == 1, token
    # split head part (title/link/style) from body
    i = tpl.index("</style>") + len("</style>")
    head, body = tpl[:i], tpl[i:]
    extra = ""
    if not re.search(r"\bbody\s*\{[^}]*margin:\s*0", head):
        extra += "body{margin:0}"
    if "[hidden]{display:none" not in head:
        extra += "[hidden]{display:none!important}"
    if "img{max-width" not in head:
        extra += "img{max-width:100%}"
    if extra:
        head = head.replace("</style>", extra + "\n</style>")
    lwc = (ROOT / "lwc.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    tag = '<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>'
    assert body.count(tag) == 1
    body = body.replace(tag, "<script>" + lwc + "</script>")
    cd, raw = build_candles()
    cdj = json.dumps(cd, separators=(",", ":")).replace("</", "<\\/")
    body = body.replace('<script type="application/json" id="data">',
                        '<script type="application/json" id="cd">' + cdj + '</script>\n<script type="application/json" id="data">')
    # loader
    pat = re.compile(r"^    cache\.set\(key,fetch\(.*$\n", re.M)
    assert len(pat.findall(body)) == 1
    body = pat.sub(lambda m: LOADER, body)
    body = body.replace("var cache=new Map();",
                        "var cache=new Map();var CD=JSON.parse(document.getElementById('cd').textContent);", 1)
    assert "var CD=" in body
    body = body.replace("{{DATA_JSON}}", blob("bots.json")).replace("{{SUMMARY_JSON}}", blob("summary.json"))
    doc = ('<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
           + head.replace("</style>", "</style>", 1) + "\n</head><body>" + body + "\n</body></html>\n")
    Path(target).write_text(doc, encoding="utf-8")
    sizes = {"lwc": len(lwc), "candles_json": len(cdj), "candles_raw_files": raw,
             "bots": len(blob("bots.json")), "summary": len(blob("summary.json")), "total": len(doc.encode("utf-8"))}
    print(target, sizes)


if __name__ == "__main__":
    if "--standalone" in sys.argv:
        standalone(sys.argv[sys.argv.index("--standalone") + 1])
    else:
        main()
