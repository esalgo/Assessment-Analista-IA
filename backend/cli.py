"""CLI del pipeline de leads. Cada etapa es un subcomando y corre sola."""

import typer

from backend.db.migrar import aplicar_migraciones
from backend.stages.ingest import ErrorDeFormato, ingestar

app = typer.Typer(help="Pipeline de priorización de leads.", no_args_is_help=True)


def _pendiente(etapa: str) -> None:
    typer.echo(f"[{etapa}] etapa aún no implementada", err=True)
    raise typer.Exit(code=1)


@app.command()
def migrate() -> None:
    """Aplica las migraciones SQL de db/migrations/."""
    aplicadas = aplicar_migraciones()
    if not aplicadas:
        typer.echo("[migrate] esquema al día, nada que aplicar")
    for nombre in aplicadas:
        typer.echo(f"[migrate] aplicada {nombre}")


@app.command()
def ingest() -> None:
    """Carga los archivos fuente sin limpiar a las tablas raw_*."""
    try:
        resultados = ingestar()
    except ErrorDeFormato as error:
        typer.echo(f"[ingest] ERROR: {error}", err=True)
        raise typer.Exit(code=1)
    for r in resultados:
        estado = "cargado" if r.cargado else "sin cambios, no se recarga"
        typer.echo(f"[ingest] {r.archivo:<22} -> {r.tabla:<19} {r.filas:>5} filas  ({estado})")


@app.command()
def normalize() -> None:
    """Normaliza fechas, teléfonos, ciudad, canal, estado y nombres."""
    _pendiente("normalize")


@app.command("resolve-models")
def resolve_models() -> None:
    """Resuelve modelo_interes_texto a un SKU del catálogo."""
    _pendiente("resolve-models")


@app.command()
def dedupe() -> None:
    """Deduplica clientes por (empresa_id, telefono_normalizado)."""
    _pendiente("dedupe")


@app.command("extract-ai")
def extract_ai() -> None:
    """Extrae señales de las conversaciones con el LLM, con caché."""
    _pendiente("extract-ai")


@app.command()
def score() -> None:
    """Calcula el score de cada lead con los pesos del histórico."""
    _pendiente("score")


@app.command()
def assign() -> None:
    """Reparte los leads del día entre asesores según capacidad."""
    _pendiente("assign")


@app.command("run-all")
def run_all() -> None:
    """Ejecuta todas las etapas en orden."""
    ingest()
    normalize()
    resolve_models()
    dedupe()
    extract_ai()
    score()
    assign()


if __name__ == "__main__":
    app()