"""Catálogos de valores válidos y sus variantes conocidas en los archivos.

Las claves de cada diccionario pasan por `clave()`: minúsculas, sin tildes
y con espacios colapsados. Así "BOGOTA", "bogotá" y "Bogota" comparten
entrada y el diccionario solo lista las variantes que difieren de verdad.
"""

import unicodedata


def clave(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


# Valores canónicos iguales a los del histórico, para poder cruzarlos.
CANALES: dict[str, str] = {
    "whatsapp": "WhatsApp",
    "meta ads": "Meta Ads",
    "formulario web": "Formulario Web",
}

ESTADOS: dict[str, str] = {
    "sin gestion": "sin_gestion",
    "contactado": "contactado",
    "cotizacion enviada": "cotizacion_enviada",
    "en proceso": "en_proceso",
    "no contesta": "no_contesta",
    "descartado": "descartado",
}

CIUDADES: dict[str, str] = {
    "bogota": "Bogotá",
    "bogota dc": "Bogotá",
    "bogota d.c.": "Bogotá",
    "medellin": "Medellín",
    "bello": "Bello",
    "itagui": "Itagüí",
    "rionegro": "Rionegro",
    "rio negro": "Rionegro",
    "barranquilla": "Barranquilla",
    "b/quilla": "Barranquilla",
    "soledad": "Soledad",
    "cartagena": "Cartagena",
    "cartagena de indias": "Cartagena",
    "santa marta": "Santa Marta",
    "sta marta": "Santa Marta",
    "monteria": "Montería",
    "soacha": "Soacha",
}
