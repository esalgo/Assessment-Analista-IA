"""Cliente del LLM: una llamada por lead, con structured outputs y reintentos."""

import asyncio
import json
import os
import random

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError

from backend.config import RAIZ
from backend.llm.schemas import SCHEMA_EXTRACCION

PROMPTS_DIR = RAIZ / "prompts"
MAX_INTENTOS = 5
# Errores transitorios: vale la pena reintentar. Un 400 (esquema o request
# mal formado) no está aquí porque reintentarlo daría el mismo error.
REINTENTABLES = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)


class ErrorDeExtraccion(Exception):
    pass


def cargar_prompt(prompt_version: str) -> str:
    return (PROMPTS_DIR / f"{prompt_version}.md").read_text(encoding="utf-8")


def crear_cliente() -> AsyncOpenAI:
    """base_url configurable para apuntar a otro proveedor compatible.
    max_retries=0: los reintentos los maneja `extraer`, así hay una sola
    política de backoff y no dos superpuestas."""
    return AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        max_retries=0,
        timeout=60,
    )


async def extraer(
    cliente: AsyncOpenAI,
    semaforo: asyncio.Semaphore,
    modelo: str,
    prompt: str,
    texto_conversacion: str,
) -> dict:
    """Devuelve el JSON de la extracción, ya validado por la API contra el esquema."""
    async with semaforo:
        for intento in range(1, MAX_INTENTOS + 1):
            try:
                respuesta = await cliente.chat.completions.create(
                    model=modelo,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": texto_conversacion},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "extraccion_lead", "strict": True, "schema": SCHEMA_EXTRACCION},
                    },
                )
                break
            except REINTENTABLES:
                if intento == MAX_INTENTOS:
                    raise
                # 2, 4, 8, 16 s más un poco de azar para que las 8 tareas no reintenten a la vez.
                await asyncio.sleep(2**intento + random.random())

    eleccion = respuesta.choices[0]
    if eleccion.message.refusal:
        raise ErrorDeExtraccion(f"el modelo se negó: {eleccion.message.refusal}")
    if eleccion.finish_reason != "stop":
        raise ErrorDeExtraccion(f"respuesta incompleta: finish_reason={eleccion.finish_reason}")
    return json.loads(eleccion.message.content)
