"""Etapa ingest: carga fiel e idempotente a las tablas raw_*."""

import shutil
from pathlib import Path

import pytest

from backend.config import RAIZ
from backend.db.conexion import conectar
from backend.stages.ingest import ErrorDeFormato, ingestar

DATOS = RAIZ / "data" / "input"


def _contar(tabla: str) -> int:
    with conectar() as conn:
        fila = conn.execute(f"SELECT count(*) FROM {tabla}").fetchone()
    assert fila is not None
    return fila[0]


def test_carga_todas_las_filas_sin_limpiar(base_de_prueba: None) -> None:
    ingestar(DATOS)

    assert _contar("raw_leads") == 1503
    assert _contar("raw_conversaciones") == 677
    assert _contar("raw_catalogo") == 24
    assert _contar("raw_asesores") == 42
    assert _contar("raw_historico") == 2200

    with conectar() as conn:
        # Las copias byte a byte siguen ahí: se detectan en normalize, no aquí
        copias = conn.execute(
            "SELECT count(*) FROM raw_leads WHERE lead_id IN ('LD-00011', 'LD-00251')"
        ).fetchone()
        # Los espacios sobrantes no se tocan
        nombre = conn.execute(
            "SELECT nombre_cliente FROM raw_leads WHERE lead_id = 'LD-00001'"
        ).fetchone()
    assert copias == (4,)
    assert nombre == ("  Wilmar Castaño Rodríguez  ",)


def test_reejecutar_no_duplica_ni_recarga(base_de_prueba: None) -> None:
    ingestar(DATOS)
    resultados = ingestar(DATOS)

    assert all(not r.cargado for r in resultados)
    assert _contar("raw_leads") == 1503


def test_archivo_modificado_se_recarga_entero(base_de_prueba: None, tmp_path: Path) -> None:
    for archivo in DATOS.iterdir():
        shutil.copy(archivo, tmp_path)
    ingestar(tmp_path)

    leads = tmp_path / "leads.csv"
    lineas = leads.read_bytes().split(b"\r\n")
    leads.write_bytes(b"\r\n".join(lineas[:-2]))  # quita la última fila

    resultados = {r.archivo: r for r in ingestar(tmp_path)}

    assert resultados["leads.csv"].cargado
    assert not resultados["asesores.csv"].cargado
    assert _contar("raw_leads") == 1502

    ingestar(DATOS)  # deja la base como la esperan los demás tests


def test_encabezado_distinto_aborta_sin_tocar_la_tabla(base_de_prueba: None, tmp_path: Path) -> None:
    ingestar(DATOS)
    for archivo in DATOS.iterdir():
        shutil.copy(archivo, tmp_path)
    leads = tmp_path / "leads.csv"
    leads.write_bytes(leads.read_bytes().replace(b"telefono", b"celular", 1))

    with pytest.raises(ErrorDeFormato):
        ingestar(tmp_path)
    assert _contar("raw_leads") == 1503
