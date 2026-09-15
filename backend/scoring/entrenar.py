"""Entrena la regresión logística del score y exporta los pesos a config/score_weights.json.

Uso: python -m backend.scoring.entrenar

Variables: pidio_cita, manifesto_cuota_inicial y forma_pago. Existen para un
lead nuevo al priorizarlo, y sus pesos tienen intervalos que no cruzan el
cero. canal y precio salieron del modelo en logit_v2: sus cuatro pesos
cruzaban el cero en logit_v1.

La urgencia no es una variable del modelo sino un multiplicador del score.
Sus valores también se calculan aquí, desde la tabla de tasas del histórico:
multiplicador de un tramo = tasa de cierre del tramo / tasa base.

De coeficientes a puntos:
1. Se ajusta la logística sin regularización (máxima verosimilitud), con
   una categoría de referencia por variable. La elección de la referencia
   no cambia el resultado final, porque después se centra.
2. Cada categoría recibe su coeficiente menos el promedio de los
   coeficientes de las categorías *informadas*, ponderado por cuántas filas
   del histórico tiene cada una. Así un lead con información sube o baja
   respecto de la tasa base, y uno sin información (NO_INFORMA /
   no_informa) queda en 0 puntos: sin información, sin ajuste.
3. Puntos = log-odds centrados × 100, redondeados. 1 punto = 0,01 de log-odds.

El intervalo de cada peso sale de un bootstrap sobre las filas del histórico:
dice cuánto se movería el peso con otra muestra de 2.021 leads.
"""

import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

from backend.config import RAIZ
from backend.scoring.historico import cargar_historico

SCORE_VERSION = "logit_v2"
RUTA_PESOS = RAIZ / "config" / "score_weights.json"
PUNTOS_POR_LOG_ODDS = 100
SEMILLA = 42
REPETICIONES_BOOTSTRAP = 500

# Orden de cada lista: la primera categoría es la referencia de la regresión.
CATEGORIAS = {
    "manifesto_cuota_inicial": ["NO", "SI", "NO_INFORMA"],
    "forma_pago": ["credito", "contado", "no_informa"],
    "pidio_cita": ["NO", "SI"],
}
# La categoría que significa "sin información".
SIN_INFORMACION = {
    "manifesto_cuota_inicial": "NO_INFORMA",
    "forma_pago": "no_informa",
    "pidio_cita": "NO_INFORMA",
}


def matriz(datos: pd.DataFrame) -> pd.DataFrame:
    columnas = {}
    for variable, categorias in CATEGORIAS.items():
        for categoria in categorias[1:]:
            columnas[f"{variable}={categoria}"] = (datos[variable] == categoria).astype(float)
    return pd.DataFrame(columnas)


def ajustar(datos: pd.DataFrame, y: pd.Series) -> LogisticRegression:
    return LogisticRegression(C=np.inf, max_iter=5000).fit(matriz(datos), y)


def log_odds_centrados(modelo: LogisticRegression, datos: pd.DataFrame) -> dict:
    coeficientes = dict(zip(matriz(datos).columns, modelo.coef_[0]))
    resultado: dict = {}
    for variable, categorias in CATEGORIAS.items():
        coef = {c: coeficientes.get(f"{variable}={c}", 0.0) for c in categorias}
        informadas = [c for c in categorias if c != SIN_INFORMACION.get(variable)]
        conteos = datos[variable].value_counts()
        promedio = sum(conteos[c] * coef[c] for c in informadas) / sum(conteos[c] for c in informadas)
        resultado[variable] = {c: coef[c] - promedio for c in informadas}
        resultado[variable][SIN_INFORMACION[variable]] = 0.0
    return resultado


def a_puntos(valor: float) -> int:
    return int(round(valor * PUNTOS_POR_LOG_ODDS))


def auc_validacion_cruzada(datos: pd.DataFrame, y: pd.Series, semillas: int = 10) -> list[float]:
    """AUC de este mismo modelo en CV5 repetida (misma forma que la comparación)."""
    medias = []
    for semilla in range(semillas):
        pliegues = StratifiedKFold(n_splits=5, shuffle=True, random_state=semilla)
        aucs = []
        for entrenamiento, prueba in pliegues.split(datos, y):
            modelo = ajustar(datos.iloc[entrenamiento], y.iloc[entrenamiento])
            probabilidades = modelo.predict_proba(matriz(datos.iloc[prueba]))[:, 1]
            aucs.append(roc_auc_score(y.iloc[prueba], probabilidades))
        medias.append(float(np.mean(aucs)))
    return medias


def intervalos_bootstrap(datos: pd.DataFrame, y: pd.Series) -> dict:
    """Percentiles 5 y 95 de los log-odds centrados sobre remuestreos del histórico."""
    generador = np.random.default_rng(SEMILLA)
    muestras: dict[str, list[float]] = {}
    for _ in range(REPETICIONES_BOOTSTRAP):
        indices = generador.integers(0, len(y), len(y))
        d, yy = datos.iloc[indices].reset_index(drop=True), y.iloc[indices].reset_index(drop=True)
        centrados = log_odds_centrados(ajustar(d, yy), d)
        for variable, valores in centrados.items():
            for categoria, v in valores.items():
                muestras.setdefault(f"{variable}={categoria}", []).append(v)
    return {
        clave: [a_puntos(float(np.percentile(v, 5))), a_puntos(float(np.percentile(v, 95)))]
        for clave, v in muestras.items()
    }


# Límite superior de cada tramo, en horas. El último no tiene límite.
TRAMOS_URGENCIA = [("<=1h", 1), ("1-4h", 4), ("4-24h", 24), ("24-48h", 48), (">48h", None)]


def multiplicadores_urgencia(datos: pd.DataFrame, y: pd.Series) -> list[dict]:
    """Tasa de cierre por tramo de horas al primer contacto, dividida por la tasa base."""
    tasa_base = y.mean()
    horas = datos["horas_al_primer_contacto"]
    tramos = []
    desde = 0.0
    for nombre, hasta in TRAMOS_URGENCIA:
        en_tramo = (horas > desde) & (horas <= hasta) if hasta is not None else (horas > desde)
        tasa = y[en_tramo].mean()
        tramos.append({
            "tramo": nombre,
            "horas_hasta": hasta,
            "leads": int(en_tramo.sum()),
            "tasa_cierre": round(float(tasa), 4),
            "multiplicador": round(float(tasa / tasa_base), 2),
        })
        desde = hasta if hasta is not None else desde
    return tramos


def main() -> None:
    datos, y = cargar_historico()
    modelo = ajustar(datos, y)
    centrados = log_odds_centrados(modelo, datos)
    intervalos = intervalos_bootstrap(datos, y)
    aucs = auc_validacion_cruzada(datos, y)
    tasa_base = float(y.mean())

    pesos = {
        "score_version": SCORE_VERSION,
        "modelo": "regresión logística sin regularización, pesos centrados en la tasa base",
        "entrenamiento": {
            "tabla": "historico_cierres",
            "excluidas": "desenlace = 'Sin gestión' (fuga de información)",
            "filas": int(len(y)),
            "cerrados": int(y.sum()),
            "tasa_base": round(tasa_base, 4),
        },
        "puntos_por_log_odds": PUNTOS_POR_LOG_ODDS,
        "regla_sin_informacion": "NO_INFORMA / no_informa = 0 puntos: el lead queda en la tasa base",
        "variables": {
            variable: {categoria: a_puntos(v) for categoria, v in valores.items()}
            for variable, valores in centrados.items()
        },
        "urgencia": {
            "que_mide": "horas desde el registro sin contacto, al momento de priorizar",
            "lectura": (
                "premia la oportunidad, no un resultado: un lead pendiente en el tramo <=1h "
                "todavía puede contactarse dentro de la ventana que en el histórico cerró más"
            ),
            "tramos": multiplicadores_urgencia(datos, y),
        },
        "intervalo_90_bootstrap_puntos": intervalos,
        "validacion": {
            "auc_cv5_media_10_semillas": round(float(np.mean(aucs)), 3),
            "auc_rango_entre_semillas": [round(min(aucs), 3), round(max(aucs), 3)],
            "alcance": "mide solo las señales de la regresión; la urgencia es un multiplicador validado aparte",
        },
    }

    RUTA_PESOS.write_text(json.dumps(pesos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(pesos, ensure_ascii=False, indent=2))
    print(f"\nPesos escritos en {RUTA_PESOS.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
