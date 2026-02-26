"""
Admin auth middleware: validates X-Admin-Secret header on API routes.

Exempt paths:
  - /static/*  (CSS/JS assets)
  - /           (page HTML — auth is client-side via sessionStorage)
  - /dashboard  (alias)
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from admin.dependencies import ADMIN_SECRET

logger = logging.getLogger(__name__)


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Exempt: static assets and page routes (auth handled client-side)
        if path.startswith("/static") or path in ("/", "/dashboard"):
            return await call_next(request)

        # All /api/admin/* routes require the secret
        if path.startswith("/api/admin"):
            if not ADMIN_SECRET:
                return JSONResponse(
                    {"error": "ADMIN_SECRET not configured on server"},
                    status_code=500,
                )
            provided = request.headers.get("X-Admin-Secret", "")
            if provided != ADMIN_SECRET:
                return JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                )

        return await call_next(request)
