"""Reparto de la capacidad por punto de venta, sin base de datos."""

from backend.stages.assign import capacidades_por_cola, cuotas_proporcionales, repartir, trasladar_sobrante


def test_capacidad_de_primer_contacto_sale_de_los_dias_para_absorber() -> None:
    assert capacidades_por_cola(77, 24, 2) == {"primer_contacto": 12, "seguimiento": 65}
    assert capacidades_por_cola(12, 31, 2) == {"primer_contacto": 12, "seguimiento": 0}


def test_cuotas_proporcionales_suman_el_total_exacto() -> None:
    cuotas = cuotas_proporcionales(12, {"AS-001": 12, "AS-002": 25, "AS-003": 20, "AS-004": 20})
    assert sum(cuotas.values()) == 12
    assert cuotas == {"AS-001": 2, "AS-002": 4, "AS-003": 3, "AS-004": 3}
    assert cuotas_proporcionales(5, {"A": 0, "B": 0}) == {"A": 0, "B": 0}


def test_seguimiento_sobre_la_capacidad_restante_nunca_supera_la_del_asesor() -> None:
    capacidades = {"A": 20, "B": 20}
    primer = cuotas_proporcionales(13, capacidades)
    seguimiento = cuotas_proporcionales(27, {a: capacidades[a] - primer[a] for a in capacidades})
    assert all(primer[a] + seguimiento[a] <= capacidades[a] for a in capacidades)
    assert sum(primer.values()) + sum(seguimiento.values()) == 40


def test_repartir_alterna_los_mejores_leads_entre_asesores() -> None:
    reparto = repartir(["L1", "L2", "L3", "L4", "L5"], {"A": 2, "B": 2})
    assert [asesor for _, asesor, _ in reparto] == ["A", "B", "A", "B"]
    assert [orden for _, _, orden in reparto] == [1, 1, 2, 2]


def test_seguimiento_corto_cede_su_sobrante_a_los_pendientes_sin_asignar() -> None:
    # PV-001: 77 de capacidad, 24 pendientes y solo 50 en seguimiento. Sin
    # traslado, primer contacto recibía 12 y quedaban 15 plazas libres con 12
    # pendientes esperando.
    objetivo = capacidades_por_cola(77, 24, 2)
    atendidos = trasladar_sobrante(objetivo, {"primer_contacto": 24, "seguimiento": 50})
    assert atendidos == {"primer_contacto": 24, "seguimiento": 50}
    assert sum(atendidos.values()) <= 77


def test_el_sobrante_pasa_en_ambos_sentidos_sin_superar_la_capacidad() -> None:
    atendidos = trasladar_sobrante({"primer_contacto": 10, "seguimiento": 5}, {"primer_contacto": 3, "seguimiento": 20})
    assert atendidos == {"primer_contacto": 3, "seguimiento": 12}
    # Con clientes de sobra en ambas colas, se respeta la proporción.
    assert trasladar_sobrante({"primer_contacto": 12, "seguimiento": 0}, {"primer_contacto": 31, "seguimiento": 52}) == {
        "primer_contacto": 12, "seguimiento": 0,
    }


def test_con_traslado_ningun_asesor_supera_su_capacidad() -> None:
    capacidades = {"AS-001": 12, "AS-002": 25, "AS-003": 20, "AS-004": 20}
    atendidos = trasladar_sobrante(capacidades_por_cola(77, 24, 2), {"primer_contacto": 24, "seguimiento": 50})
    primer = cuotas_proporcionales(atendidos["primer_contacto"], capacidades)
    seguimiento = cuotas_proporcionales(atendidos["seguimiento"], {a: capacidades[a] - primer[a] for a in capacidades})
    assert all(primer[a] + seguimiento[a] <= capacidades[a] for a in capacidades)
    assert sum(primer.values()) == 24 and sum(seguimiento.values()) == 50
