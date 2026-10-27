"""Nora EDU API — Entrypoint độc lập của dự án nora/edu.

Chạy:
    cd /home/vmc03/norabt/nora/edu
    uvicorn backend.main:app --host 127.0.0.1 --port 18020
"""
import os
import sys
from pathlib import Path

# Đảm bảo import trong edu/backend được ưu tiên cao nhất
EDU_ROOT = Path(__file__).resolve().parent.parent
if str(EDU_ROOT) not in sys.path:
    sys.path.insert(0, str(EDU_ROOT))

# Namespace dữ liệu độc lập của EDU
os.environ.setdefault("NORA_DATA_ROOT", str(EDU_ROOT / "data"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager
from backend.core import ENGINE_NAME, NAUTILUS_VERSION
from backend.routes.system import engine_router, home_router, users_router, edu_router, warm_market_cache
from backend.routes import studio


@asynccontextmanager
async def lifespan(app: FastAPI):
    warm_market_cache()
    yield


app = FastAPI(title="Nora EDU API", version="3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nora.edu.expsolution.io",
        "https://edu.nora.expsolution.io",
        "http://localhost:18020",
        "http://localhost:18021",
        "http://127.0.0.1:18020",
        "http://127.0.0.1:18021",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

# EDU routers: chỉ gồm system utilities, users/auth, edu content và studio read/validate allow-list
for r in [engine_router, home_router, users_router, edu_router] + studio.EDU_STUDIO_ROUTERS:
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True, "product": "edu", "engine": {"name": ENGINE_NAME, "version": NAUTILUS_VERSION}}


# ─── EDU Frontend ────────────────────────────────────────────────────────────
WEB = EDU_ROOT / "frontend" / "dist"

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
