"""Etapa resolve-models: modelo_interes_texto (190 variantes) -> SKU del catálogo (24).

Cascada, de la regla más estricta a la más permisiva. Gana la primera que decide:
1. exacto         marca + línea completas
2. exacto_linea   línea sin marca
3. solo_marca     solo la marca
4. linea_parcial  marca + inicio de una sola línea; si calza con varias -> solo_marca
5. fuzzy          fuzz.ratio >= 85 contra marca + línea
6. sin_match

Antes de comparar, el texto pasa por `normalizar_texto_modelo`. La etapa es
determinista: reejecutarla escribe exactamente lo mismo.
"""

import re
from collections import Counter
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from backend.catalogos import clave
from backend.db.conexion import conectar

UMBRAL_FUZZY = 85
# Anclado al final: "Honda Navi 2026" -> "honda navi". Un año en medio del texto no se toca.
ANIO_FINAL = re.compile(r"\s+20\d{2}\s*$")


def normalizar_texto_modelo(texto: str) -> str:
    """Minúsculas, sin tildes, espacios colapsados, A.K.T -> akt y sin año final."""
    normalizado = clave(texto).replace("a.k.t", "akt")
    return ANIO_FINAL.sub("", normalizado)


@dataclass
class Moto:
    sku: str
    marca: str
    linea: str


@dataclass
class Resolucion:
    sku: str | None
    marca: str | None
    metodo: str
    confianza: float | None
    score_segundo: float | None = None


class Catalogo:
    """Índices del catálogo por texto normalizado, construidos una sola vez."""

    def __init__(self, motos: list[Moto]) -> None:
        self.motos = motos
        self.por_marca_linea = {normalizar_texto_modelo(f"{m.marca} {m.linea}"): m for m in motos}
        self.por_linea = {normalizar_texto_modelo(m.linea): m for m in motos}
        self.marcas = {normalizar_texto_modelo(m.marca): m.marca for m in motos}


def resolver_modelo(texto: str, catalogo: Catalogo) -> Resolucion:
    normalizado = normalizar_texto_modelo(texto)

    moto = catalogo.por_marca_linea.get(normalizado)
    if moto:
        return Resolucion(moto.sku, moto.marca, "exacto", 100)

    moto = catalogo.por_linea.get(normalizado)
    if moto:
        return Resolucion(moto.sku, moto.marca, "exacto_linea", 100)

    marca = catalogo.marcas.get(normalizado)
    if marca:
        return Resolucion(None, marca, "solo_marca", 100)

    # Palabras completas, no caracteres: "honda xr" es inicio de "xr 150l"
    # pero no de "xre 300", porque "xr" y "xre" son palabras distintas.
    palabras = normalizado.split()
    marca = catalogo.marcas.get(palabras[0]) if palabras else None
    if marca and len(palabras) > 1:
        resto = palabras[1:]
        candidatas = [
            m for m in catalogo.motos
            if m.marca == marca and normalizar_texto_modelo(m.linea).split()[: len(resto)] == resto
        ]
        if len(candidatas) == 1:
            return Resolucion(candidatas[0].sku, marca, "linea_parcial", 100)
        if len(candidatas) > 1:
            return Resolucion(None, marca, "solo_marca", 100)

    mejores = process.extract(normalizado, list(catalogo.por_marca_linea), scorer=fuzz.ratio, limit=2)
    if mejores and mejores[0][1] >= UMBRAL_FUZZY:
        moto = catalogo.por_marca_linea[mejores[0][0]]
        segundo = round(mejores[1][1], 2) if len(mejores) > 1 else None
        return Resolucion(moto.sku, moto.marca, "fuzzy", round(mejores[0][1], 2), segundo)

    return Resolucion(None, None, "sin_match", None)


def resolver_modelos() -> Counter:
    resumen: Counter = Counter()
    with conectar() as conn, conn.transaction():
        catalogo = Catalogo([Moto(*fila) for fila in conn.execute("SELECT sku, marca, linea FROM motos")])
        leads = conn.execute("SELECT lead_id, modelo_interes_texto FROM leads").fetchall()

        actualizaciones = []
        for lead_id, texto in leads:
            if texto is None:
                # Sin texto no hay nada que resolver: todo queda nulo, no "sin_match".
                resumen["sin_texto"] += 1
                actualizaciones.append((None, None, None, None, None, lead_id))
                continue
            r = resolver_modelo(texto, catalogo)
            resumen[r.metodo] += 1
            actualizaciones.append((r.sku, r.marca, r.metodo, r.confianza, r.score_segundo, lead_id))

        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE leads SET sku = %s, marca = %s, match_method = %s,
                                 match_confidence = %s, match_score_segundo = %s
                WHERE lead_id = %s
                """,
                actualizaciones,
            )
    return resumen
