"""Etapa score. Por ahora solo las reglas derivadas sobre la extracción del LLM.

Una regla derivada no modifica la salida del LLM guardada en extracciones_ia:
calcula el valor que usa el score y devuelve el nombre de la regla aplicada,
para que quede en `scores.factores` y el tablero pueda mostrarla.
"""

REGLA_INICIAL_IMPLICA_CREDITO = "inicial_mencionada_implica_credito"


def forma_pago_para_score(extraccion: dict) -> tuple[str, str | None]:
    """Si el tema de la inicial salió (SI o NO) y el LLM dejó forma_pago en
    no_informa, la forma de pago es crédito: nadie que pague de contado dice
    "no tengo inicial". Devuelve (valor, regla aplicada o None)."""
    forma_pago = extraccion["forma_pago"]
    if forma_pago == "no_informa" and extraccion["manifesto_cuota_inicial"] in ("SI", "NO"):
        return "credito", REGLA_INICIAL_IMPLICA_CREDITO
    return forma_pago, None


def sku_para_score(sku_formulario: str | None, extraccion: dict | None) -> tuple[str | None, str | None]:
    """El score usa el SKU de la conversación cuando existe: es lo que el
    cliente pidió por escrito, evidencia más rica que un campo de formulario.
    Ambos se conservan (leads.sku y extracciones_ia.payload) para que el
    tablero muestre los dos cuando difieran. Devuelve (sku, fuente)."""
    if extraccion and extraccion.get("sku_resuelto"):
        return extraccion["sku_resuelto"], "conversacion"
    if sku_formulario:
        return sku_formulario, "formulario"
    return None, None
