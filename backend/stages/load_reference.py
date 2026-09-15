"""Etapa load-reference: carga las tablas de referencia desde raw_*.

historico_cierres se carga aquí por comodidad, pero no es referencia: es
analítica y solo la consume el entrenamiento del score. ciudades no está
aquí: es semilla de la migración 005.

Estos archivos vienen limpios (integridad referencial verificada), así que
la transformación es un INSERT ... SELECT con casts. Todo con upsert por
clave natural, en una sola transacción. Si un cast falla, la etapa aborta:
eso significaría que el archivo cambió de forma y hay que revisarlo.
"""

import psycopg

from backend.db.conexion import conectar


class ErrorDeReferencia(Exception):
    pass


def _contar(conn: psycopg.Connection, tabla: str) -> int:
    fila = conn.execute(f"SELECT count(*) FROM {tabla}").fetchone()
    assert fila is not None
    return fila[0]


def cargar_referencia() -> dict[str, int]:
    """Devuelve el número de filas de cada tabla al terminar."""
    with conectar() as conn, conn.transaction():
        conn.execute(
            """
            INSERT INTO empresas (empresa_id)
            SELECT empresa_id FROM raw_asesores
            UNION SELECT empresa_id FROM raw_historico
            UNION SELECT empresa_id FROM raw_leads WHERE empresa_id <> ''
            ON CONFLICT DO NOTHING
            """
        )

        # Un punto de venta con dos empresas rompería el aislamiento: se aborta.
        conflictivos = conn.execute(
            """
            WITH pares AS (
                SELECT punto_venta_id, empresa_id FROM raw_asesores
                UNION SELECT punto_venta_id, empresa_id FROM raw_historico
                UNION SELECT punto_venta_id, empresa_id FROM raw_leads WHERE punto_venta_id <> ''
            )
            SELECT punto_venta_id FROM pares GROUP BY punto_venta_id HAVING count(*) > 1
            """
        ).fetchall()
        if conflictivos:
            raise ErrorDeReferencia(f"puntos de venta en más de una empresa: {conflictivos}")

        conn.execute(
            """
            INSERT INTO puntos_venta (punto_venta_id, empresa_id)
            SELECT punto_venta_id, empresa_id FROM raw_asesores
            UNION SELECT punto_venta_id, empresa_id FROM raw_historico
            UNION SELECT punto_venta_id, empresa_id FROM raw_leads WHERE punto_venta_id <> ''
            ON CONFLICT (punto_venta_id) DO NOTHING
            """
        )

        conn.execute("INSERT INTO marcas (marca) SELECT DISTINCT marca FROM raw_catalogo ON CONFLICT DO NOTHING")

        conn.execute(
            """
            INSERT INTO motos (sku, marca, linea, cilindraje, segmento, precio_lista, unidades_disponibles)
            SELECT sku, marca, linea, cilindraje::integer, segmento,
                   precio_lista::bigint, unidades_disponibles::integer
            FROM raw_catalogo
            ON CONFLICT (sku) DO UPDATE SET
                marca = EXCLUDED.marca,
                linea = EXCLUDED.linea,
                cilindraje = EXCLUDED.cilindraje,
                segmento = EXCLUDED.segmento,
                precio_lista = EXCLUDED.precio_lista,
                unidades_disponibles = EXCLUDED.unidades_disponibles
            """
        )

        # La disponibilidad se reemplaza entera: es una lista, no hay qué upsertear.
        conn.execute("DELETE FROM inventario_pv")
        conn.execute(
            """
            INSERT INTO inventario_pv (sku, punto_venta_id)
            SELECT sku, unnest(string_to_array(puntos_venta_disponibles, '|'))
            FROM raw_catalogo
            """
        )

        conn.execute(
            """
            INSERT INTO asesores (asesor_id, nombre, punto_venta_id, empresa_id,
                                  capacidad_diaria_leads, activo, fecha_ingreso)
            SELECT asesor_id, nombre, punto_venta_id, empresa_id,
                   capacidad_diaria_leads::integer, activo = 'SI', fecha_ingreso::date
            FROM raw_asesores
            ON CONFLICT (asesor_id) DO UPDATE SET
                nombre = EXCLUDED.nombre,
                punto_venta_id = EXCLUDED.punto_venta_id,
                empresa_id = EXCLUDED.empresa_id,
                capacidad_diaria_leads = EXCLUDED.capacidad_diaria_leads,
                activo = EXCLUDED.activo,
                fecha_ingreso = EXCLUDED.fecha_ingreso
            """
        )

        conn.execute(
            """
            INSERT INTO historico_cierres (lead_id, fecha_registro, canal, empresa_id, punto_venta_id,
                modelo_cotizado, sku, precio_lista, horas_al_primer_contacto, numero_contactos,
                manifesto_cuota_inicial, forma_pago, pidio_cita, desenlace)
            SELECT h.lead_id, h.fecha_registro::date, h.canal, h.empresa_id, h.punto_venta_id,
                   h.modelo_cotizado, m.sku, h.precio_lista::bigint,
                   nullif(h.horas_al_primer_contacto, '')::numeric, h.numero_contactos::integer,
                   h.manifesto_cuota_inicial, h.forma_pago_declarada, h.pidio_cita, h.desenlace
            FROM raw_historico h
            LEFT JOIN motos m ON m.marca || ' ' || m.linea = h.modelo_cotizado
            ON CONFLICT (lead_id) DO UPDATE SET
                fecha_registro = EXCLUDED.fecha_registro,
                canal = EXCLUDED.canal,
                empresa_id = EXCLUDED.empresa_id,
                punto_venta_id = EXCLUDED.punto_venta_id,
                modelo_cotizado = EXCLUDED.modelo_cotizado,
                sku = EXCLUDED.sku,
                precio_lista = EXCLUDED.precio_lista,
                horas_al_primer_contacto = EXCLUDED.horas_al_primer_contacto,
                numero_contactos = EXCLUDED.numero_contactos,
                manifesto_cuota_inicial = EXCLUDED.manifesto_cuota_inicial,
                forma_pago = EXCLUDED.forma_pago,
                pidio_cita = EXCLUDED.pidio_cita,
                desenlace = EXCLUDED.desenlace
            """
        )

        resumen = {
            tabla: _contar(conn, tabla)
            for tabla in ("empresas", "puntos_venta", "marcas", "motos",
                          "inventario_pv", "asesores", "historico_cierres")
        }
        fila = conn.execute("SELECT count(*) FROM historico_cierres WHERE sku IS NULL").fetchone()
        assert fila is not None
        resumen["historico_sin_sku"] = fila[0]
    return resumen
