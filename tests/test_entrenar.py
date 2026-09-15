"""Regla de centrado de los pesos del score, con datos sintéticos (sin base de datos)."""

import numpy as np
import pandas as pd

from backend.scoring.entrenar import ajustar, log_odds_centrados


def _historico_sintetico() -> tuple[pd.DataFrame, pd.Series]:
    generador = np.random.default_rng(0)
    n = 3000
    datos = pd.DataFrame({
        "canal": generador.choice(["Formulario Web", "Meta Ads", "WhatsApp"], n),
        "manifesto_cuota_inicial": generador.choice(["SI", "NO", "NO_INFORMA"], n),
        "forma_pago": generador.choice(["contado", "credito", "no_informa"], n),
        "pidio_cita": generador.choice(["SI", "NO"], n, p=[0.3, 0.7]),
        "log_precio_lista": np.log(generador.choice([5e6, 1e7, 2e7], n)),
    })
    log_odds = -2.5 + 0.8 * (datos["pidio_cita"] == "SI") + 0.6 * (datos["manifesto_cuota_inicial"] == "SI")
    y = pd.Series((generador.random(n) < 1 / (1 + np.exp(-log_odds))).astype(int))
    return datos, y


def test_sin_informacion_vale_cero_y_las_informadas_quedan_centradas() -> None:
    datos, y = _historico_sintetico()
    centrados = log_odds_centrados(ajustar(datos, y), datos)

    assert centrados["pidio_cita"]["NO_INFORMA"] == 0.0
    assert centrados["manifesto_cuota_inicial"]["NO_INFORMA"] == 0.0
    assert centrados["forma_pago"]["no_informa"] == 0.0

    for variable, informadas in [("pidio_cita", ["SI", "NO"]), ("manifesto_cuota_inicial", ["SI", "NO"])]:
        conteos = datos[variable].value_counts()
        promedio = sum(conteos[c] * centrados[variable][c] for c in informadas) / sum(conteos[c] for c in informadas)
        assert abs(promedio) < 1e-9

    assert centrados["pidio_cita"]["SI"] > 0 > centrados["pidio_cita"]["NO"]
    assert centrados["manifesto_cuota_inicial"]["SI"] > 0 > centrados["manifesto_cuota_inicial"]["NO"]
