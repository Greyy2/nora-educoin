"""Nora API: app FastAPI duy nhất (uvicorn backend.main:app).

Mọi việc (backtest, WFA, Monte Carlo, danh mục) đi qua các router trong backend/routes;
UI, terminal (curl) và script đều gọi cùng các endpoint này. Bản build frontend (frontend/dist) được phục vụ ở "/".
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.jobs.runner import EphemeralGone, NotReady
from backend.nautilus.version import ENGINE_NAME, NAUTILUS_VERSION
from backend.routes import alpha, book, data, engine, live, process

app = FastAPI(title="Nora API", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)   # JSON thống kê/biểu đồ lớn (vài trăm KB) nén còn ~1/8; mức 5 thay mặc định 9: ~100 ms -> ~10 ms CPU/450 KB (nén chạy trong event loop, giữ GIL), file to hơn ~10%

for m in (process, alpha, book, data, live, engine):
    for r in m.ROUTERS:
        app.include_router(r)


@app.exception_handler(EphemeralGone)
def _ephemeral_gone(_request, exc: EphemeralGone):
    """Kết quả job tạm đã hết hạn -> 410 (khác 404 = id chưa từng có); detail.code để giao diện nhận biết."""
    return JSONResponse(status_code=410, content={"detail": {"code": exc.code, "message": str(exc), "job_id": exc.job_id}})


@app.exception_handler(NotReady)
def _not_ready(_request, exc: NotReady):
    """Tính năng Nautilus chưa hỗ trợ -> 501; detail.code = NOT_READY để giao diện hiện "chưa hỗ trợ"."""
    return JSONResponse(status_code=501, content={"detail": {"code": exc.code, "message": str(exc)}})


@app.on_event("startup")
def _enforce_job_lifecycle():
    """Cache chỉ giữ tiến trình chưa xong: job xong -> lưu/xoá, bot đã dừng -> xoá, job lỗi -> xoá, job huỷ còn tiến độ chạy dở (resume được) -> giữ PAUSED_KEEP_DAYS ngày, huỷ không có gì -> xoá (chạy nền, không chặn khởi động)."""
    import threading

    from backend.jobs import runner as batch_jobs
    threading.Thread(target=batch_jobs.enforce_lifecycle, name="job-lifecycle", daemon=True).start()


@app.get("/api/health")
def health():
    return {"ok": True, "engine": {"name": ENGINE_NAME, "version": NAUTILUS_VERSION}}


# ─── Giao diện (bản build Vite) ───────────────────────────────────────────────
WEB = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")

    def _index():
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

    @app.get("/")
    def index():
        return _index()

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, detail="API endpoint not found")
        f = WEB / path
        return FileResponse(f) if f.is_file() else _index()
