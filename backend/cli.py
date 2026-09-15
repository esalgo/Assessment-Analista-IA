"""CLI del pipeline de leads. Cada etapa es un subcomando y corre sola."""

import json
from typing import Annotated

import typer

from backend.db.migrar import aplicar_migraciones
from backend.stages.assign import asignar
from backend.usuarios import sembrar_usuarios
from backend.stages.dedupe import deduplicar
from backend.stages.extract_ai import PROMPT_VERSION, extraer_conversaciones, medir_variabilidad
from backend.stages.ingest import ErrorDeFormato, ingestar
from backend.stages.load_reference import ErrorDeReferencia, cargar_referencia
from backend.stages.normalize import ErrorDeCatalogo, normalizar
from backend.stages.resolve_models import resolver_modelos
from backend.stages.score import calcular_scores, guardar_scores

app = typer.Typer(help="Pipeline de priorización de leads.", no_args_is_help=True)




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
def extract_ai(
    limite: Annotated[int | None, typer.Option(help="Máximo de leads a enviar al LLM (muestras).")] = None,
    lead_id: Annotated[list[str] | None, typer.Option(help="Solo este lead; se puede repetir.")] = None,
) -> None:
    """Extrae señales de las conversaciones con el LLM, con caché."""
    resultado = extraer_conversaciones(limite, lead_id)
    for nombre, cantidad in sorted(resultado.conteos.items()):
        typer.echo(f"[extract-ai] {nombre:<50} {cantidad:>5}")
    for lead, error in resultado.fallidas:
        typer.echo(f"[extract-ai] FALLIDA {lead}: {error}", err=True)


@app.command("medir-ruido")
def medir_ruido(
    lead_id: Annotated[list[str], typer.Option(help="Lead a repetir; se puede repetir la opción.")],
    repeticiones: Annotated[int, typer.Option(help="Llamadas idénticas por lead.")] = 3,
) -> None:
    """Repite la extracción sin caché ni guardado y reporta qué campos cambian."""
    salidas = medir_variabilidad(lead_id, repeticiones)
    campos = list(next(iter(salidas.values()))[0])
    variaron: dict[str, int] = {campo: 0 for campo in campos}
    for lead, corridas in sorted(salidas.items()):
        for campo in campos:
            valores = [json.dumps(c[campo], ensure_ascii=False) for c in corridas]
            if len(set(valores)) > 1:
                variaron[campo] += 1
                typer.echo(f"[medir-ruido] {lead} {campo}: {' / '.join(valores)}")
    typer.echo(f"[medir-ruido] {PROMPT_VERSION}, {len(salidas)} leads x {repeticiones} llamadas")
    for campo, cantidad in variaron.items():
        typer.echo(f"[medir-ruido] {campo:<28} varió en {cantidad:>2} de {len(salidas)} leads")


@app.command()
def score() -> None:
    """Puntúa cada cliente, lo ubica en su cola y le asigna temperatura según sus señales."""
    resultados, referencia = calcular_scores()
    guardar_scores(resultados)
    typer.echo(f"[score] fecha_referencia {referencia:%Y-%m-%d %H:%M}, {len(resultados)} clientes")
    for cola in ("primer_contacto", "seguimiento", "descartado"):
        en_cola = [r for r in resultados if r.cola == cola]
        temperaturas = {t: sum(r.temperatura == t for r in en_cola) for t in ("alta", "media", "baja")}
        typer.echo(
            f"[score] cola {cola:<16} clientes {len(en_cola):>4}  "
            f"alta {temperaturas['alta']:>4}  media {temperaturas['media']:>4}  baja {temperaturas['baja']:>4}"
        )


@app.command()
def assign() -> None:
    """Reparte la lista del día por asesor, con la capacidad de cada punto de venta."""
    resumenes, dias = asignar()
    typer.echo(f"[assign] días para absorber el represamiento: {dias}")
    typer.echo(
        "[assign] pv      asesores  capacidad  pendientes  seguimiento  objetivo_primer/seguim  "
        "asignados_primer/seguim  libres  días_cartera"
    )
    for r in resumenes:
        objetivo = f"{r.capacidad_por_cola['primer_contacto']}/{r.capacidad_por_cola['seguimiento']}"
        asignados = f"{r.asignados_por_cola['primer_contacto']}/{r.asignados_por_cola['seguimiento']}"
        typer.echo(
            f"[assign] {r.punto_venta_id}  {r.asesores_activos:>8}  {r.capacidad:>9}  {r.pendientes:>10}  {r.seguimiento:>11}  "
            f"{objetivo:>22}  {asignados:>23}  {r.plazas_libres:>6}  {r.dias_de_cartera:>12.1f}"
        )
    for r in resumenes:
        for alerta in r.alertas:
            typer.echo(f"[assign] ALERTA {r.punto_venta_id}: {alerta}")
    total = sum(sum(r.asignados_por_cola.values()) for r in resumenes)
    libres = sum(r.plazas_libres for r in resumenes)
    typer.echo(f"[assign] asignados hoy {total} de {sum(r.capacidad for r in resumenes)} de capacidad; {libres} plazas libres")


@app.command("seed-usuarios")
def seed_usuarios() -> None:
    """Crea o actualiza los usuarios de demo con las contraseñas del .env (nunca en un .sql)."""
    for rol, cantidad in sembrar_usuarios().items():
        typer.echo(f"[seed-usuarios] {rol:<8} {cantidad:>3}")


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