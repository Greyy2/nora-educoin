"""Nora API: app FastAPI duy nhất (uvicorn backend.main:app).

Mọi việc (backtest, WFA, Monte Carlo, phễu alpha, danh mục) đi qua các router trong backend/api/routers;
UI, terminal (curl) và script đều gọi cùng các endpoint này. Bản build frontend (frontend/dist) được phục vụ ở "/".
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routers import book, chart, data, funnel, live, market, portfolio, strategies

app = FastAPI(title="Nora API", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(book.router)
app.include_router(book.alphas_router)
app.include_router(portfolio.router)
app.include_router(funnel.router)
app.include_router(strategies.router)
app.include_router(data.router)
app.include_router(market.router)
app.include_router(live.router)
app.include_router(chart.router)


@app.get("/api/health")
def health():
    return {"ok": True}


# ─── Giao diện (bản build Vite) ───────────────────────────────────────────────
WEB = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")

    def _index():
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache, must-revalidate"})

    @app.get("/")
    def index():
        return _index()

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, detail="API endpoint not found")
        f = WEB / path
        return FileResponse(f) if f.is_file() else _index()
