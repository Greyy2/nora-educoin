"""Live view nhẹ cho các trang HTML trong none/: chỉ phục vụ thư mục này, chỉ theo dõi file .html trong đó,
tự tải lại trình duyệt khi file đổi (giữ nguyên #hash), nén gzip để file lớn tải nhanh qua remote.

Chạy:  python3 none/okx-top10/serve.py            (mặc định cổng 5501, thư mục none/)
       python3 none/okx-top10/serve.py --port 5502 --root /đường/dẫn/khác
Mở:    http://localhost:5501/okx-report.html
"""
import argparse
import gzip
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

SNIPPET = (b"<script>(function(){var es,t;function go(){es=new EventSource('/__live');"
           b"es.addEventListener('reload',function(){location.reload();});"
           b"es.onerror=function(){es.close();clearTimeout(t);t=setTimeout(go,2000);};}go();})();</script>")


class State:
    version = 0
    cond = threading.Condition()


def watch(root, interval=1.0):
    """Poll mtime/size of top-level .html files; bump version once a change has settled (writer finished)."""
    def snap():
        out = {}
        for n in os.listdir(root):
            if n.endswith(".html"):
                try:
                    st = os.stat(os.path.join(root, n))
                    out[n] = (st.st_mtime_ns, st.st_size)
                except FileNotFoundError:
                    pass
        return out
    last = snap()
    while True:
        time.sleep(interval)
        cur = snap()
        if cur != last:
            time.sleep(0.8)                       # đợi ghi xong
            settled = snap()
            if settled == cur:
                last = cur
                with State.cond:
                    State.version += 1
                    State.cond.notify_all()


_cache = {}


def html_bytes(path):
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1], hit[2]
    raw = open(path, "rb").read()
    i = raw.rfind(b"</body>")
    raw = raw[:i] + SNIPPET + raw[i:] if i >= 0 else raw + SNIPPET
    gz = gzip.compress(raw, 6)
    _cache[path] = (key, raw, gz)
    return raw, gz


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        p = self.path.split("?", 1)[0].split("#", 1)[0]
        if p == "/__live":
            return self.live()
        if p == "/":
            self.send_response(302)
            self.send_header("Location", "/okx-report.html")
            return self.end_headers()
        fs = self.translate_path(p)
        if fs.endswith(".html") and os.path.isfile(fs):
            raw, gz = html_bytes(fs)
            use_gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
            body = gz if use_gz else raw
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if use_gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def live(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        seen = State.version
        try:
            while True:
                with State.cond:
                    State.cond.wait(timeout=20)
                    v = State.version
                if v != seen:
                    seen = v
                    self.wfile.write(b"event: reload\ndata: 1\n\n")
                else:
                    self.wfile.write(b": ping\n\n")          # giữ kết nối qua proxy/port-forward
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5501)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--root", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    threading.Thread(target=watch, args=(root,), daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), lambda *x, **k: Handler(*x, directory=root, **k))
    srv.daemon_threads = True
    print(f"live view: http://localhost:{a.port}/okx-report.html  (root {root})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
