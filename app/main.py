"""ParcelDesk application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import admin, auth, clients, labels, parcels, portal, public, receiving
from .config import settings
from .database import Base, SessionLocal, engine
from .migrations import sync_schema
from .models import Parcel, User

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("parceldesk")

STATIC_DIR = Path(__file__).parent / "static"


def _security_preflight() -> None:
    """Warn loudly about weak/default settings so nothing ships insecure by accident."""
    if settings.secret_key in ("change-me-in-production", "change-me-to-a-long-random-string") \
            or len(settings.secret_key) < 32:
        log.warning("SECRET_KEY is short or still the default — set a long random value in .env "
                    "before exposing this server (python -c \"import secrets;"
                    "print(secrets.token_urlsafe(48))\")")
    if settings.first_admin_password in ("admin123", "changeme", "password"):
        log.warning("The first admin account still uses the default password — change it in "
                    "Settings → Users right after logging in.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    sync_schema(engine)          # add new columns to existing installs
    _security_preflight()

    db = SessionLocal()
    try:
        from .services import runtime
        runtime.load_overrides(db)

        from .seed import ensure_admin, seed_demo_data
        ensure_admin(db)
        if settings.demo_mode and not db.query(Parcel.id).first():
            log.info("DEMO_MODE on — seeding sample parcels")
            seed_demo_data(db)

        if settings.sync_on_startup and db.query(Parcel.id).first():
            from .services import tracking
            tracking.sync_all(db, trigger="startup", limit=100)
    finally:
        db.close()

    from .scheduler import start_scheduler, shutdown_scheduler
    start_scheduler()
    log.info("%s ready — open %s", settings.app_name, settings.public_base_url)
    try:
        yield
    finally:
        shutdown_scheduler()
        log.info("%s shutting down", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan,
                  description="Self-hosted multi-carrier parcel tracking (DHL / FedEx / Aramex)")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (auth.router, auth.users_router, parcels.router, clients.router,
                   receiving.router, labels.router, portal.router, portal.admin_router,
                   admin.router, public.router):
        app.include_router(module)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": settings.app_name, "demo_mode": settings.demo_mode}

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        # serve the SPA shell for non-API 404s so client-side routes still work
        if exc.status_code == 404 and (STATIC_DIR / "index.html").exists():
            return FileResponse(STATIC_DIR / "index.html")
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def root():
            return FileResponse(STATIC_DIR / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = STATIC_DIR / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
