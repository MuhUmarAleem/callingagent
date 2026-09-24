"""
Application entry point.

Assembles the FastAPI app, registers routers, and installs global
exception handlers that always return the standard error envelope.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import configure_logging, get_settings
from app.routers import patients, vapi

# Configure logging before anything else
configure_logging(get_settings())
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db import init_schema
    init_schema()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Patient Registration API",
        description="Backend for a Vapi voice-agent patient registration system.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ----- Exception handlers -----

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Convert FastAPI/Pydantic request validation errors to envelope format."""
        fields = {}
        for error in exc.errors():
            loc = error.get("loc", [])
            field = ".".join(str(l) for l in loc if l not in ("body", "query", "path"))
            fields[field or "input"] = error.get("msg", "Invalid value")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "data": None,
                "error": {
                    "code": "validation_error",
                    "message": "One or more fields are invalid.",
                    "fields": fields,
                },
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        """Catch-all handler: log the full error, return a safe generic message."""
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred. Please try again.",
                    "fields": {},
                },
            },
        )

    # ----- Routers -----
    app.include_router(patients.router)
    app.include_router(vapi.router)

    # ----- Static files (dashboard) -----
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        @app.get("/", include_in_schema=False)
        def dashboard():
            return FileResponse(static_dir / "dashboard.html")

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
