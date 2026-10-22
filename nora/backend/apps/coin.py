"""COIN API — FastAPI app độc lập (uvicorn backend.apps.coin:app --port 18010).

Phạm vi:
- Auth/Users/Sessions (chia sẻ cơ sở dữ liệu người dùng nhưng domain cookie độc lập)
- Studio: backtest, WFA, Monte Carlo, Alpha catalog, Research, Scan
- Live: Bot control, Paper/Testnet/Live trading, exchange credentials
- Data admin: crawl, promote, ticks
- Portfolio, Overview, History
- Engine version, Health

COIN KHÔNG có quyền: EDU private user/content data.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.jobs.runner import EphemeralGone, NotReady
from backend.core import ENGINE_NAME, NAUTILUS_VERSION

# ─── Routers dành cho COIN ────────────────────────────────────────────────────
from backend.routes import studio, data, live
from backend.routes.system import engine_router, home_router, users_router, overview_router

app = FastAPI(title="Nora COIN API", version="3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://coin.nora.expsolution.io",
        "http://localhost:18010",
        "http://localhost:18011",
        "http://127.0.0.1:18010",
        "http://127.0.0.1:18011",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

# COIN routers: system + studio + live + data (không có edu_router)
_coin_routers = (
    [engine_router, home_router, users_router, overview_router]
    + studio.ROUTERS
    + live.ROUTERS
    + data.ROUTERS
)
for r in _coin_routers:
    app.include_router(r)


@app.exception_handler(EphemeralGone)
def _ephemeral_gone(_request, exc: EphemeralGone):
    return JSONResponse(status_code=410, content={"detail": {"code": exc.code, "message": str(exc), "job_id": exc.job_id}})


@app.exception_handler(NotReady)
def _not_ready(_request, exc: NotReady):
    return JSONResponse(status_code=501, content={"detail": {"code": exc.code, "message": str(exc)}})


@app.on_event("startup")
def _enforce_job_lifecycle():
    """Job lifecycle thread — bao gồm cả live bot supervision."""
    import threading
    from backend.jobs import runner as batch_jobs
    threading.Thread(target=batch_jobs.enforce_lifecycle, name="coin-job-lifecycle", daemon=True).start()


@app.get("/api/health")
def health():
    return {"ok": True, "product": "coin", "engine": {"name": ENGINE_NAME, "version": NAUTILUS_VERSION}}


# ─── WebSocket / Charts pass-through ─────────────────────────────────────────
# Các route /ws/* và /charts/* được phục vụ bởi live router và studio router bên trong.
# Nginx proxy /ws và /charts đến COIN API (port 18010), không cần mount thêm ở đây.

# ─── COIN Frontend (dist-coin) ────────────────────────────────────────────────
WEB = Path(__file__).resolve().parents[2] / "frontend" / "dist-coin"
# Fallback về dist (bản build monolith cũ) nếu dist-coin chưa được build
if not WEB.exists():
    WEB = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if WEB.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")

    def _index():
        target = WEB / "index.html"
        if not target.exists():
            target = WEB / "index.coin.html"
        return FileResponse(target, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

    @app.get("/")
    def index():
        return _index()

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, detail="API endpoint not found")
        f = WEB / path
        return FileResponse(f) if f.is_file() else _index()
