from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.models  # noqa: F401 — registers models on Base
from app.db_init import run_migrations
from app.routers import pages


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic owns the schema; bring the DB to head on startup (needs Postgres up).
    run_migrations()
    yield


app = FastAPI(title="Care Platform", lifespan=lifespan)
app.include_router(pages.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
