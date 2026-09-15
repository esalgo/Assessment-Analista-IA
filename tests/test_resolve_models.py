"""Etapa resolve-models: cascada de reglas y fuzzy solo para errores de tipeo."""

import pytest

from backend.config import RAIZ
from backend.db.conexion import conectar
from backend.stages.ingest import ingestar
from backend.stages.load_reference import cargar_referencia
from backend.stages.normalize import normalizar
from backend.stages.resolve_models import (
    Catalogo,
    Moto,
    normalizar_texto_modelo,
    resolver_modelo,
    resolver_modelos,
)

CATALOGO = Catalogo([
    Moto("SKU-001", "Honda", "CB 125F Twister"),
    Moto("SKU-002", "Honda", "XR 150L"),
    Moto("SKU-003", "Honda", "CB 190R"),
    Moto("SKU-004", "Honda", "Navi"),
    Moto("SKU-005", "Honda", "Dio 110"),
    Moto("SKU-006", "Honda", "XRE 300"),
    Moto("SKU-008", "Bajaj", "Pulsar NS 125"),
    Moto("SKU-009", "Bajaj", "Pulsar NS 160"),
    Moto("SKU-010", "Bajaj", "Pulsar RS 200"),
    Moto("SKU-017", "AKT", "NKD 125"),
])


def _resumen(texto: str) -> tuple:
    r = resolver_modelo(texto, CATALOGO)
    return (r.sku, r.marca, r.metodo)


def test_normalizacion_quita_solo_el_anio_final() -> None:
    assert normalizar_texto_modelo("Honda  Navi 2026 ") == "honda navi"
    assert normalizar_texto_modelo("A.K.T NKD 125") == "akt nkd 125"
    assert normalizar_texto_modelo("Modelo 2026 especial") == "modelo 2026 especial"


def test_exacto_tras_normalizar() -> None:
    assert _resumen("HONDA CB 190R") == ("SKU-003", "Honda", "exacto")
    assert _resumen("Honda Navi 2026") == ("SKU-004", "Honda", "exacto")
    assert _resumen("A.K.T NKD 125") == ("SKU-017", "AKT", "exacto")


def test_linea_sin_marca() -> None:
    assert _resumen("CB 190R") == ("SKU-003", "Honda", "exacto_linea")


def test_solo_marca_no_inventa_sku() -> None:
    assert _resumen("Bajaj") == (None, "Bajaj", "solo_marca")


def test_linea_parcial_unica_resuelve_por_palabras_completas() -> None:
    assert _resumen("Honda Dio") == ("SKU-005", "Honda", "linea_parcial")
    # "xr" es la primera palabra de "XR 150L" pero no de "XRE 300"
    assert _resumen("Honda XR") == ("SKU-002", "Honda", "linea_parcial")


def test_linea_parcial_ambigua_queda_en_marca() -> None:
    assert _resumen("Bajaj Pulsar") == (None, "Bajaj", "solo_marca")
    assert _resumen("Honda CB") == (None, "Honda", "solo_marca")


def test_marca_mal_escrita_resuelve_por_fuzzy_con_ambos_scores() -> None:
    r = resolver_modelo("Hnda CB 190R", CATALOGO)
    assert (r.sku, r.metodo) == ("SKU-003", "fuzzy")
    assert r.confianza == 96.0
    assert r.score_segundo is not None and r.score_segundo < 85


def test_fuzzy_elige_el_mejor_entre_lineas_parecidas() -> None:
    r = resolver_modelo("Bajai Pulsar NS 160", CATALOGO)
    assert r.sku == "SKU-009"
    assert r.confianza is not None and r.score_segundo is not None
    assert r.confianza > r.score_segundo


def test_texto_irreconocible_sin_match() -> None:
    assert _resumen("Vespa Primavera") == (None, None, "sin_match")


@pytest.fixture
def resuelto(base_de_prueba: None) -> dict:
    ingestar(RAIZ / "data" / "input")
    cargar_referencia()
    normalizar()
    return resolver_modelos()


def test_distribucion_sobre_los_datos_reales(resuelto: dict) -> None:
    assert resuelto == {
        "exacto": 1077,
        "solo_marca": 109,
        "exacto_linea": 100,
        "sin_texto": 79,
        "linea_parcial": 69,
        "fuzzy": 66,
    }


def test_fuzzy_real_tiene_margen_sobre_el_segundo(resuelto: dict) -> None:
    with conectar() as conn:
        fila = conn.execute(
            """
            SELECT min(match_confidence), max(match_score_segundo)
            FROM leads WHERE match_method = 'fuzzy'
            """
        ).fetchone()
    assert fila is not None
    ganador_min, segundo_max = fila
    assert ganador_min >= 85 > segundo_max


def test_reejecutar_escribe_lo_mismo(resuelto: dict) -> None:
    consulta = """
        SELECT md5(string_agg(concat_ws('|', lead_id, sku, marca, match_method,
                                        match_confidence, match_score_segundo), ',' ORDER BY lead_id))
        FROM leads
    """
    with conectar() as conn:
        antes = conn.execute(consulta).fetchone()
    assert resolver_modelos() == resuelto
    with conectar() as conn:
        assert conn.execute(consulta).fetchone() == antes
