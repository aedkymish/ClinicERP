"""ClinicERP v2 API — FastAPI application."""
import asyncio
import contextlib
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routers import (admin, appointments, attendance, audit_log, auth, expenses, inventory, invoices, patients,
                      payroll, reports, services, staff, users, visits)

logging.basicConfig(level=logging.INFO)
API = "/api/v1"


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    task = None
    if s.scheduler_enabled and s.database_url.startswith("sqlite"):
        from .services.backup import nightly_loop

        task = asyncio.create_task(nightly_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="ClinicERP API",
    version="2.0.0",
    description="REST API for ClinicERP v2. Money values are integer minor units (e.g. cents).",
    docs_url=f"{API}/docs",
    redoc_url=None,
    openapi_url=f"{API}/openapi.json",
    lifespan=lifespan,
)

if get_settings().cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith(API) and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"  # patient data must not sit in browser caches
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query", "path")]
        fields[".".join(loc) or "_"] = err.get("msg", "Invalid value").removeprefix("Value error, ")
    first = next(iter(fields.items()), ("", "Invalid input"))
    return JSONResponse(status_code=422, content={"detail": {
        "message": f"{first[0]}: {first[1]}" if first[0] else first[1], "code": "validation", "fields": fields}})


for r in (auth.router, users.router, patients.router, appointments.router, visits.router, services.router,
          invoices.router, inventory.router, expenses.router, staff.router, attendance.router, payroll.router,
          reports.router, audit_log.router, admin.router):
    app.include_router(r, prefix=API)


@app.get(f"{API}/health", tags=["health"])
def health():
    return {"status": "ok"}
