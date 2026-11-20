"""CloudReader API. Run with: uvicorn app.main:app --host 127.0.0.1 --port 8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import books, generation, narration, player
from .api import settings as settings_api
from .config import Settings, get_settings
from .context import AppContext
from .manuscript.importers import ManuscriptError
from .providers.base import TTSError
from .providers.registry import ProviderRegistry
from .services.export import IncompleteAudio
from .services.generation import Worker, recover_interrupted
from .services.library import ConflictError


def _setup_logging(s: Settings) -> None:
    root = logging.getLogger("cloudreader")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    h = RotatingFileHandler(s.logs_dir / "cloudreader.log", maxBytes=5_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(h)
    root.addHandler(logging.StreamHandler())


def create_app(settings: Settings | None = None, providers: ProviderRegistry | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = AppContext.create(s, providers)
        _setup_logging(s)
        recover_interrupted(ctx)
        app.state.ctx = ctx
        if s.start_worker:
            ctx.worker = Worker(ctx)
            ctx.worker.start()
        yield
        if ctx.worker:
            ctx.worker.stop()

    app = FastAPI(title=f"{s.app_name} API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins, allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["Content-Disposition", "X-Skipped-Chapters"])

    def err(status: int, message: str, code: str = "error", **extra):
        return JSONResponse({"detail": message, "code": code, **extra}, status_code=status)

    @app.exception_handler(ManuscriptError)
    async def _m(_: Request, e: ManuscriptError):
        return err(400, str(e), "manuscript_error")

    @app.exception_handler(KeyError)
    async def _k(_: Request, e: KeyError):
        return err(404, str(e.args[0]) if e.args else "Not found", "not_found")

    @app.exception_handler(ValueError)
    async def _v(_: Request, e: ValueError):
        return err(400, str(e), "invalid")

    @app.exception_handler(ConflictError)
    async def _c(_: Request, e: ConflictError):
        return err(409, str(e), "conflict")

    @app.exception_handler(IncompleteAudio)
    async def _i(_: Request, e: IncompleteAudio):
        return err(409, str(e), "incomplete_audio")

    @app.exception_handler(PermissionError)
    async def _p(_: Request, e: PermissionError):
        return err(400, str(e), "provider_unavailable")

    @app.exception_handler(TTSError)
    async def _t(_: Request, e: TTSError):
        logging.getLogger("cloudreader").warning("TTS error %s: %s", e.code, e.detail[:300])
        return err(502, e.message, e.code)

    @app.exception_handler(RuntimeError)
    async def _r(_: Request, e: RuntimeError):
        return err(500, str(e), "runtime")

    for r in (books.router, generation.router, narration.router, player.router, settings_api.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"ok": True, "app": s.app_name}

    return app


app = create_app()
