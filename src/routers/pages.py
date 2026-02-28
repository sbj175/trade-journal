"""Page-serving routes — HTML template responses for each page."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.dependencies import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@router.get("/positions", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main application - Open Positions Page (Vue 3 — no Jinja2 context needed)"""
    return templates.TemplateResponse("positions.html", {"request": request})


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Serve the Performance Reports page (Vue 3 — no Jinja2 context needed)"""
    return templates.TemplateResponse("reports.html", {"request": request})


@router.get("/risk", response_class=HTMLResponse)
async def risk_dashboard(request: Request):
    """Serve the Portfolio Risk X-Ray page (Vue 3 — no Jinja2 context needed)"""
    return templates.TemplateResponse("risk-dashboard.html", {"request": request})


@router.get("/ledger", response_class=HTMLResponse)
async def ledger_page(request: Request):
    """Serve the Position Ledger page (Vue 3 — no Jinja2 context needed)"""
    return templates.TemplateResponse("ledger.html", {"request": request})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Serve the Settings page (Vue 3 — no Jinja2 context needed)"""
    return templates.TemplateResponse("settings.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page (standalone, no nav bar)"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/beta-full", response_class=HTMLResponse)
async def beta_full_page(request: Request):
    """Serve the beta-full standalone page (no nav bar)"""
    return templates.TemplateResponse("beta-full.html", {"request": request})
