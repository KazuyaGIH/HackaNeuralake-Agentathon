import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import API_DIR, Settings


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
        self.engine: AsyncEngine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=False)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine.sync_engine, "connect")
            def _pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA busy_timeout=30000")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()

        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as s:
            yield s

    async def migrate(self) -> None:
        """Aplica migracoes Alembic ate head (executa em thread; Alembic usa engine sincrona)."""
        await asyncio.to_thread(run_migrations, self.url)

    async def dispose(self) -> None:
        await self.engine.dispose()


def sync_url(url: str) -> str:
    return url.replace("+aiosqlite", "")


def run_migrations(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_url(url))
    command.upgrade(cfg, "head")


def ensure_dirs(settings: Settings) -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
