"""EDU API — FastAPI app độc lập (uvicorn backend.apps.edu:app --port 18020).

Phạm vi:
- Auth/Users/Sessions (chia sẻ cơ sở dữ liệu người dùng với COIN nhưng cookie domain độc lập)
- Market Education: /api/edu/*
- Home Summary (phần edu): /api/home/summary
- Engine version: /api/studio/nautilus/*
- Backtest kết quả giáo dục: đọc qua studio (chỉ đọc, không launch bot)

EDU KHÔNG có quyền: live bot control, exchange credentials, COIN portfolio/ledger.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.jobs.runner import EphemeralGone, NotReady
from backend.core import ENGINE_NAME, NAUTILUS_VERSION

# ─── Routers dành cho EDU ─────────────────────────────────────────────────────
# engine_router: GET /api/studio/nautilus/*  (version, check_update)
# home_router:   GET /api/home/summary
# users_router:  GET/POST /api/users, /api/me (auth/session)
# edu_router:    GET /api/edu/* (market, users, strategies)
# studio ROUTERS (chỉ backtest/wfa/mc read — không live bot): /api/studio/* không có bot control
from backend.routes.system import engine_router, home_router, users_router, edu_router
from backend.routes import studio

app = FastAPI(title="Nora EDU API", version="3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
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


@app.exception_handler(EphemeralGone)
def _ephemeral_gone(_request, exc: EphemeralGone):
    return JSONResponse(status_code=410, content={"detail": {"code": exc.code, "message": str(exc), "job_id": exc.job_id}})


@app.exception_handler(NotReady)
def _not_ready(_request, exc: NotReady):
    return JSONResponse(status_code=501, content={"detail": {"code": exc.code, "message": str(exc)}})



@app.get("/api/health")
def health():
    return {"ok": True, "product": "edu", "engine": {"name": ENGINE_NAME, "version": NAUTILUS_VERSION}}


# ─── EDU Frontend (dist-edu) ──────────────────────────────────────────────────
WEB = Path(__file__).resolve().parents[2] / "frontend" / "dist-edu"
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")

    def _index():
        target = WEB / "index.html"
        if not target.exists():
            target = WEB / "index.edu.html"
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
