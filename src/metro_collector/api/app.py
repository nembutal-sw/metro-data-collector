from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from metro_collector.api.routers import admin, system, transit
from metro_collector.config import get_settings
from metro_collector.db import Database
from metro_collector.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings.ensure_data_directories()
    database = Database(settings.database_url.get_secret_value())
    await database.open()
    application.state.database = database
    try:
        yield
    finally:
        await database.close()


app = FastAPI(
    title="Metro Data Collector API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(system.router)
app.include_router(transit.router)
app.include_router(transit.odsay_router)
app.include_router(admin.router)


def run() -> None:
    uvicorn.run(
        "metro_collector.api.app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )
