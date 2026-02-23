"""Page-serving routes — HTML template responses for each page."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.dependencies import templates

router = APIRouter()

# Nav links - single source of truth for all pages
NAV_LINKS = [
    {"href": "/positions", "label": "Positions"},
    {"href": "/ledger", "label": "Ledger"},
    {"href": "/reports", "label": "Reports"},
    {"href": "/risk", "label": "Risk"},
]


def _nav_context(request: Request, active_path: str, variant: str = "standard") -> dict:
    """Build template context with nav bar variables"""
    return {
        "request": request,
        "nav_links": NAV_LINKS,
        "active_path": active_path,
        "nav_variant": variant,
    }


@router.get("/", response_class=HTMLResponse)
@router.get("/positions", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main application - Open Positions Page"""
    return templates.TemplateResponse("positions.html", _nav_context(request, "/positions"))


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Serve the Performance Reports page"""
    return templates.TemplateResponse("reports.html", _nav_context(request, "/reports"))


@router.get("/risk", response_class=HTMLResponse)
async def risk_dashboard(request: Request):
    """Serve the Portfolio Risk X-Ray page"""
    return templates.TemplateResponse("risk-dashboard.html", _nav_context(request, "/risk"))


@router.get("/ledger", response_class=HTMLResponse)
async def ledger_page(request: Request):
    """Serve the Position Ledger page"""
    return templates.TemplateResponse("ledger.html", _nav_context(request, "/ledger"))


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Serve the Settings page"""
    return templates.TemplateResponse("settings.html", _nav_context(request, "/settings", "settings"))
