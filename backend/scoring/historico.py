"""Carga de historico_cierres para la comparación de modelos y el entrenamiento.

Las filas "Sin gestión" se excluyen: tienen horas nulas y 0 contactos, así
que el desenlace se filtra en las variables (fuga de información).
"""

import numpy as np
import pandas as pd

from backend.db.conexion import conectar

COLUMNAS = [
    "canal", "manifesto_cuota_inicial", "forma_pago", "pidio_cita", "precio_lista",
    "horas_al_primer_contacto", "numero_contactos", "desenlace",
]


def cargar_historico() -> tuple[pd.DataFrame, pd.Series]:
    """ORDER BY fijo: los pliegues de la validación cruzada dependen del orden
    de las filas, y sin él una recarga de la tabla cambiaría los AUC."""
    with conectar() as conn:
        filas = conn.execute(
            f"""
            SELECT {", ".join(COLUMNAS)}
            FROM historico_cierres
            WHERE desenlace <> 'Sin gestión'
            ORDER BY lead_id
            """
        ).fetchall()
    datos = pd.DataFrame(filas, columns=COLUMNAS)
    datos["log_precio_lista"] = np.log(datos["precio_lista"].astype(float))
    datos["horas_al_primer_contacto"] = datos["horas_al_primer_contacto"].astype(float)
    objetivo = (datos["desenlace"] == "Cerrado").astype(int)
    return datos, objetivo
