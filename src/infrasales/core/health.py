"""Probes for orchestrators: liveness checks the process, readiness the database."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import SQLAlchemyError

from infrasales.core import schema
from infrasales.core.db import Database, database

router = APIRouter(include_in_schema=False)  # probes are not part of the API contract
_READINESS_TIMEOUT_SECONDS = 3


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Alive: the process serves requests. A database outage must not restart it."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(db: Annotated[Database, Depends(database)], response: Response) -> dict[str, str]:
    """Ready: the database is reachable, and its schema one this build can use."""
    try:
        async with asyncio.timeout(_READINESS_TIMEOUT_SECONDS):
            ready = await schema.suits_build(db)
    except OSError, SQLAlchemyError, TimeoutError:
        ready = False
    response.status_code = 200 if ready else 503
    return {"status": "ready" if ready else "unavailable"}
