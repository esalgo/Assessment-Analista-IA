"""API HTTP.

Caddy publica la API bajo /api y le quita ese prefijo antes de pasarla
(handle_path). Por eso las rutas aquí no llevan /api, y root_path="/api" hace
que /docs genere las URLs correctas. n8n llama directo a api:8000, sin prefijo.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.db import abrir_pool, cerrar_pool
from backend.api.rutas import router


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    abrir_pool()
    yield
    cerrar_pool()


app = FastAPI(title="Leads API", root_path="/api", lifespan=ciclo_de_vida)
app.include_router(router)
