"""Etapa assign: la lista de gestión del día, por asesor, dentro de cada punto de venta.

La capacidad es por punto de venta, no global: un asesor solo trabaja leads
de su punto de venta. Por cada punto de venta:

1. Capacidad = suma de capacidad_diaria_leads de sus asesores activos.
2. Reparto entre colas, derivado del represamiento:
   primer contacto = ⌈pendientes / DIAS_ABSORBER_REPRESAMIENTO⌉ (con tope en
   la capacidad); seguimiento = el resto. Esa proporción se respeta mientras
   ambas colas tengan clientes: si una no alcanza a llenar su parte, lo que
   sobra pasa a la otra dentro del mismo punto de venta. El objetivo de días
   es un mínimo, no un techo.
3. Se toman los primeros clientes de cada cola, en el orden de score (score
   descendente, lo más fresco primero).
4. Se reparten entre asesores en proporción a su capacidad, con la misma
   proporción entre colas para todos. No hay asesores dedicados: asesores.csv
   no trae nada que distinga roles, y suponerlos sería decidir en silencio.

Además reporta los puntos de venta donde la demanda supera la capacidad.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from backend.config import dias_absorber_represamiento
from backend.db.conexion import conectar
from backend.stages.score import COLA_PRIMER_CONTACTO, COLA_SEGUIMIENTO, clave_de_orden, fecha_referencia


def capacidades_por_cola(capacidad: int, pendientes: int, dias_absorber: int) -> dict[str, int]:
    """Primer contacto recibe lo necesario para vaciar los pendientes en
    `dias_absorber` días; seguimiento, el resto. Derivado, no un porcentaje."""
    primer_contacto = min(capacidad, math.ceil(pendientes / dias_absorber))
    return {COLA_PRIMER_CONTACTO: primer_contacto, COLA_SEGUIMIENTO: capacidad - primer_contacto}


def trasladar_sobrante(objetivo: dict[str, int], clientes: dict[str, int]) -> dict[str, int]:
    """Cuántos clientes de cada cola se atienden hoy en un punto de venta.

    Parte del objetivo (la proporción entre colas) y lo recorta a los clientes
    que hay. Si una cola no alcanza a llenar su parte, lo que sobra pasa a la
    otra, en cualquier sentido, hasta agotar sus clientes. La capacidad total
    del punto de venta nunca se supera: solo se mueve lo que sobra."""
    atendidos = {cola: min(objetivo[cola], clientes[cola]) for cola in objetivo}
    sobrante = sum(objetivo.values()) - sum(atendidos.values())
    # RAMA INALCANZABLE con la fórmula actual: el traslado de primer_contacto
    # hacia seguimiento nunca ocurre, porque el objetivo de primer contacto es
    # ⌈pendientes / días⌉ ≤ pendientes y esa cola nunca deja sobrante. Solo se
    # ejecuta el sentido seguimiento → primer_contacto. El bucle es simétrico a
    # propósito, y test_el_sobrante_pasa_en_ambos_sentidos_sin_superar_la_capacidad
    # prueba el otro sentido llamando a la función directamente.
    for cola in objetivo:
        extra = min(sobrante, clientes[cola] - atendidos[cola])
        atendidos[cola] += extra
        sobrante -= extra
    return atendidos


def cuotas_proporcionales(total: int, pesos: dict[str, int]) -> dict[str, int]:
    """Reparte `total` en proporción a `pesos` con enteros que suman exactamente
    `total` (método del resto mayor). Empates en el resto: por id, para que sea determinista."""
    suma = sum(pesos.values())
    if total == 0 or suma == 0:
        return {clave: 0 for clave in pesos}
    exactas = {clave: total * peso / suma for clave, peso in pesos.items()}
    cuotas = {clave: math.floor(valor) for clave, valor in exactas.items()}
    faltan = total - sum(cuotas.values())
    por_resto = sorted(pesos, key=lambda clave: (-(exactas[clave] - cuotas[clave]), clave))
    for clave in por_resto[:faltan]:
        cuotas[clave] += 1
    return cuotas


def repartir(leads_ordenados: list[str], cuotas: dict[str, int]) -> list[tuple[str, str, int]]:
    """(lead_id, asesor_id, orden). Cada lead, en orden de prioridad, va al
    asesor con más cuota libre en proporción a la suya: así los mejores leads
    no se concentran en un solo asesor."""
    libres = dict(cuotas)
    asignados: dict[str, int] = defaultdict(int)
    resultado = []
    for lead_id in leads_ordenados:
        candidatos = [a for a in cuotas if libres[a] > 0]
        if not candidatos:
            break
        asesor = min(candidatos, key=lambda a: (-libres[a] / cuotas[a], a))
        libres[asesor] -= 1
        asignados[asesor] += 1
        resultado.append((lead_id, asesor, asignados[asesor]))
    return resultado


@dataclass
class ResumenPuntoVenta:
    punto_venta_id: str
    asesores_activos: int
    capacidad: int
    pendientes: int
    seguimiento: int
    capacidad_por_cola: dict[str, int]
    asignados_por_cola: dict[str, int]
    alertas: list[str] = field(default_factory=list)

    @property
    def plazas_libres(self) -> int:
        """Solo quedan plazas libres cuando el punto de venta no tiene más clientes activos."""
        return self.capacidad - sum(self.asignados_por_cola.values())

    @property
    def dias_de_cartera(self) -> float:
        """Días que tomaría atender a todos los clientes activos con esta capacidad."""
        return (self.pendientes + self.seguimiento) / self.capacidad if self.capacidad else math.inf


def asignar() -> tuple[list[ResumenPuntoVenta], int]:
    dias = dias_absorber_represamiento()
    with conectar() as conn:
        fecha = fecha_referencia(conn).date()
        asesores = conn.execute(
            """
            SELECT asesor_id, punto_venta_id, capacidad_diaria_leads
            FROM asesores WHERE activo ORDER BY asesor_id
            """
        ).fetchall()
        clientes = conn.execute(
            """
            SELECT lead_id, punto_venta_id, empresa_id, cola, score, horas_desempate
            FROM scores
            WHERE cola IN (%s, %s)
            """,
            (COLA_PRIMER_CONTACTO, COLA_SEGUIMIENTO),
        ).fetchall()

        capacidad_asesor: dict[str, dict[str, int]] = defaultdict(dict)
        for asesor_id, punto_venta_id, capacidad in asesores:
            capacidad_asesor[punto_venta_id][asesor_id] = capacidad

        por_pv_y_cola: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        empresa_de: dict[str, str] = {}
        for lead_id, punto_venta_id, empresa_id, cola, score, horas in clientes:
            por_pv_y_cola[(punto_venta_id, cola)].append((clave_de_orden(score, float(horas)), lead_id))
            empresa_de[lead_id] = empresa_id

        filas = []
        resumenes = []
        for punto_venta_id in sorted({pv for pv, _ in por_pv_y_cola} | set(capacidad_asesor)):
            capacidades = capacidad_asesor.get(punto_venta_id, {})
            capacidad = sum(capacidades.values())
            colas = {cola: [lead for _, lead in sorted(por_pv_y_cola[(punto_venta_id, cola)])]
                     for cola in (COLA_PRIMER_CONTACTO, COLA_SEGUIMIENTO)}
            por_cola = capacidades_por_cola(capacidad, len(colas[COLA_PRIMER_CONTACTO]), dias)
            atendidos = trasladar_sobrante(por_cola, {cola: len(leads) for cola, leads in colas.items()})

            # Primer contacto primero; seguimiento se reparte sobre la capacidad
            # que le queda a cada asesor, así nadie supera la suya por redondeo.
            cuotas_primer = cuotas_proporcionales(atendidos[COLA_PRIMER_CONTACTO], capacidades)
            restante = {a: capacidades[a] - cuotas_primer[a] for a in capacidades}
            cuotas_seguimiento = cuotas_proporcionales(atendidos[COLA_SEGUIMIENTO], restante)

            asignados = {}
            for cola, cuotas in ((COLA_PRIMER_CONTACTO, cuotas_primer), (COLA_SEGUIMIENTO, cuotas_seguimiento)):
                reparto = repartir(colas[cola], cuotas)
                asignados[cola] = len(reparto)
                filas.extend((fecha, lead, empresa_de[lead], asesor, orden, cola) for lead, asesor, orden in reparto)

            resumen = ResumenPuntoVenta(
                punto_venta_id=punto_venta_id,
                asesores_activos=len(capacidades),
                capacidad=capacidad,
                pendientes=len(colas[COLA_PRIMER_CONTACTO]),
                seguimiento=len(colas[COLA_SEGUIMIENTO]),
                capacidad_por_cola=por_cola,
                asignados_por_cola=asignados,
            )
            if math.ceil(resumen.pendientes / dias) > capacidad:
                resumen.alertas.append(f"no alcanza a absorber los pendientes en {dias} días")
            if resumen.pendientes + resumen.seguimiento > capacidad * dias:
                resumen.alertas.append(f"la cartera activa tarda {resumen.dias_de_cartera:.1f} días en atenderse")
            resumenes.append(resumen)

        with conn.transaction():
            conn.execute("DELETE FROM asignaciones WHERE fecha = %s", (fecha,))
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO asignaciones (fecha, lead_id, empresa_id, asesor_id, orden, cola)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    filas,
                )
    return resumenes, dias
