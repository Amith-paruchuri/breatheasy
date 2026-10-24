"""Production web plumbing: logging, request IDs, security headers, CSRF guard,
client IP, rate limiting and serving the built frontend."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .config import Settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


# ---------- logging ----------
class JsonFormatter(logging.Formatter):
    """One JSON object per line; Cloud Logging reads `severity` and `message`."""

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id_var.get(),
        }
        for k in ("method", "path", "status", "latency_ms"):
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging(s: Settings) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if s.is_production else logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(h)
    root.setLevel(s.log_level.upper())
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log (no query strings)
    # httpx logs every upstream URL at INFO, query string included (search text,
    # coordinates). Keep those out of the logs, as the privacy policy promises.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


access_log = logging.getLogger("breatheasy.access")


# ---------- client IP ----------
def client_ip(request: Request) -> str:
    # Cloud Run's front end and our nginx both APPEND the real client address, so the
    # right-most X-Forwarded-For entry is the trustworthy one; earlier entries are
    # whatever the client sent.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Per-instance sliding window. Cloud Run runs several instances, so the real
    ceiling is limit x instances: keep Google quotas as the hard cap."""

    def __init__(self, per_minute: int):
        self.limit = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self.hits) > 50_000:
            self.hits.clear()
        return True


# ---------- security headers ----------
def content_security_policy() -> str:
    # Allowlist from Google's CSP guidance for Maps JS + Google Identity Services,
    # plus OpenStreetMap/CARTO tiles for the open-data map and Google Fonts.
    g = "https://*.googleapis.com https://*.gstatic.com *.google.com https://*.ggpht.com *.googleusercontent.com"
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src 'self' 'unsafe-eval' blob: {g} https://accounts.google.com/gsi/client",
            f"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com/gsi/style",
            f"img-src 'self' data: blob: {g} https://*.basemaps.cartocdn.com https://*.tile.openstreetmap.org",
            "font-src 'self' https://fonts.gstatic.com data:",
            f"connect-src 'self' data: blob: {g} https://accounts.google.com/gsi/",
            "frame-src *.google.com https://accounts.google.com/gsi/",
            "worker-src 'self' blob:",
            "manifest-src 'self'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
        ]
    )


class WebMiddleware(BaseHTTPMiddleware):
    """Request ID, access log, CSRF guard and security headers in one pass."""

    STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.s = settings
        self.csp = content_security_policy()

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-cloud-trace-context", "").split("/")[0] or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            path = request.url.path
            # CSRF: browsers only let same-origin scripts (or CORS-approved ones) add a
            # custom header, so requiring it blocks cross-site form/navigation posts.
            if (
                request.method in self.STATE_CHANGING
                and path.startswith("/api/")
                and request.headers.get("x-requested-with") != "breatheasy"
            ):
                response: Response = JSONResponse({"detail": "Missing X-Requested-With header."}, status_code=403)
            else:
                response = await call_next(request)
        except Exception:
            logging.getLogger("breatheasy").exception("unhandled error")
            response = JSONResponse({"detail": "Something went wrong on our side. Please try again."}, status_code=500)

        h = response.headers
        h["X-Request-ID"] = rid
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=(), payment=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"  # Google sign-in popup
        if self.s.is_production:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if self.s.csp_mode == "enforce":
            h["Content-Security-Policy"] = self.csp
        elif self.s.csp_mode == "report-only":
            h["Content-Security-Policy-Report-Only"] = self.csp
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")

        if not request.url.path.startswith(("/healthz", "/assets/")):
            access_log.info(
                "%s %s %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "method": request.method,
                    "path": request.url.path,  # never the query string: it can hold places
                    "status": response.status_code,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
        request_id_var.reset(token)
        return response


# ---------- frontend ----------
def mount_frontend(app: FastAPI, static_dir: str) -> bool:
    root = Path(static_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    no_cache = {"Cache-Control": "no-cache"}
    immutable = {"Cache-Control": "public, max-age=31536000, immutable"}

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_file() and root in candidate.parents:
                headers = immutable if full_path.startswith("assets/") else no_cache
                return FileResponse(candidate, headers=headers)
            if full_path.startswith("assets/") or "." in full_path.rsplit("/", 1)[-1]:
                return JSONResponse({"detail": "Not found."}, status_code=404)
        return FileResponse(index, headers=no_cache)  # client-side routes

    return True
