"""Configuración leída de variables de entorno (y del .env en local)."""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent.parent
MIGRACIONES_DIR = RAIZ / "db" / "migrations"


def fecha_referencia_configurada() -> date | None:
    """FECHA_REFERENCIA (yyyy-mm-dd) si está definida. Si no, cada etapa usa
    la máxima fecha inequívoca del dataset. Nunca la fecha del sistema."""
    valor = os.getenv("FECHA_REFERENCIA")
    return date.fromisoformat(valor) if valor else None


def dias_absorber_represamiento() -> int:
    """En cuántos días debe vaciarse la cola de primer contacto con la
    capacidad diaria. De aquí sale el reparto entre las dos colas."""
    return int(os.getenv("DIAS_ABSORBER_REPRESAMIENTO", "2"))


def jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def pipeline_token() -> str:
    """Token que n8n manda en X-Pipeline-Token para disparar el pipeline."""
    return os.environ["PIPELINE_TOKEN"]


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
