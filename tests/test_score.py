"""Reglas derivadas del score sobre la extracción, sin base de datos."""

from backend.stages.score import REGLA_INICIAL_IMPLICA_CREDITO, forma_pago_para_score, sku_para_score


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
