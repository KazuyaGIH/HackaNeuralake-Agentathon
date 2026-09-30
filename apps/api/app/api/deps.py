from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.storage.db import Database

LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
LOCAL_OWNER = "local"


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database = request.app.state.db
    async with db.session() as s:
        yield s


def current_owner(request: Request, settings: Annotated[Settings, Depends(get_settings_dep)]) -> str:
    """Local: workspace unico, apenas loopback. Token: Bearer obrigatorio (nunca em query string)."""
    if settings.auth_mode == "local":
        host = request.client.host if request.client else "127.0.0.1"
        if host not in LOOPBACK:
            raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "loopback_only", "message": "modo local aceita apenas conexoes de loopback; configure AGENTATHON_AUTH_MODE=token para exposicao em rede"})
        return LOCAL_OWNER
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": "unauthorized", "message": "token Bearer obrigatorio"}, headers={"WWW-Authenticate": "Bearer"})
    owner = settings.token_map().get(token.strip())
    if owner is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": "unauthorized", "message": "token invalido"}, headers={"WWW-Authenticate": "Bearer"})
    return owner


Owner = Annotated[str, Depends(current_owner)]
Session = Annotated[AsyncSession, Depends(get_session)]
