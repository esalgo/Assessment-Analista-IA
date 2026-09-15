"""Etapa normalize: funciones puras primero, luego la etapa completa sobre los datos reales."""

from datetime import date, datetime

import pytest

from backend.config import RAIZ
from backend.db.conexion import conectar
from backend.stages.ingest import ingestar
from backend.stages.load_reference import cargar_referencia
from backend.stages.normalize import (
    ZONA,
    contacto_no_antes_de,
    es_fecha_sin_hora,
    lecturas_fecha,
    normalizar,
    normalizar_ciudad,
    normalizar_estado,
    normalizar_nombre,
    normalizar_telefono,
    resolver_contacto,
    resolver_registro,
)

VENTANA = (date(2026, 7, 25), date(2026, 9, 14))


def _fecha(texto: str) -> datetime:
    return datetime.fromisoformat(texto).replace(tzinfo=ZONA)


# --- Teléfonos -------------------------------------------------------------

def test_telefono_con_prefijo_57_pegado() -> None:
    assert normalizar_telefono("573223242028") == "3223242028"


def test_telefono_con_espacios_sobrantes() -> None:
    assert normalizar_telefono("  3149037411  ") == "3149037411"


def test_telefono_con_separadores() -> None:
    assert normalizar_telefono("+57 322 1743999") == "3221743999"
    assert normalizar_telefono("(315) 149-8889") == "3151498889"


def test_telefono_de_seis_digitos_es_invalido() -> None:
    assert normalizar_telefono("300123") is None


# --- Texto y catálogos -----------------------------------------------------

def test_nombre_recortado_en_title_case() -> None:
    assert normalizar_nombre("  HÉCTOR GIRALDO  RESTREPO ") == "Héctor Giraldo Restrepo"
    assert normalizar_nombre("Y. Castaño Valencia") == "Y. Castaño Valencia"


def test_variantes_de_ciudad_y_estado() -> None:
    assert {normalizar_ciudad(v) for v in ["Bogotá D.C.", "BOGOTA", "bogotá", "Bogota DC"]} == {"Bogotá"}
    assert normalizar_ciudad("Rio Negro") == "Rionegro"
    assert normalizar_ciudad("") is None
    assert normalizar_estado("SIN GESTION") == normalizar_estado("Sin gestión") == "sin_gestion"


# --- Fechas ----------------------------------------------------------------

@pytest.mark.parametrize(
    ("texto", "esperada"),
    [
        ("2026-08-29 22:58:00", "2026-08-29 22:58"),
        ("19/08/2026 17:40", "2026-08-19 17:40"),
        ("09-08-2026", "2026-08-09 00:00"),
        ("2026-08-24T14:11:00", "2026-08-24 14:11"),
    ],
)
def test_los_cuatro_formatos_parsean(texto: str, esperada: str) -> None:
    assert lecturas_fecha(texto) == [_fecha(esperada)]


def test_mm_dd_inequivoco_no_falla() -> None:
    assert lecturas_fecha("08/15/2026 10:00") == [_fecha("2026-08-15 10:00")]


def test_dia_imposible_no_tiene_lecturas() -> None:
    assert lecturas_fecha("2026-08-33 10:00:00") == []


def test_dia_igual_a_mes_no_es_ambiguo() -> None:
    assert lecturas_fecha("08/08/2026 10:00") == [_fecha("2026-08-08 10:00")]


def test_registro_ambiguo_resuelto_por_ventana_a_mm_dd() -> None:
    # dd/mm = 9 de mayo (fuera de ventana), mm/dd = 5 de septiembre
    resuelta = resolver_registro(lecturas_fecha("09/05/2026 15:44") or [], VENTANA)
    assert (resuelta.valor, resuelta.metodo, resuelta.ambigua) == (_fecha("2026-09-05 15:44"), "ventana", False)


def test_registro_irresoluble_queda_dd_mm_y_marcado() -> None:
    resuelta = resolver_registro(lecturas_fecha("09/08/2026 20:06") or [], VENTANA)
    assert (resuelta.valor, resuelta.metodo, resuelta.ambigua) == (_fecha("2026-08-09 20:06"), "irresoluble_ddmm", True)


def test_contacto_ambiguo_resuelto_por_coherencia_con_registro() -> None:
    # 12 sep y 9 dic: la ventana ya descarta diciembre
    resuelta = resolver_contacto(lecturas_fecha("09/12/2026 10:00") or [], _fecha("2026-09-10 08:00"), VENTANA)
    assert resuelta.valor == _fecha("2026-09-12 10:00")

    # 8 sep y 9 ago, ambas en ventana: solo 8 sep es posterior al registro
    resuelta = resolver_contacto(lecturas_fecha("08/09/2026 10:00") or [], _fecha("2026-09-01 08:00"), VENTANA)
    assert (resuelta.valor, resuelta.metodo) == (_fecha("2026-09-08 10:00"), "coherencia")


def test_contacto_sin_hora_el_mismo_dia_no_es_anterior_al_registro() -> None:
    # 03-09-2026 se parsea a medianoche; el registro fue a las 08:17 del mismo día
    assert contacto_no_antes_de(_fecha("2026-09-03 00:00"), True, _fecha("2026-09-03 08:17"))
    assert not contacto_no_antes_de(_fecha("2026-09-03 00:00"), False, _fecha("2026-09-03 08:17"))
    assert es_fecha_sin_hora("03-09-2026") and not es_fecha_sin_hora("2026-09-03 08:17:00")


def test_registro_irresoluble_desempatado_por_contacto_con_hora() -> None:
    # LD-00243: con dd/mm el contacto quedaría 30 días antes del registro
    resuelta = resolver_registro(
        lecturas_fecha("08/09/2026 11:29") or [], VENTANA, _fecha("2026-08-09 15:29"), False
    )
    assert (resuelta.valor, resuelta.metodo, resuelta.ambigua) == (_fecha("2026-08-09 11:29"), "coherencia", False)


def test_contacto_sin_hora_del_mismo_dia_no_desempata() -> None:
    # Lecturas 9 ago y 8 sep. Contacto 8 sep sin hora: compatible con ambas
    # (el mismo día nunca descarta), así que no decide.
    resuelta = resolver_registro(
        lecturas_fecha("09/08/2026 20:06") or [], VENTANA, _fecha("2026-09-08 00:00"), True
    )
    assert (resuelta.metodo, resuelta.ambigua) == ("irresoluble_ddmm", True)


def test_contacto_sin_hora_de_otro_dia_si_desempata() -> None:
    # Contacto 20 ago sin hora: la lectura 8 sep queda después del contacto por calendario
    resuelta = resolver_registro(
        lecturas_fecha("09/08/2026 20:06") or [], VENTANA, _fecha("2026-08-20 00:00"), True
    )
    assert (resuelta.valor, resuelta.metodo) == (_fecha("2026-08-09 20:06"), "coherencia")


def test_contacto_con_dos_lecturas_coherentes_gana_la_mas_cercana() -> None:
    resuelta = resolver_contacto(lecturas_fecha("09/08/2026 10:00") or [], _fecha("2026-08-08 08:00"), VENTANA)
    assert (resuelta.valor, resuelta.metodo, resuelta.ambigua) == (_fecha("2026-08-09 10:00"), "mas_cercana", True)


# --- Etapa completa --------------------------------------------------------

@pytest.fixture
def normalizado(base_de_prueba: None) -> dict:
    ingestar(RAIZ / "data" / "input")
    cargar_referencia()
    return normalizar().conteos


def test_lead_de_prueba_va_a_cuarentena_con_motivos_especificos(normalizado: dict) -> None:
    with conectar() as conn:
        motivos = {m for (m,) in conn.execute("SELECT motivo FROM cuarentena WHERE clave = 'LD-01501'")}
        en_leads = conn.execute("SELECT count(*) FROM leads WHERE lead_id = 'LD-01501'").fetchone()
    assert motivos == {"canal nulo", "fecha_registro imposible: 2026-08-33 10:00:00"}
    assert en_leads == (0,)


def test_copias_identicas_se_eliminan_y_queda_una(normalizado: dict) -> None:
    with conectar() as conn:
        fila = conn.execute("SELECT count(*) FROM leads WHERE lead_id IN ('LD-00011', 'LD-00251')").fetchone()
    assert fila == (2,)
    assert normalizado["cuarentena_lead_id_repetido"] == 2
    assert normalizado["leads_cargados"] == 1500


def test_conversacion_whatsapp_de_lead_meta_ads_se_procesa(normalizado: dict) -> None:
    with conectar() as conn:
        fila = conn.execute(
            """
            SELECT count(*) FROM conversaciones c JOIN leads l USING (lead_id)
            WHERE l.canal = 'Meta Ads' AND c.canal = 'WhatsApp'
            """
        ).fetchone()
    assert fila is not None and fila[0] > 0


def test_conversaciones_huerfanas_a_cuarentena_y_el_resto_sigue(normalizado: dict) -> None:
    assert normalizado["cuarentena_conversacion_huerfana"] == 12
    assert normalizado["conversaciones_cargadas"] == 665


def test_estado_gestionado_sin_contacto_se_marca(normalizado: dict) -> None:
    assert normalizado["estado_sin_contacto"] == 86


def test_sin_contactos_anteriores_al_registro_tras_resolver_fechas(normalizado: dict) -> None:
    # Con el parser ingenuo eran 129; los 61 de "mismo día sin hora" eran artefacto
    # y LD-00243 se resuelve por coherencia.
    assert normalizado["contacto_antes_registro"] == 0
    assert normalizado["fecha_contacto_sin_hora"] == 208


def test_reejecutar_da_el_mismo_resultado(normalizado: dict) -> None:
    consulta = """
        SELECT md5(string_agg(t::text, '|' ORDER BY t::text))
        FROM (SELECT l.*, (SELECT count(*) FROM mensajes) AS mensajes,
                     (SELECT count(*) FROM cuarentena) AS cuarentena FROM leads l) t
    """
    with conectar() as conn:
        antes = conn.execute(consulta).fetchone()
    segunda = normalizar().conteos
    with conectar() as conn:
        despues = conn.execute(consulta).fetchone()
    assert antes == despues
    assert segunda == normalizado
