"""Configuración leída de variables de entorno (y del .env en local)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent.parent
MIGRACIONES_DIR = RAIZ / "db" / "migrations"


def data_input_dir() -> Path:
    """En Docker es /app/data/input (lo define el .env). En local, si no
    está definida, se usa data/input del repo."""
    return Path(os.getenv("DATA_INPUT_DIR", RAIZ / "data" / "input"))


def database_url() -> str:
    """En Docker el compose define DATABASE_URL. En local se arma desde
    las variables POSTGRES_* apuntando a localhost."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    usuario = os.environ["POSTGRES_USER"]
    clave = os.environ["POSTGRES_PASSWORD"]
    base = os.environ["POSTGRES_DB"]
    host = os.getenv("POSTGRES_HOST", "localhost")
    puerto = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{usuario}:{clave}@{host}:{puerto}/{base}"
