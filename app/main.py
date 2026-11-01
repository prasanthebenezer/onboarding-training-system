from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import Base, engine
from .routes import admin, trainee


def create_app() -> FastAPI:
    Base.metadata.create_all(engine)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Onboarding & Training System", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="trn_session",
                       max_age=60 * 60 * 12, same_site="lax",
                       https_only=settings.base_url.startswith("https"))
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(trainee.router)
    app.include_router(admin.router)

    @app.get("/")
    def root():
        return RedirectResponse("/admin")

    @app.get("/healthz")
    def health():
        return {"ok": True}

    return app


app = create_app()
