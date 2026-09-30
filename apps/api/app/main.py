import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import APP_VERSION
from app.api.routes import router
from app.budget.prices import load_price_table
from app.config import Settings, get_settings
from app.orchestration.executor import Executor
from app.providers.base import ProviderAdapter
from app.providers.catalog import Catalog
from app.storage.db import Database, ensure_dirs
from app.storage.repo import RunNotifier

log = logging.getLogger("agentathon")


def create_app(settings: Settings | None = None, *, adapters: dict[str, ProviderAdapter] | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_dirs(settings)
        db = Database(settings.db_url)
        await db.migrate()
        prices = load_price_table(settings.neuralake_prices_file)
        catalog = Catalog(settings, prices)
        notifier = RunNotifier()
        app.state.settings = settings
        app.state.db = db
        app.state.prices = prices
        app.state.catalog = catalog
        app.state.notifier = notifier
        executor = Executor(db, settings, catalog, prices, notifier, adapters=adapters)
        interrupted = await executor.mark_interrupted()
        if interrupted:
            log.warning("runs marcados como interrupted apos reinicio: %s", interrupted)
        app.state.executor = executor
        if settings.executor_enabled:
            executor.start()
        try:
            yield
        finally:
            await executor.stop()
            await db.dispose()

    app = FastAPI(
        title="Agentathon API",
        version=APP_VERSION,
        description="Hackathon entre equipes de agentes de IA: propostas concorrentes, critica limitada, verificacao objetiva, Judge e ranking rastreavel. "
                    "Modo simulado (mock) funciona sem chaves; modo real exige credencial configurada no backend.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    return app


app = create_app()
