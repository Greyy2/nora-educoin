"""Thư viện chiến lược: mỗi CHIẾN LƯỢC (không phải mỗi alpha / khung giờ) = Ý tưởng -> Công thức bằng lời -> Công thức toán học -> Thống kê.

Công thức dựng từ CÂY KHUÔN của chiến lược (strategy/book.py CANDIDATES: "ema_{ema_n}", {"param": "k_up"}, khung "{signal_tf}") nên là dạng KÝ HIỆU,
đúng cấu trúc engine đang chạy; nhãn tham số lấy từ params_schema. Thống kê = các alpha đã qua kiểm định của chiến lược đó trong sổ chính + sổ thử nghiệm
(mọi khung giờ gộp chung). Danh mục: STRATEGIES; chiến lược có "doc": "combined" (Sideway) là MỘT mục gồm cả hai chiều.

    catalog() -> {"sources": [{"key": "nora", "label": "Nora", "strategies": [{key, name, kind, side, idea, plain, math, summary, stats}, ...]}]}
    plain: câu tiếng Việt, ký hiệu toán nằm trong $…$ (UI hiện bằng KaTeX nội dòng).
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.core.signals.kernels import REGISTRY

FRAME_VI = {"1m": "1 phút", "5m": "5 phút", "15m": "15 phút", "1h": "1 giờ", "4h": "4 giờ", "24h": "ngày"}
CMP_LATEX = {"<": "<", ">": ">", "<=": r"\le", ">=": r"\ge"}
CMP_VI = {"<": "<", ">": ">", "<=": "≤", ">=": "≥"}
PRICE = {"close": ("C", "giá đóng cửa"), "open": ("O", "giá mở cửa"), "high": ("H", "giá cao"), "low": ("L", "giá thấp")}
BAND = {"bbl": ("BB", "lo", "dải dưới Bollinger"), "bbu": ("BB", "up", "dải trên Bollinger"), "bbm": ("BB", "mid", "đường giữa Bollinger"),
        "kcl": ("KC", "lo", "dải dưới Keltner"), "kcu": ("KC", "up", "dải trên Keltner"), "kcm": ("KC", "mid", "đường giữa Keltner")}
STAT_KEYS = ("ret_pct", "extreme_ret_pct", "mdd_pct", "extreme_mdd_pct", "sharpe", "sortino", "profit_factor", "win_rate", "trades", "symbols_positive")
# Tổng hợp cấp chiến lược trên các alpha đã đạt: lợi nhuận / tỷ số = trung bình; MDD = xấu nhất; số lệnh = tổng
SUMMARY = {"ret_pct": "mean", "extreme_ret_pct": "mean", "mdd_pct": "max", "extreme_mdd_pct": "max", "sharpe": "mean", "sortino": "mean",
           "profit_factor": "mean", "win_rate": "mean", "trades": "sum"}
STAGES = ("FINAL", "S6_holdout", "S5_sizing", "S4_montecarlo", "S3_wfa", "S2_antiluck", "S1_backtest")
_PH = re.compile(r"\{(\w+)\}")



def vn(x: Any) -> str:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return str(x)
    return f"{float(x):.4f}".rstrip("0").rstrip(".").replace(".", ",")


# ─── Ký hiệu tham số ────────────────────────────────────────────────────────
def psym(name: str) -> str:
    """Tên tham số khuôn -> ký hiệu: rsi_lo -> θ^{RSI}_{lo}; gate_er_max -> θ^{ER}_{gate}; k_up -> k_{up}; ema_n -> n."""
    t = name.split("_")
    rest = r"\_".join(t[1:])
    if t[0] == "gate" and len(t) > 1 and t[1] in REGISTRY:
        return rf"\theta^{{\mathrm{{{t[1].upper()}}}}}_{{\mathrm{{gate}}}}"
    if t[0] in REGISTRY and len(t) > 1 and t[-1] not in ("n", "k", "m"):
        return rf"\theta^{{\mathrm{{{t[0].upper()}}}}}_{{\mathrm{{{rest}}}}}"
    if len(t) > 1 and t[-1] in ("n", "k", "m"):
        return t[-1]
    return rf"{t[0]}_{{\mathrm{{{rest}}}}}" if len(t) > 1 else t[0]


def fsym(frame: str) -> str:
    m = _PH.fullmatch(frame)
    return rf"\tau_{{\mathrm{{{m.group(1).replace('_tf', '')}}}}}" if m else rf"\mathrm{{{frame}}}"


def _label(schema: Dict[str, Any], name: str) -> str:
    return str((schema.get(f"sig.{name}") or schema.get(name) or {}).get("label_vi") or name)


def pword(name: str, schema: Dict[str, Any]) -> str:
    """Tên tham số bằng lời: ngưỡng (…_lo/_hi/_max/gate_…) gọi là "ngưỡng …"; còn lại dùng nhãn schema (vd "hệ số dải trên")."""
    t = name.split("_")
    if t[0] == "gate":
        return "ngưỡng dồn"
    if t[0] in REGISTRY and t[-1] in ("lo", "hi", "max", "min"):
        return {"lo": "ngưỡng thấp", "hi": "ngưỡng cao", "max": "ngưỡng", "min": "ngưỡng"}[t[-1]]
    return _label(schema, name).lower()


# ─── Toán hạng / điều kiện: (LaTeX, lời) ──────────────────────────────────────
def operand(item: Any, schema: Dict[str, Any], t: str = "t") -> Tuple[str, str]:
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        return vn(item).replace(",", "."), vn(item)
    if not isinstance(item, dict):
        return r"\varnothing", "—"
    if "param" in item:
        return psym(item["param"]), pword(item["param"], schema)
    if item.get("type") == "calculate":
        a, b = operand(item.get("number_1"), schema, t), operand(item.get("number_2"), schema, t)
        if item.get("logic") == "*":
            return rf"{b[0]}\cdot {a[0]}", f"{b[1]} × {a[1]}"
        op = {"+": "+", "-": "-", "/": "/"}.get(item.get("logic"), "?")
        return rf"{a[0]}{op}{b[0]}", f"{a[1]} {op} {b[1]}"
    if "column" in item:
        lag = int(item.get("index", 0) or 0)
        tt = t if not lag else f"{t}-{lag}"
        frame = str(item.get("frame", ""))
        fl = fsym(frame)
        col = str(item["column"])
        kernel = col.split("_", 1)[0]
        subs = [psym(p) for p in _PH.findall(col)]
        if col in PRICE:
            out = (rf"{PRICE[col][0]}^{{{fl}}}_{{{tt}}}", PRICE[col][1])
        elif kernel in BAND:
            sym, band, words = BAND[kernel]
            out = (rf"\mathrm{{{sym}}}^{{\mathrm{{{band}}},{fl}}}_{{{','.join(subs)}}}({tt})", words)
        elif kernel in REGISTRY:
            fw = _label(schema, frame.strip("{}")).lower() if _PH.fullmatch(frame) else frame
            note = f" ({fw})" if frame != schema.get("_main_frame") else ""
            out = (rf"\mathrm{{{kernel.upper()}}}^{{{fl}}}_{{{','.join(subs)}}}({tt})", kernel.upper() + note)
        else:
            out = (rf"\mathrm{{{col}}}({tt})", col)
        if "add" in item:
            m = operand(item["add"], schema, tt)
            out = (rf"{out[0]}+{m[0]}", f"{out[1]} + {m[1]}")
        if "subtract" in item:
            m = operand(item["subtract"], schema, tt)
            out = (rf"{out[0]}-{m[0]}", f"{out[1]} − {m[1]}")
        return out
    return r"\varnothing", "—"


def _shift(item: Any) -> Any:
    if isinstance(item, list):
        return [_shift(x) for x in item]
    if not isinstance(item, dict):
        return item
    return {k: (int(v or 0) + 1 if k == "index" and "column" in item else _shift(v)) for k, v in item.items()}


def _off_by_default(c: List[Any]) -> bool:
    """Ngưỡng mặc định nằm ngoài miền chỉ báo (vd gate_rsi = 101) = điều kiện TUỲ CHỌN, mặc định tắt."""
    left, op, right = c
    if not (isinstance(right, dict) and "default" in right and isinstance(left, dict) and "column" in left):
        return False
    spec = REGISTRY.get(str(left["column"]).split("_", 1)[0])
    if spec is None or ".." not in spec.unit:
        return False
    lo, hi = (float(x) for x in spec.unit.split(".."))
    v = float(right["default"])
    return (op in ("<", "<=") and v > hi) or (op in (">", ">=") and v < lo)


def conditions(tree: Any, schema: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Cây khuôn (OR các khối, AND trong khối) -> (dòng LaTeX, câu). Cặp (x > y tại t, x ≤ y tại t−1) gộp thành "cắt lên"."""
    tex, words = [], []
    blocks = [b for b in (tree or []) if isinstance(b, list) and b]
    for bi, block in enumerate(blocks):
        used = set()
        bt, bw = [], []
        for i, a in enumerate(block):
            if i in used:
                continue
            pair = next((j for j, b in enumerate(block) if j != i and j not in used and (a[1], b[1]) in ((">", "<="), ("<", ">="))
                         and b[0] == _shift(a[0]) and b[2] == _shift(a[2])), None)
            l, r = operand(a[0], schema), operand(a[2], schema)
            opt = " (tuỳ chọn, mặc định tắt)" if _off_by_default(a) else ""
            if pair is not None:
                used.update((i, pair))
                l1, r1 = operand(a[0], schema, "t-1"), operand(a[2], schema, "t-1")
                rev = {">": r"\le", "<": r"\ge"}[a[1]]
                bt.append(rf"{l[0]}{CMP_LATEX[a[1]]}{r[0]}\ \land\ {l1[0]}{rev}{r1[0]}")
                bw.append(f"{l[1]} cắt {'lên trên' if a[1] == '>' else 'xuống dưới'} {r[1]}")
            else:
                bt.append(rf"{l[0]}{CMP_LATEX.get(a[1], a[1])}{r[0]}")
                bw.append(f"{l[1]} {CMP_VI.get(a[1], a[1])} {r[1]}{opt}")
        tex.append(r"\ \land\ ".join(bt))
        words.append(" và ".join(bw))
    if len(tex) > 1:
        tex = [r"\ \lor\ ".join(rf"({x})" for x in tex)]
        words = [" HOẶC ".join(f"({w})" for w in words)]
    return tex, words


# ─── Một mục chiến lược ─────────────────────────────────────────────────────
def _exits(cand: Dict[str, Any], side: str) -> Tuple[List[str], List[str]]:
    sch = cand.get("params_schema") or {}
    adv, fav = {"LONG": ("-", "+"), "SHORT": ("+", "-")}.get(side, (r"\mp ", r"\pm "))   # hai chiều: dấu trên = Long, dấu dưới = Short
    tex = [r"\nu=\mathrm{ATR\%}(t_0)"]
    words = []
    if "dca_step_pct" in sch:
        cmp_ = r"\le" if side == "LONG" else r"\ge"
        tex.append(rf"P_k=P_{{k-1}}(1{adv}s\,\nu),\quad q_k=q_0\,m^{{k}},\quad k\le K,\quad \mathrm{{Gate}}_t=1")
        words.append("Giá đi ngược thì dồn tầng $k$ cách tầng trước $s\\nu$ ($\\nu$ = ATR%), khối lượng ×$m$ mỗi tầng, tối đa $K$ tầng — chỉ khi điều kiện dồn còn đúng.")
    pbar = r"\bar P" if "dca_step_pct" in sch else r"P_0"
    ref = "giá trung bình" if "dca_step_pct" in sch else "giá vào"
    tex.append(rf"\mathrm{{SL}}={pbar}(1{adv}s_L\nu),\quad \mathrm{{TP}}={pbar}(1{fav}s_T\nu)")
    words.append(f"Cắt lỗ $s_L\\nu$, chốt lời $s_T\\nu$ tính từ {ref}.")
    if "trailing_stop" in sch:
        ext = {"LONG": r"\max H", "SHORT": r"\min L"}.get(side, r"\max H\ /\ \min L")
        tex.append(rf"\mathrm{{Trail}}=P^*(1{adv}s_R\nu),\quad P^*={ext},\quad \frac{{|P^*-{pbar}|}}{{{pbar}}}\ge a\,\nu")
        words.append("Trailing: lãi đạt $a\\nu$ thì bật, dừng cách đỉnh lãi $s_R\\nu$.")
    return tex, words


def _sizing() -> Tuple[str, str]:
    return (r"N=\min\!\left(\frac{E\,r}{s_L\nu+2(f+\epsilon)},\ E\,c\right),\quad \lambda\le\left\lfloor\frac{1}{1.5\,s_L\nu+\mathrm{mmr}}\right\rfloor",
            "Khối lượng tính ngược từ rủi ro: chạm cắt lỗ (gồm mọi tầng, phí, trượt) chỉ mất $r$% vốn; đòn bẩy tự hạ để luôn cắt lỗ trước khi thanh lý.")


def _main_frame(tree: Any) -> Optional[str]:
    """Khung của toán hạng giá đầu tiên trong cây (khung vào lệnh) — chỉ báo ở khung khác được ghi chú khung."""
    for block in tree or []:
        for c in block:
            for x in (c[0], c[2]):
                if isinstance(x, dict) and x.get("column") in PRICE:
                    return str(x.get("frame"))
    return None


def leg_doc(cand: Dict[str, Any], label: str = "") -> Dict[str, Any]:
    sch = {**(cand.get("params_schema") or {}), "_main_frame": _main_frame(cand.get("tree"))}
    side = cand["side"]
    sv = "Long" if side == "LONG" else "Short"
    plain, math = [], []
    e_tex, e_w = conditions(cand.get("tree"), sch)
    pre = f"{label} " if label else ""
    math.append({"title": f"{pre}Vào lệnh", "latex": rf"\mathrm{{Entry}}^{{\mathrm{{{sv.lower()}}}}}_t=\mathbb{{1}}\left[{e_tex[0]}\right]"})
    plain.append(f"{pre}vào lệnh khi {e_w[0]}." if label else f"Vào {sv} khi {e_w[0]}.")
    if cand.get("stop"):
        x_tex, x_w = conditions(cand.get("stop"), sch)
        math.append({"title": f"{pre}Thoát (đảo chiều)", "latex": rf"\mathrm{{Exit}}_t=\mathbb{{1}}\left[{x_tex[0]}\right]"})
        plain.append(f"{pre}Thoát khi {x_w[0]}.")
    if cand.get("dca_gate"):
        g_tex, g_w = conditions(cand.get("dca_gate"), sch)
        math.append({"title": f"{pre}Được phép dồn", "latex": rf"\mathrm{{Gate}}_t=\mathbb{{1}}\left[{g_tex[0]}\right]"})
        plain.append(f"{pre}Chỉ dồn khi {g_w[0]}.")
    return {"plain": plain, "math": math, "side": side}


def _alphas_of(leg_ids: List[str], books: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out = []
    for kind, book in books:
        for it in book.get("strategies") or []:
            if it.get("id") not in leg_ids:
                continue
            sm = ((it.get("evidence") or {}).get("stage_metrics") or {})
            stage = next((s for s in STAGES if sm.get(s)), None)
            m = sm.get(stage) or {}
            out.append({"leg": it["id"], "side": it.get("side"), "timeframe": book.get("timeframe"), "book": kind,
                        "alpha_id": (it.get("evidence") or {}).get("funnel_alpha_id"), "stage": stage,
                        "universe": len(book.get("universe") or []),
                        **{k: m.get(k) for k in STAT_KEYS}})
    return out


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Chỉ số tổng hợp của chiến lược trên các alpha đã đạt (quy tắc SUMMARY); không có alpha -> {"n": 0}."""
    out: Dict[str, Any] = {"n": len(rows)}
    for key, how in SUMMARY.items():
        v = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
        if v:
            out[key] = round(sum(v) / len(v), 4) if how == "mean" else (max(v) if how == "max" else int(sum(v)))
    return out


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _user_card_metrics(sim: Any) -> Dict[str, Any]:
    """Số đo thẻ alpha người dùng từ metrics.simulate của kết quả đã lưu: khoá và đơn vị CHỈ lấy từ trường tường minh (khối nora: ret_pct, mdd_pct, sharpe, sortino, win_rate_trades %,
    profit_factor_trades; thiếu khối nora thì khối xno: cumulative_return/max_drawdown là phân số ×100). Thiếu -> None (giao diện hiện "—"), không bao giờ 0 giả; số 0 thật được giữ."""
    from backend.core.analytics.user_alphas import _first_num
    nora, xno = (sim or {}).get("nora") or {}, (sim or {}).get("xno") or {}

    def pct(v):
        return None if v is None else v * 100.0
    mdd = _first_num(nora, "mdd_pct")
    xmdd = _first_num(xno, "max_drawdown")
    trades = _first_num(nora, "trades")
    return {
        "ret_pct": _first_num(nora, "ret_pct") if _first_num(nora, "ret_pct") is not None else pct(_first_num(xno, "cumulative_return")),
        "mdd_pct": abs(mdd) if mdd is not None else (abs(xmdd) * 100.0 if xmdd is not None else None),
        "sharpe": _first_num(nora, "sharpe") if _first_num(nora, "sharpe") is not None else _first_num(xno, "sharpe"),
        "sortino": _first_num(nora, "sortino") if _first_num(nora, "sortino") is not None else _first_num(xno, "sortino"),
        "profit_factor": _first_num(nora, "profit_factor_trades"),
        "win_rate": _first_num(nora, "win_rate_trades"),
        "trades": int(trades) if trades is not None else None,
    }


def catalog(alphas_dir: Optional[str] = None) -> Dict[str, Any]:
    from backend.core.strategy.book import BY_ID, STRATEGIES
    if alphas_dir is None:
        from backend.core.params.presets import alphas_dir as _ad
        alphas_dir = _ad()
    books = [(k, b) for k, b in (("main", _read(os.path.join(alphas_dir, "book.json"))),
                                 ("explore", _read(os.path.join(alphas_dir, "explore", "book.json")))) if b]
    sizing_tex, sizing_w = _sizing()
    items = []
    for st in STRATEGIES:
        legs = st["legs"]
        groups = [list(legs.items())] if st.get("doc") == "combined" else [[x] for x in legs.items()]
        for group in groups:
            cands = [BY_ID[cid] for _, cid in group]
            label = len(group) > 1
            docs = [leg_doc(c, ("Long:" if c["side"] == "LONG" else "Short:") if label else "") for c in cands]
            ex_tex, ex_w = _exits(cands[0], "BOTH" if label else cands[0]["side"])
            if label:
                ex_w.append("Hai chiều đối xứng: dấu trên cho Long, dấu dưới cho Short.")
            items.append({
                "key": "_".join([st["id"]] + ([] if label else [group[0][0].lower()])),
                "strategy": st["id"], "name": st["name"], "kind": st["kind"],
                "side": "Long + Short" if label else ("Long" if group[0][0] == "LONG" else "Short"),
                "idea": st["idea"],
                "plain": [p for d in docs for p in d["plain"]] + ex_w + [sizing_w],
                "math": [m for d in docs for m in d["math"]] + [{"title": "Dồn lệnh & thoát lệnh" if "dca_step_pct" in (cands[0].get("params_schema") or {})
                                                                        else "Thoát lệnh", "latex": r" \\ ".join(ex_tex)},
                                                               {"title": "Khối lượng", "latex": sizing_tex}],
            })
            items[-1]["stats"] = _alphas_of([cid for _, cid in group], books)
            items[-1]["summary"] = summarize(items[-1]["stats"])

    # Nhóm Alpha người dùng (C1)
    from backend.core.analytics import user_alphas
    uas = user_alphas.list_user_alphas(base_dir=alphas_dir)
    for ua in uas:
        if ua.get("status") == "ARCHIVED":
            continue
        code = ua.get("code", "")
        plain_lines = []
        try:
            from backend.core.strategy.pydsl import compile_code
            from backend.core.strategy.pydsl.explain import explain_program
            prog = compile_code(code, register=False)
            exp = explain_program(prog, profile=ua.get("profile", "xno"), position=(ua.get("config") or {}).get("position"))
            plain_lines = [r["action_vi"] for r in exp.get("rules", [])] + [e["desc"] for e in exp.get("execution", [])[:2]]
        except Exception:
            plain_lines = [ua.get("note") or "Chiến lược người dùng đã xác minh"]

        stat_item = {
            "leg": ua["id"],
            "side": "LONG" if (ua.get("config", {}).get("program", {}) or {}).get("legs") == ["LONG"] else "BOTH",
            "timeframe": (ua.get("config", {}) or {}).get("timeframe", "24h"),
            "book": "user",
            "alpha_id": ua["id"],
            "stage": ua.get("status", "SAVED"),
            "universe": len((ua.get("config", {}) or {}).get("symbols") or []),
            **_user_card_metrics((ua.get("metrics") or {}).get("simulate")),
        }
        items.append({
            "key": f"user_{ua['id']}",
            "strategy": ua["id"],
            "name": ua["name"],
            "kind": "Alpha người dùng",
            "side": "Long" if (ua.get("config", {}).get("program", {}) or {}).get("legs") == ["LONG"] else "Long + Short",
            "idea": ua.get("note") or f"Alpha người dùng từ nguồn {ua.get('source', 'alpha-create')}",
            "plain": plain_lines,
            "math": [{"title": "Cấu hình thực thi", "latex": rf"\mathrm{{{ua.get('profile', 'xno')}}}"}],
            "stats": [stat_item],
            "summary": {
                "n": 1,
                "ret_pct": stat_item["ret_pct"],
                "mdd_pct": stat_item["mdd_pct"],
                "sharpe": stat_item["sharpe"],
                "sortino": stat_item["sortino"],
                "profit_factor": stat_item["profit_factor"],
                "win_rate": stat_item["win_rate"],
                "trades": stat_item["trades"],
            },
            "is_user_alpha": True,
            "alpha_id": ua["id"],
        })

    return {"sources": [{"key": "nora", "label": "Nora", "strategies": items}]}

