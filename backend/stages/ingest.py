"""Etapa ingest: carga los archivos fuente a las tablas raw_* sin limpiar nada.

Idempotencia por archivo: se calcula el sha256 de sus bytes. Si coincide
con el del último lote cargado, no se toca. Si cambió, en una sola
transacción se registra un lote nuevo, se vacía la tabla raw y se cargan
todas las filas. O queda la versión nueva completa, o la anterior intacta.

Los valores se guardan como texto exacto del archivo: espacios sobrantes,
mayúsculas, campos vacíos ('') y filas duplicadas incluidos.
"""

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

from backend.config import data_input_dir
from backend.db.conexion import conectar

# archivo -> (tabla raw, columnas esperadas en el encabezado, en orden)
ARCHIVOS_CSV: dict[str, tuple[str, list[str]]] = {
    "leads.csv": ("raw_leads", [
        "lead_id", "fecha_registro", "canal", "empresa_id", "punto_venta_id",
        "nombre_cliente", "telefono", "email", "ciudad", "modelo_interes_texto",
        "estado_gestion", "fecha_primer_contacto", "campania",
    ]),
    "catalogo_motos.csv": ("raw_catalogo", [
        "sku", "marca", "linea", "cilindraje", "segmento", "precio_lista",
        "puntos_venta_disponibles", "unidades_disponibles",
    ]),
    "asesores.csv": ("raw_asesores", [
        "asesor_id", "nombre", "punto_venta_id", "empresa_id",
        "capacidad_diaria_leads", "activo", "fecha_ingreso",
    ]),
    "historico_cierres.csv": ("raw_historico", [
        "lead_id", "fecha_registro", "canal", "empresa_id", "punto_venta_id",
        "modelo_cotizado", "precio_lista", "horas_al_primer_contacto",
        "numero_contactos", "manifesto_cuota_inicial", "forma_pago_declarada",
        "pidio_cita", "desenlace",
    ]),
}

ARCHIVO_CONVERSACIONES = "conversaciones.json"
TABLA_CONVERSACIONES = "raw_conversaciones"


class ErrorDeFormato(Exception):
    """El archivo no tiene la forma esperada. Se aborta: cargar un archivo
    con columnas corridas contaminaría todo lo que viene después."""


@dataclass
class ResultadoArchivo:
    archivo: str
    tabla: str
    filas: int
    cargado: bool  # False = sin cambios desde el último lote


def sha256_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def leer_csv(ruta: Path, columnas: list[str]) -> list[list[str]]:
    # newline="" deja que el módulo csv maneje el CRLF sin alterar los valores
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.reader(f)
        encabezado = next(lector)
        if encabezado != columnas:
            raise ErrorDeFormato(f"{ruta.name}: encabezado inesperado {encabezado}")
        filas = []
        for fila in lector:
            if len(fila) != len(columnas):
                raise ErrorDeFormato(
                    f"{ruta.name}, línea {lector.line_num}: "
                    f"{len(fila)} campos, se esperaban {len(columnas)}"
                )
            filas.append(fila)
    return filas


def leer_conversaciones(ruta: Path) -> list[str]:
    """Devuelve cada conversación como texto JSON, lista para la columna jsonb."""
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, list):
        raise ErrorDeFormato(f"{ruta.name}: se esperaba una lista de conversaciones")
    return [json.dumps(conversacion, ensure_ascii=False) for conversacion in datos]


def ultimo_hash(conn: psycopg.Connection, archivo: str) -> str | None:
    fila = conn.execute(
        "SELECT source_hash FROM ingest_lotes WHERE archivo = %s ORDER BY lote_id DESC LIMIT 1",
        (archivo,),
    ).fetchone()
    return fila[0] if fila else None


def recargar_tabla(
    conn: psycopg.Connection,
    archivo: str,
    source_hash: str,
    tabla: str,
    columnas: list[str],
    filas: list[list[str]],
) -> None:
    """Reemplaza el contenido de la tabla raw por las filas dadas.

    `tabla` y `columnas` salen de las constantes de este módulo, nunca de
    datos externos, por eso se interpolan directamente en el SQL.
    """
    with conn.transaction():
        fila = conn.execute(
            "INSERT INTO ingest_lotes (archivo, source_hash, filas) VALUES (%s, %s, %s) RETURNING lote_id",
            (archivo, source_hash, len(filas)),
        ).fetchone()
        assert fila is not None
        lote_id = fila[0]

        conn.execute(f"DELETE FROM {tabla}")

        lista_columnas = ", ".join(["lote_id", "fila_num", *columnas])
        with conn.cursor().copy(f"COPY {tabla} ({lista_columnas}) FROM STDIN") as copia:
            for fila_num, valores in enumerate(filas, start=1):
                copia.write_row([lote_id, fila_num, *valores])


def ingestar(directorio: Path | None = None) -> list[ResultadoArchivo]:
    directorio = directorio or data_input_dir()
    resultados: list[ResultadoArchivo] = []

    with conectar() as conn:
        for archivo, (tabla, columnas) in ARCHIVOS_CSV.items():
            ruta = directorio / archivo
            source_hash = sha256_archivo(ruta)
            filas = leer_csv(ruta, columnas)
            cargado = source_hash != ultimo_hash(conn, archivo)
            if cargado:
                recargar_tabla(conn, archivo, source_hash, tabla, columnas, filas)
            resultados.append(ResultadoArchivo(archivo, tabla, len(filas), cargado))

        ruta = directorio / ARCHIVO_CONVERSACIONES
        source_hash = sha256_archivo(ruta)
        conversaciones = leer_conversaciones(ruta)
        cargado = source_hash != ultimo_hash(conn, ARCHIVO_CONVERSACIONES)
        if cargado:
            recargar_tabla(
                conn, ARCHIVO_CONVERSACIONES, source_hash, TABLA_CONVERSACIONES,
                ["payload"], [[texto] for texto in conversaciones],
            )
        resultados.append(
            ResultadoArchivo(ARCHIVO_CONVERSACIONES, TABLA_CONVERSACIONES, len(conversaciones), cargado)
        )

    return resultados
