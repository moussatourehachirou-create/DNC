from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.db import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Démarrage rapide en développement ; en production, les migrations Alembic font foi.
    Base.metadata.create_all(engine())
    yield


app = FastAPI(
    title="Budget Intelligence Engine",
    description="Planification budgétaire, PPM et suivi de la performance — Bénin",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
