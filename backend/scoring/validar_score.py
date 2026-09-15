"""Validación del componente de señales del score sobre el histórico.

Uso: python -m backend.scoring.validar_score

Mide solo las señales de la conversación (pesos logit_v2). La urgencia no
entra aquí: es un multiplicador con su propia tabla (docs/validacion.md, 2.3).

- Predicciones fuera de pliegue: los puntos de cada lead salen de pesos
  entrenados sin ese lead. Puntuar con pesos entrenados sobre las mismas
  filas sería optimista.
- CV5 repetida con 10 semillas, como en la comparación de modelos.
- Hay muchos empates de puntos: los deciles no están bien definidos. Los
  empates se desempatan al azar y los resultados se promedian sobre las
  repeticiones. Por eso también se reporta la tasa por combinación de
  señales, que no depende de desempates ni de parámetros entrenados.
- Se puntúan los puntos que usa producción: NO_INFORMA / no_informa = 0.
- Sin la regla inicial_mencionada_implica_credito: describe cómo el LLM
  llena forma_pago en una conversación. En el histórico no_informa lo
  registró un asesor, y esas filas cierran por encima de la base.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

from backend.scoring.entrenar import a_puntos, ajustar, log_odds_centrados
from backend.scoring.historico import cargar_historico
from backend.stages.score import temperatura_por_senales

SEMILLAS = 10


def puntos_fuera_de_pliegue(datos: pd.DataFrame, y: pd.Series, semilla: int) -> np.ndarray:
    puntos = np.zeros(len(y), dtype=int)
    pliegues = StratifiedKFold(n_splits=5, shuffle=True, random_state=semilla)
    for entrenamiento, prueba in pliegues.split(datos, y):
        d = datos.iloc[entrenamiento]
        centrados = log_odds_centrados(ajustar(d, y.iloc[entrenamiento]), d)
        for i in prueba:
            fila = datos.iloc[i]
            puntos[i] = sum(a_puntos(centrados[v][fila[v]]) for v in ("pidio_cita", "manifesto_cuota_inicial", "forma_pago"))
    return puntos


def tabla_deciles(datos: pd.DataFrame, y: pd.Series, repeticiones: list[np.ndarray]) -> tuple[str, float, float]:
    tasa_base = y.mean()
    tasas = np.zeros((len(repeticiones), 10))
    lifts_top20 = []
    generador = np.random.default_rng(0)
    for r, puntos in enumerate(repeticiones):
        azar = generador.random(len(y))
        # Mayor puntaje primero; empates al azar.
        orden = np.lexsort((azar, -puntos))
        decil = np.empty(len(y), dtype=int)
        decil[orden] = np.arange(len(y)) * 10 // len(y)
        for d in range(10):
            tasas[r, d] = y[decil == d].mean()
        top20 = decil < 2
        lifts_top20.append(y[top20].mean() / tasa_base)

    lineas = ["| Decil (1 = mayor puntaje) | Tasa de cierre (media 10 rep.) | Rango entre repeticiones | Lift vs base |",
              "|---|---|---|---|"]
    for d in range(10):
        media = tasas[:, d].mean()
        lineas.append(
            f"| {d + 1} | {media:.1%} | {tasas[:, d].min():.1%}–{tasas[:, d].max():.1%} | {media / tasa_base:.2f}x |"
        )
    return "\n".join(lineas), float(np.mean(lifts_top20)), float(np.min(lifts_top20))


def tabla_combinaciones(y: pd.Series, datos: pd.DataFrame) -> str:
    """Tasa de cierre real por combinación de señales, de la mayor a la menor.
    Es descriptiva: no usa pesos, así que no tiene fuga."""
    combinaciones = datos.assign(cerrado=y).groupby(
        ["pidio_cita", "manifesto_cuota_inicial", "forma_pago"]
    )["cerrado"].agg(["count", "mean"]).sort_values("mean", ascending=False)
    lineas = ["| Cita | Inicial | Forma de pago | Leads | Tasa de cierre | Lift vs base |", "|---|---|---|---|---|---|"]
    for (cita, inicial, forma), fila in combinaciones.iterrows():
        lineas.append(
            f"| {cita} | {inicial} | {forma} | {int(fila['count'])} | {fila['mean']:.1%} | {fila['mean'] / y.mean():.2f}x |"
        )
    return "\n".join(lineas)


def tabla_temperatura(datos: pd.DataFrame, y: pd.Series) -> str:
    """La temperatura es una regla sobre las señales, sin parámetros entrenados:
    no necesita validación cruzada."""
    temperaturas = [
        temperatura_por_senales([
            {"variable": v, "valor": fila[v]} for v in ("pidio_cita", "manifesto_cuota_inicial", "forma_pago")
        ])
        for _, fila in datos.iterrows()
    ]
    tabla = pd.crosstab(pd.Series(temperaturas, name="temperatura"), datos["desenlace"])
    lineas = ["| Temperatura | Cerrado | Perdido | Total | Tasa de cierre | Lift vs base |", "|---|---|---|---|---|---|"]
    for temperatura in ["alta", "media", "baja"]:
        cerrados, perdidos = int(tabla.loc[temperatura, "Cerrado"]), int(tabla.loc[temperatura, "Perdido"])
        tasa = cerrados / (cerrados + perdidos)
        lineas.append(
            f"| {temperatura} | {cerrados} | {perdidos} | {cerrados + perdidos} | {tasa:.1%} | {tasa / y.mean():.2f}x |"
        )
    return "\n".join(lineas)


def main() -> None:
    datos, y = cargar_historico()
    print(f"Histórico sin 'Sin gestión': {len(y)} leads, {y.sum()} cerrados, tasa base {y.mean():.2%}\n")
    repeticiones = [puntos_fuera_de_pliegue(datos, y, s) for s in range(SEMILLAS)]
    aucs = [roc_auc_score(y, puntos) for puntos in repeticiones]
    print(f"AUC de los puntos fuera de pliegue: {np.mean(aucs):.3f} (rango {min(aucs):.3f}–{max(aucs):.3f})\n")

    deciles, lift_medio, lift_minimo = tabla_deciles(datos, y, repeticiones)
    print("## Tasa de cierre por decil de puntos (fuera de pliegue)\n")
    print(deciles)
    print(f"\nLift del top 20 %: {lift_medio:.2f}x en promedio (mínimo entre repeticiones {lift_minimo:.2f}x)\n")
    print("## Tasa de cierre por combinación de señales\n")
    print(tabla_combinaciones(y, datos))
    print("\n## Temperatura × desenlace\n")
    print(tabla_temperatura(datos, y))


if __name__ == "__main__":
    main()
