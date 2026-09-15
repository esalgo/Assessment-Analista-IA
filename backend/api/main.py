"""API HTTP. Por ahora solo expone el chequeo de salud."""

from fastapi import FastAPI

app = FastAPI(title="Leads API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}