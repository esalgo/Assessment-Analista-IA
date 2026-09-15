"""Chequeos de la extracción que no necesitan llamar al LLM."""

from backend.llm.cache import hash_conversacion
from backend.llm.validacion import campos_informados, violaciones_consistencia

TEXTO = (
    "## Conversación CONV-1 · inicio 2026-08-09 20:06\n"
    "[20:06] cliente: Qué más pues, me interesa la Honda Dio 110\n"
    "[20:24] asesor: Con esa inicial la cuota le queda alrededor de $480.000 a 48 meses.\n"
    "[20:28] cliente: De contado, ya tengo la plata lista, 6800mil"
)


def _payload(**cambios: object) -> dict:
    base = {
        "modelo_interes_mencionado": "Honda Dio 110",
        "cuota_inicial_cop": None,
        "forma_pago": "contado",
        "manifesto_cuota_inicial": "NO_INFORMA",
        "pidio_cita": "NO_INFORMA",
        "pidio_cotizacion": "NO_INFORMA",
        "intencion_declarada": "compra_inmediata",
        "objecion_principal": "ninguna",
        "justificacion": "De contado, ya tengo la plata lista, 6800mil",
        "confianza": 1,
    }
    return base | cambios


def test_hash_cambia_con_la_version_del_prompt() -> None:
    assert hash_conversacion(TEXTO, "extraccion_v1") != hash_conversacion(TEXTO, "extraccion_v2")
    assert hash_conversacion(TEXTO, "extraccion_v2") == hash_conversacion(TEXTO, "extraccion_v2")


def test_salida_consistente_no_tiene_violaciones() -> None:
    assert violaciones_consistencia(_payload(), TEXTO) == []


def test_contado_con_inicial_se_registra_sin_corregir() -> None:
    payload = _payload(manifesto_cuota_inicial="SI", cuota_inicial_cop=6800000)
    violaciones = violaciones_consistencia(payload, TEXTO)
    assert "contado_con_cuota_inicial" in violaciones
    assert payload["cuota_inicial_cop"] == 6800000


def test_monto_sin_manifestar_inicial() -> None:
    payload = _payload(forma_pago="credito", manifesto_cuota_inicial="NO", cuota_inicial_cop=1000000)
    assert violaciones_consistencia(payload, TEXTO) == ["monto_sin_manifestar_inicial"]


def test_inicial_cero_es_no_y_conserva_el_monto() -> None:
    credito = {"forma_pago": "credito", "justificacion": ""}
    assert violaciones_consistencia(_payload(**credito, manifesto_cuota_inicial="NO", cuota_inicial_cop=0), TEXTO) == []
    assert violaciones_consistencia(_payload(**credito, manifesto_cuota_inicial="SI", cuota_inicial_cop=0), TEXTO) == [
        "inicial_cero_marcada_como_si"
    ]


def test_cita_del_asesor_no_cuenta_como_literal_del_cliente() -> None:
    payload = _payload(justificacion="De contado, ya tengo la plata lista, 6800mil | la cuota le queda alrededor de $480.000")
    assert violaciones_consistencia(payload, TEXTO) == ["justificacion_no_literal_del_cliente"]


def test_campos_informados_ignora_no_informa_en_ambas_grafias() -> None:
    assert campos_informados(_payload()) == 2
    assert campos_informados(_payload(forma_pago="no_informa", intencion_declarada="no_informa")) == 0
