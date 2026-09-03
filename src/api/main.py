"""FastAPI REST application for the AI Finance Controller with CORS and UI console mounting."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.api.routes_copilot import router as copilot_router
from src.api.routes_forecast import router as forecast_router
from src.api.routes_reconcile import router as reconcile_router
from src.api.routes_reports import router as reports_router
from src.api.routes_workbench import router as workbench_router

app = FastAPI(
    title="AI Finance Controller API",
    description="Automated Reconciliation, Operational Remediation Workbench, and Forward Cash Forecasting Engine",
    version="1.0.0",
)

# Enable CORS for local dev and embedded web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(reconcile_router)
app.include_router(workbench_router)
app.include_router(forecast_router)
app.include_router(copilot_router)
app.include_router(reports_router)

UI_INDEX_PATH = Path(__file__).resolve().parent.parent / "ui" / "index.html"


@app.get("/", include_in_schema=False)
def serve_dashboard():
    """Serve the responsive Fintech Operations Dashboard UI."""
    if UI_INDEX_PATH.exists():
        return FileResponse(UI_INDEX_PATH)
    return {"message": "AI Finance Controller API is running. UI index.html not found."}


@app.get("/health")
def health_check():
    """System health check endpoint."""
    return {"status": "healthy", "service": "ai-finance-controller", "version": "1.0.0"}
