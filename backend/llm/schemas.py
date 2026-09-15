"""JSON Schema estricto de la extracción.

Con `strict: true` la API garantiza que la respuesta cumple este esquema:
todos los campos presentes, sin campos extra y solo valores de los enums.

forma_pago y manifesto_cuota_inicial usan los mismos valores que
historico_cierres.csv, y pidio_cita los mismos SI/NO. Los tres agregan
NO_INFORMA porque una conversación puede no tocar el tema; el histórico
no lo necesita porque ahí el dato ya está registrado.

objecion_principal ganó sin_inicial e historial_crediticio en extraccion_v2;
las filas de v1 se generaron con el enum anterior.

El orden de las propiedades importa: el modelo escribe el JSON en ese
orden. cuota_inicial_cop depende de forma_pago y de manifesto_cuota_inicial,
así que va después de ambos. Hasta extraccion_v3 iba antes, y el modelo
fijaba el monto sin haber decidido todavía que la compra era de contado.

sku_resuelto no está aquí: lo calcula resolve-models sobre
modelo_interes_mencionado, no el LLM.
"""

SI_NO_INFORMA = ["SI", "NO", "NO_INFORMA"]

SCHEMA_EXTRACCION: dict = {
    "type": "object",
    "properties": {
        "modelo_interes_mencionado": {"type": ["string", "null"]},
        "forma_pago": {"type": "string", "enum": ["contado", "credito", "no_informa"]},
        "manifesto_cuota_inicial": {"type": "string", "enum": SI_NO_INFORMA},
        "cuota_inicial_cop": {"type": ["integer", "null"]},
        "pidio_cita": {"type": "string", "enum": SI_NO_INFORMA},
        "pidio_cotizacion": {"type": "string", "enum": SI_NO_INFORMA},
        "intencion_declarada": {
            "type": "string",
            "enum": ["compra_inmediata", "comparando", "explorando", "descartado", "no_informa"],
        },
        "objecion_principal": {
            "type": "string",
            "enum": [
                "precio", "tasa", "cuota", "sin_inicial", "historial_crediticio",
                "disponibilidad", "tramites", "ninguna", "otra",
            ],
        },
        "justificacion": {"type": "string", "maxLength": 200},
        "confianza": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "modelo_interes_mencionado",
        "forma_pago",
        "manifesto_cuota_inicial",
        "cuota_inicial_cop",
        "pidio_cita",
        "pidio_cotizacion",
        "intencion_declarada",
        "objecion_principal",
        "justificacion",
        "confianza",
    ],
    "additionalProperties": False,
}
