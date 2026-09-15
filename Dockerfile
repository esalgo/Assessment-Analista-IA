FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Bogota

WORKDIR /app

# requirements.txt primero: si no cambia, Docker reutiliza esta capa
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY db/ ./db/
COPY config/ ./config/
COPY prompts/ ./prompts/

EXPOSE 8000

# `fastapi run` es el modo producción. `fastapi dev` solo en local:
# escucha en 127.0.0.1 y dentro de un contenedor eso no responde a nadie.
CMD ["fastapi", "run", "backend/api/main.py", "--host", "0.0.0.0", "--port", "8000"]
