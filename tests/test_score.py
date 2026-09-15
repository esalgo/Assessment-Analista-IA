"""Reglas del score sobre la extracción y el grupo fusionado, sin base de datos."""

from datetime import datetime

from backend.stages.score import (
    REGLA_INICIAL_IMPLICA_CREDITO,
    a_escala_0_100,
    cargar_pesos,
    clave_de_orden,
    estado_consolidado,
    extraccion_consolidada,
    forma_pago_para_score,
    log_odds_relativos,
    punto_venta_del_grupo,
    puntos_posibles,
    rango_log_odds,
    sku_para_score,
    temperatura_por_senales,
    tramo_urgencia,
)

PESOS = cargar_pesos()


def _dia(d: int) -> datetime:
    return datetime(2026, 8, d)


def test_no_tengo_inicial_sin_forma_de_pago_es_credito_y_se_registra_la_regla() -> None:
    extraccion = {"forma_pago": "no_informa", "manifesto_cuota_inicial": "NO"}
    assert forma_pago_para_score(extraccion) == ("credito", REGLA_INICIAL_IMPLICA_CREDITO)
    assert extraccion["forma_pago"] == "no_informa"


def test_regla_no_aplica_si_la_inicial_no_salio_o_la_forma_de_pago_ya_viene() -> None:
    assert forma_pago_para_score({"forma_pago": "no_informa", "manifesto_cuota_inicial": "NO_INFORMA"}) == ("no_informa", None)
    assert forma_pago_para_score({"forma_pago": "contado", "manifesto_cuota_inicial": "NO_INFORMA"}) == ("contado", None)
    assert forma_pago_para_score({"forma_pago": "credito", "manifesto_cuota_inicial": "SI"}) == ("credito", None)


def test_sku_de_la_conversacion_gana_y_formulario_es_respaldo() -> None:
    assert sku_para_score("SKU-018", {"sku_resuelto": "SKU-006"}) == ("SKU-006", "conversacion")
    assert sku_para_score("SKU-018", {"sku_resuelto": None}) == ("SKU-018", "formulario")
    assert sku_para_score("SKU-018", None) == ("SKU-018", "formulario")
    assert sku_para_score(None, None) == (None, None)


def test_estado_mas_avanzado_del_embudo() -> None:
    assert estado_consolidado([(_dia(1), "cotizacion_enviada"), (_dia(5), "sin_gestion")]) == "cotizacion_enviada"


def test_descartado_mas_reciente_gana_y_anterior_no() -> None:
    assert estado_consolidado([(_dia(1), "contactado"), (_dia(9), "descartado")]) == "descartado"
    assert estado_consolidado([(_dia(1), "descartado"), (_dia(9), "no_contesta")]) == "no_contesta"


def test_extraccion_del_grupo_toma_el_ultimo_valor_informado_por_campo() -> None:
    antigua = {"pidio_cita": "SI", "manifesto_cuota_inicial": "SI", "forma_pago": "credito"}
    reciente = {"pidio_cita": "NO_INFORMA", "manifesto_cuota_inicial": "NO", "forma_pago": "no_informa"}
    consolidada = extraccion_consolidada([(_dia(9), reciente), (_dia(1), antigua)])
    assert consolidada["pidio_cita"] == "SI"
    assert consolidada["manifesto_cuota_inicial"] == "NO"
    assert consolidada["forma_pago"] == "credito"
    assert extraccion_consolidada([]) is None


def test_urgencia_por_tramo_y_contactado_sin_tramo() -> None:
    assert tramo_urgencia(0.5, PESOS)["tramo"] == "<=1h"
    assert tramo_urgencia(4, PESOS)["tramo"] == "1-4h"
    assert tramo_urgencia(300, PESOS)["tramo"] == ">48h"
    assert tramo_urgencia(None, PESOS) is None


def test_sin_senales_y_sin_urgencia_queda_en_50() -> None:
    assert a_escala_0_100(log_odds_relativos(0, 1.0, PESOS), PESOS) == 50


def test_extremos_alcanzables_dan_0_y_100() -> None:
    puntos = puntos_posibles(PESOS)
    multiplicadores = [t["multiplicador"] for t in PESOS["urgencia"]["tramos"]]
    assert a_escala_0_100(log_odds_relativos(puntos[-1], max(multiplicadores), PESOS), PESOS) == 100
    assert a_escala_0_100(log_odds_relativos(puntos[0], min(multiplicadores), PESOS), PESOS) == 0
    minimo, maximo = rango_log_odds(PESOS)
    assert minimo < 0 < maximo


def test_contado_con_inicial_no_cuenta_como_combinacion_posible() -> None:
    variables = PESOS["variables"]
    imposible = variables["forma_pago"]["contado"] + variables["manifesto_cuota_inicial"]["SI"] + variables["pidio_cita"]["SI"]
    assert imposible not in puntos_posibles(PESOS)


def test_dentro_de_la_cola_desempata_lo_mas_fresco() -> None:
    clientes = [("viejo", 50, 900.0), ("fresco", 50, 3.0), ("mejor_score", 64, 1000.0)]
    ordenados = sorted(clientes, key=lambda c: clave_de_orden(c[1], c[2]))
    assert [c[0] for c in ordenados] == ["mejor_score", "fresco", "viejo"]


def _factor(variable: str, valor: str) -> dict:
    return {"variable": variable, "valor": valor, "puntos": 1}


def test_temperatura_sale_de_las_senales_positivas_no_de_la_capacidad() -> None:
    assert temperatura_por_senales([_factor("pidio_cita", "SI"), _factor("forma_pago", "contado")]) == "alta"
    assert temperatura_por_senales([_factor("pidio_cita", "SI"), _factor("manifesto_cuota_inicial", "SI"), _factor("forma_pago", "credito")]) == "alta"
    assert temperatura_por_senales([_factor("manifesto_cuota_inicial", "SI"), _factor("forma_pago", "credito")]) == "media"
    assert temperatura_por_senales([_factor("forma_pago", "credito"), _factor("pidio_cita", "NO")]) == "baja"
    assert temperatura_por_senales([]) == "baja"


def test_cliente_fusionado_va_al_punto_de_venta_del_lead_mas_reciente() -> None:
    leads = [(_dia(3), "LD-00004", "PV-002"), (_dia(6), "LD-00052", "PV-004")]
    assert punto_venta_del_grupo(leads) == "PV-004"
