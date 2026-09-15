"""CLI del pipeline de leads. Cada etapa es un subcomando y corre sola."""

import typer

from backend.db.migrar import aplicar_migraciones
from backend.stages.dedupe import deduplicar
from backend.stages.ingest import ErrorDeFormato, ingestar
from backend.stages.load_reference import ErrorDeReferencia, cargar_referencia
from backend.stages.normalize import ErrorDeCatalogo, normalizar
from backend.stages.resolve_models import resolver_modelos

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


@app.command("load-reference")
def load_reference() -> None:
    """Carga empresas, puntos de venta, catálogo, asesores e histórico desde raw_*."""
    try:
        conteos = cargar_referencia()
    except ErrorDeReferencia as error:
        typer.echo(f"[load-reference] ERROR: {error}", err=True)
        raise typer.Exit(code=1)
    for tabla, filas in conteos.items():
        typer.echo(f"[load-reference] {tabla:<20} {filas:>5}")


@app.command()
def normalize() -> None:
    """Normaliza fechas, teléfonos, ciudad, canal, estado y nombres."""
    try:
        resultado = normalizar()
    except ErrorDeCatalogo as error:
        typer.echo(f"[normalize] ERROR: {error}", err=True)
        raise typer.Exit(code=1)
    assert resultado.ventana is not None
    typer.echo(f"[normalize] ventana de fechas {resultado.ventana[0]} a {resultado.ventana[1]}")
    typer.echo(f"[normalize] fecha_referencia {resultado.fecha_referencia}")
    for nombre, cantidad in sorted(resultado.conteos.items()):
        typer.echo(f"[normalize] {nombre:<40} {cantidad:>5}")


@app.command("resolve-models")
def resolve_models() -> None:
    """Resuelve modelo_interes_texto a un SKU del catálogo."""
    for metodo, cantidad in resolver_modelos().most_common():
        typer.echo(f"[resolve-models] {metodo:<15} {cantidad:>5}")


@app.command()
def dedupe() -> None:
    """Deduplica clientes por (empresa_id, telefono_normalizado)."""
    for nombre, cantidad in sorted(deduplicar().items()):
        typer.echo(f"[dedupe] {nombre:<45} {cantidad:>5}")


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
    load_reference()
    normalize()
    resolve_models()
    dedupe()
    extract_ai()
    score()
    assign()


if __name__ == "__main__":
    app()