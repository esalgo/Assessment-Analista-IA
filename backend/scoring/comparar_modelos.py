"""Compara cuatro familias de modelos sobre historico_cierres, con AUC en CV5.

Uso: python -m backend.scoring.comparar_modelos

Solo mide; no entrena el modelo que usa el score. Dos conjuntos de variables:
- produccion: las que se pueden calcular para un lead nuevo al priorizarlo.
- completo: produccion + horas_al_primer_contacto y numero_contactos, que no
  existen al momento de priorizar. Solo sirve para medir cuánto AUC cuesta
  la restricción.

Las filas "Sin gestión" se excluyen al cargar (ver backend/scoring/historico.py).

Todos los modelos usan los mismos 5 pliegues, así que la diferencia contra
la logística se calcula pliegue a pliegue (comparación pareada). Además se
repite la CV5 con 10 semillas de partición: con 197 positivos, cambiar solo
qué fila cae en qué pliegue mueve el AUC de un mismo modelo en ~0,03, más que
varias de las diferencias entre familias.

Sin ajuste de hiperparámetros: ajustarlos con los mismos pliegues inflaría
el AUC del modelo ajustado y exigiría validación cruzada anidada.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from backend.scoring.historico import cargar_historico

SEMILLA = 42
CATEGORICAS = ["canal", "manifesto_cuota_inicial", "forma_pago", "pidio_cita"]
VARIABLES_PRODUCCION = CATEGORICAS + ["log_precio_lista"]
VARIABLES_COMPLETO = VARIABLES_PRODUCCION + ["horas_al_primer_contacto", "numero_contactos"]


def matriz(datos: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    """One-hot para las categóricas (se descarta una categoría de referencia)."""
    categoricas = [v for v in variables if v in CATEGORICAS]
    numericas = [v for v in variables if v not in CATEGORICAS]
    dummies = pd.get_dummies(datos[categoricas], drop_first=True, dtype=float)
    return pd.concat([dummies, datos[numericas]], axis=1)


def modelos() -> dict:
    # La logística y el SVM dependen de la escala de las variables; los árboles no.
    return {
        "Regresión logística": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
        "SVM (kernel RBF)": make_pipeline(StandardScaler(), SVC(kernel="rbf")),
        "Random Forest": RandomForestClassifier(n_estimators=500, random_state=SEMILLA, n_jobs=-1),
        "Gradient Boosting": GradientBoostingClassifier(random_state=SEMILLA),
    }


def comparar(X: pd.DataFrame, y: pd.Series, semilla: int = SEMILLA) -> dict[str, np.ndarray]:
    pliegues = StratifiedKFold(n_splits=5, shuffle=True, random_state=semilla)
    return {nombre: cross_val_score(m, X, y, cv=pliegues, scoring="roc_auc") for nombre, m in modelos().items()}


def tabla_semillas(X: pd.DataFrame, y: pd.Series, semillas: int = 10) -> str:
    """AUC medio de la CV5 repetida con distintas particiones."""
    medias: dict[str, list[float]] = {nombre: [] for nombre in modelos()}
    for semilla in range(semillas):
        for nombre, valores in comparar(X, y, semilla).items():
            medias[nombre].append(valores.mean())
    base = np.array(medias["Regresión logística"])
    lineas = [
        f"| Modelo | AUC medio ({semillas} semillas) | Rango entre semillas | Δ vs logística (rango) |",
        "|---|---|---|---|",
    ]
    for nombre, lista in medias.items():
        valores = np.array(lista)
        diferencia = valores - base
        delta = (
            "—" if nombre == "Regresión logística"
            else f"{diferencia.mean():+.3f} ({diferencia.min():+.3f} a {diferencia.max():+.3f})"
        )
        lineas.append(f"| {nombre} | {valores.mean():.3f} | {valores.min():.3f}–{valores.max():.3f} | {delta} |")
    return "\n".join(lineas)


def tabla(aucs: dict[str, np.ndarray]) -> str:
    base = aucs["Regresión logística"]
    lineas = [
        "| Modelo | AUC medio | Desv. entre pliegues | Δ vs logística (media ± desv. pareada) |",
        "|---|---|---|---|",
    ]
    for nombre, valores in aucs.items():
        diferencia = valores - base
        delta = "—" if nombre == "Regresión logística" else f"{diferencia.mean():+.3f} ± {diferencia.std():.3f}"
        lineas.append(f"| {nombre} | {valores.mean():.3f} | {valores.std():.3f} | {delta} |")
    return "\n".join(lineas)


def main() -> None:
    datos, y = cargar_historico()
    print(f"Filas de entrenamiento: {len(y)} ({y.sum()} cerrados, tasa {y.mean():.1%})\n")
    resultados = {}
    for nombre, variables in [("produccion", VARIABLES_PRODUCCION), ("completo", VARIABLES_COMPLETO)]:
        resultados[nombre] = comparar(matriz(datos, variables), y)
        print(f"## Variables: {nombre} ({', '.join(variables)})\n")
        print(f"CV5, semilla {SEMILLA}:\n")
        print(tabla(resultados[nombre]))
        print("\nCV5 repetida:\n")
        print(tabla_semillas(matriz(datos, variables), y))
        print()

    costo = resultados["completo"]["Regresión logística"] - resultados["produccion"]["Regresión logística"]
    print(f"Costo de la restricción (logística, completo − produccion): {costo.mean():+.3f} ± {costo.std():.3f}")
    print("AUC por pliegue:")
    for conjunto, aucs in resultados.items():
        for nombre, valores in aucs.items():
            print(f"  {conjunto:<10} {nombre:<20} {' '.join(f'{v:.3f}' for v in valores)}")


if __name__ == "__main__":
    main()
