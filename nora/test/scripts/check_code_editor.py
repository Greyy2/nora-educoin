#!/usr/bin/env python3
"""Hồi quy trình soạn code (frontend/src/components/studio/CodeEditor.jsx) trên /alpha/create và /education, chạy trong Chrome THẬT (Playwright).

Lỗi gốc đã sửa ("gõ dòng dưới nó nhảy lên dòng trên"): textarea và lớp tô màu cuộn RIÊNG, đồng bộ scrollTop bằng JS; thanh cuộn (15px) của textarea làm vùng cuộn tối đa của nó
lớn hơn lớp tô màu nên ở cuối file chữ hiển thị lệch ~1 dòng so với con trỏ. Nay chỉ còn MỘT khung cuộn; kịch bản dưới đây gõ nhiều dòng (Enter + tự thụt lề), Tab / Shift+Tab,
Backspace ở đầu dòng, dán, bấm chuột vào dòng dưới rồi gõ, và ở MỖI bước kiểm: nội dung textarea, vị trí con trỏ, chữ tô màu của dòng chứa con trỏ trùng khít textarea
(lệch < 1px), textarea không tự cuộn, con trỏ nằm trong vùng nhìn thấy.

Chạy (cần `npm run build` + API đang chạy; python có playwright, vd. /usr/bin/python3):
    python3 test/scripts/check_code_editor.py [--url http://localhost:18010] [--chrome /usr/bin/google-chrome] [--shots DIR]
Thoát mã 0 nếu mọi kiểm tra đạt.
"""
import argparse
import os
import sys

from playwright.sync_api import sync_playwright

LINE_H, PAD_T = 19, 10
STATE_JS = """() => {
  const t = document.querySelector('textarea.se-ta'), sc = document.querySelector('.se-ed');
  const before = t.value.slice(0, t.selectionStart);
  const row = before.split('\\n').length - 1;
  const lns = document.querySelectorAll('.se-ln');
  const l = lns[row].getBoundingClientRect(), tr = t.getBoundingClientRect(), sr = sc.getBoundingClientRect();
  return {value: t.value, sel: t.selectionStart, selEnd: t.selectionEnd, row, nlines: t.value.split('\\n').length, nHl: lns.length,
          hlTop: l.top, taTop: tr.top + %d + row * %d, scTop: sc.scrollTop, view: [sr.top, sr.bottom - 44 - (sc.offsetHeight - sc.clientHeight)],
          bar: [sc.offsetWidth - sc.clientWidth, sc.offsetHeight - sc.clientHeight], taScroll: [t.scrollTop, t.scrollLeft]};
}""" % (PAD_T, LINE_H)

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("  FAIL", msg)


def state(pg):
    return pg.evaluate(STATE_JS)


def aligned(pg, label):
    """Chữ tô màu của dòng chứa con trỏ trùng textarea; textarea không tự cuộn; số dòng tô màu = số dòng textarea; con trỏ nằm trong vùng nhìn thấy."""
    s = state(pg)
    check(abs(s["hlTop"] - s["taTop"]) < 1.0, f"{label}: dòng tô màu lệch textarea {s['hlTop'] - s['taTop']:.1f}px")
    check(s["taScroll"] == [0, 0], f"{label}: textarea tự cuộn {s['taScroll']}")
    check(s["nHl"] == s["nlines"], f"{label}: {s['nHl']} dòng tô màu ≠ {s['nlines']} dòng textarea")
    top = s["hlTop"]
    check(s["view"][0] - 1 <= top and top + LINE_H <= s["view"][1] + 1, f"{label}: con trỏ ngoài vùng nhìn thấy (dòng {s['row']}, y={top:.0f}, vùng={s['view']})")
    return s


def run_page(pg, url):
    print(url)
    pg.goto(url)
    pg.wait_for_selector("textarea.se-ta")
    ta = pg.locator("textarea.se-ta")
    ta.click()
    pg.keyboard.press("Control+A")
    pg.keyboard.press("Delete")
    check(state(pg)["value"] == "", "xoá hết không về rỗng")

    # 1. nhiều dòng với Enter: giữ thụt lề, thêm 4 dấu cách sau dòng kết thúc bằng ':'
    pg.keyboard.type("class A(SimpleAlgorithm):")
    pg.keyboard.press("Enter")
    pg.keyboard.type("def f(self):")
    pg.keyboard.press("Enter")
    pg.keyboard.type("x = 1")
    pg.keyboard.press("Enter")
    pg.keyboard.type("y = 2")
    s = aligned(pg, "enter/auto-indent")
    check(s["value"] == "class A(SimpleAlgorithm):\n    def f(self):\n        x = 1\n        y = 2", f"auto-indent sai: {s['value']!r}")
    check(s["sel"] == len(s["value"]), "con trỏ không ở cuối sau khi gõ")

    # 2. Tab / Shift+Tab ở dòng trống mới
    pg.keyboard.press("Enter")
    pg.keyboard.press("Tab")
    s = aligned(pg, "tab")
    check(s["value"].endswith("y = 2\n" + " " * 8 + "    "), f"Tab không thụt 4 dấu cách: {s['value'][-20:]!r}")
    pg.keyboard.press("Shift+Tab")
    s = aligned(pg, "shift+tab")
    check(s["value"].endswith("y = 2\n" + " " * 8), f"Shift+Tab không bớt 4 dấu cách: {s['value'][-20:]!r}")

    # 3. Backspace ở đầu dòng: dồn dòng lên dòng trên, con trỏ đúng chỗ nối
    pg.keyboard.press("Home")
    n0 = state(pg)["nlines"]
    pg.keyboard.press("Backspace")   # ở cột 0: nối với dòng trên
    s = aligned(pg, "backspace đầu dòng")
    check(s["nlines"] == n0 - 1, f"Backspace ở đầu dòng không nối dòng ({n0} -> {s['nlines']})")
    check(s["value"].split("\n")[-1] == " " * 8 + "y = 2" + " " * 8, f"dòng nối sai: {s['value'].splitlines()[-1]!r}")
    check(s["sel"] == len(s["value"]) - 8, f"con trỏ sau Backspace không ở chỗ nối (sel={s['sel']})")

    # 4. dán nhiều dòng (không qua bàn phím): input event, con trỏ ở cuối đoạn dán
    pg.keyboard.press("End")
    pg.keyboard.press("Enter")
    pg.keyboard.insert_text("a = 1\nb = 2\n")
    s = aligned(pg, "dán")
    check(s["value"].endswith("a = 1\nb = 2\n") and s["sel"] == len(s["value"]), f"dán sai: sel={s['sel']} len={len(s['value'])}")

    # 5. tài liệu dài + dòng rất dài (ra cả thanh cuộn dọc lẫn ngang): gõ ở cuối file
    pg.keyboard.press("Control+A")
    pg.keyboard.press("Delete")
    for i in range(70):
        pg.keyboard.type(f"line{i} = {i}")
        pg.keyboard.press("Enter")
    pg.keyboard.type("z = " + "1 + " * 80 + "1")
    s = aligned(pg, "cuối file dài")
    if s["bar"] == [0, 0]:
        print("  (cảnh báo: trình duyệt dùng thanh cuộn nổi — lỗi gốc chỉ lộ với thanh cuộn cổ điển; chạy lại với chrome có thanh cuộn)")
    check(s["row"] == 70 and s["scTop"] > 0, f"không cuộn tới dòng cuối (row={s['row']}, scTop={s['scTop']})")
    pg.keyboard.press("Enter")
    pg.keyboard.type("last = 1")
    s = aligned(pg, "dòng mới ở cuối")
    check(s["value"].endswith("\nlast = 1") and s["row"] == 71, "gõ dòng mới ở cuối bị lệch dòng")

    # 6. lên giữa file bằng phím rồi gõ; con trỏ + nội dung đúng dòng
    for _ in range(30):
        pg.keyboard.press("ArrowUp")
    pg.keyboard.press("End")
    pg.keyboard.type("Z")
    s = aligned(pg, "giữa file")
    lines = s["value"].split("\n")
    check(lines[s["row"]].endswith("Z") and s["row"] == 71 - 30, f"ký tự gõ không nằm ở đúng dòng: row={s['row']} {lines[s['row']]!r}")

    # 7. bấm chuột vào một dòng đang hiển thị (dòng dưới), gõ: chữ phải vào ĐÚNG dòng bấm
    for target in (0.25, 0.6, 0.9):
        box = pg.evaluate("""(f) => { const sc = document.querySelector('.se-ed').getBoundingClientRect();
            const lns = [...document.querySelectorAll('.se-ln')].map((e, i) => [i, e.getBoundingClientRect()])
              .filter(([, r]) => r.top >= sc.top + 4 && r.bottom <= sc.bottom - 50);
            const [i, r] = lns[Math.floor(lns.length * f)]; return {i, x: sc.left + 120, y: r.top + r.height / 2}; }""", target)
        pg.mouse.click(box["x"], box["y"])
        pg.keyboard.press("End")
        pg.keyboard.type("Q")
        s = aligned(pg, f"bấm chuột dòng {box['i']}")
        lines = s["value"].split("\n")
        check(s["row"] == box["i"] and lines[box["i"]].endswith("Q"), f"bấm dòng {box['i']} nhưng gõ vào dòng {s['row']}")

    # 8. cuối cùng: dòng dưới cùng + Enter nhiều lần, không lệch dần
    pg.keyboard.press("Control+End")
    for k in range(25):
        pg.keyboard.press("Enter")
        pg.keyboard.type(f"t{k}")
    s = aligned(pg, "gõ liên tục ở cuối")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:18010")
    ap.add_argument("--chrome", default=None, help="đường dẫn chrome/chromium; mặc định: chromium của playwright, lùi về /usr/bin/google-chrome")
    ap.add_argument("--shots", default=None, help="thư mục lưu ảnh chụp màn hình sau kịch bản")
    a = ap.parse_args()
    with sync_playwright() as p:
        kw = {"ignore_default_args": ["--hide-scrollbars"]}      # thanh cuộn cổ điển như máy người dùng: nơi lỗi gốc lộ ra
        try:
            browser = p.chromium.launch(**({"executable_path": a.chrome, **kw} if a.chrome else kw))
        except Exception:  # noqa: BLE001
            browser = p.chromium.launch(executable_path=a.chrome or "/usr/bin/google-chrome", **kw)
        pg = browser.new_page(viewport={"width": 1400, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for path in ("/alpha/create", "/education"):
            run_page(pg, a.url.rstrip("/") + path)
            if a.shots:
                os.makedirs(a.shots, exist_ok=True)
                pg.screenshot(path=os.path.join(a.shots, "editor" + path.replace("/", "_") + ".png"))
        check(not errs, f"lỗi JS trong trang: {errs[:2]}")
        browser.close()
    print("ĐẠT" if not fails else f"THẤT BẠI: {len(fails)} lỗi")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
