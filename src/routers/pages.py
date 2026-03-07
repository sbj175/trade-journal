"""Page-serving routes — SPA catch-all + standalone pages."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from src.dependencies import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page (standalone Alpine.js, outside SPA)"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/beta-full", response_class=HTMLResponse)
async def beta_full_page(request: Request):
    """Serve the beta-full standalone page (outside SPA)"""
    return templates.TemplateResponse("beta-full.html", {"request": request})


@router.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_catch_all(request: Request, full_path: str):
    """Serve the SPA shell for all client-side routes."""
    # Block dotfiles and sensitive paths
    segments = full_path.strip("/").split("/")
    if any(seg.startswith(".") for seg in segments if seg):
        return PlainTextResponse("Not Found", status_code=404)
    return templates.TemplateResponse("index.html", {"request": request})
