"""Nora COIN API — Entrypoint độc lập của dự án nora/coin.

Chạy:
    cd /home/vmc03/norabt/nora/coin
    uvicorn backend.main:app --host 127.0.0.1 --port 18010
"""
import os
import sys
from pathlib import Path

# Đảm bảo import trong coin/backend được ưu tiên cao nhất
COIN_ROOT = Path(__file__).resolve().parent.parent
if str(COIN_ROOT) not in sys.path:
    sys.path.insert(0, str(COIN_ROOT))

# Namespace dữ liệu độc lập của COIN
os.environ.setdefault("NORA_DATA_ROOT", str(COIN_ROOT / "data"))
os.environ.setdefault("NORA_MASTER_CAPITAL_PAPER", "10000.0")
os.environ.setdefault("NORA_MASTER_CAPITAL_TESTNET", "10000.0")
os.environ.setdefault("NORA_MASTER_CAPITAL_LIVE", "50000.0")


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.jobs.runner import EphemeralGone, NotReady
from backend.core import ENGINE_NAME, NAUTILUS_VERSION

# Routers COIN
from backend.routes import studio, data, live
from backend.routes.system import engine_router, home_router, users_router, overview_router

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Job lifecycle thread cho COIN (bao gồm cả live bot supervision)."""
    import threading
    from backend.jobs import runner as batch_jobs, live_supervisor
    threading.Thread(target=batch_jobs.enforce_lifecycle, name="coin-job-lifecycle", daemon=True).start()
    live_supervisor.start()
    yield


app = FastAPI(title="Nora COIN API", version="3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nora.coin.expsolution.io",
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


@app.get("/api/health")
def health():
    return {"ok": True, "product": "coin", "engine": {"name": ENGINE_NAME, "version": NAUTILUS_VERSION}}


# ─── COIN Frontend ────────────────────────────────────────────────────────────
WEB = COIN_ROOT / "frontend" / "dist"

if WEB.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")

    def _index():
        target = WEB / "index.html"
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
