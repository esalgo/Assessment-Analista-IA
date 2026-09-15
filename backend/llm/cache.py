"""Clave de caché de la extracción.

La caché es la propia tabla extracciones_ia: si ya hay una fila con
(lead_id, conversacion_hash), la conversación no se vuelve a enviar.
Cambiar el texto de la conversación o la versión del prompt cambia el
hash, y solo entonces se paga una llamada nueva.
"""

import hashlib


def hash_conversacion(texto_conversacion: str, prompt_version: str) -> str:
    return hashlib.sha256((texto_conversacion + prompt_version).encode("utf-8")).hexdigest()
