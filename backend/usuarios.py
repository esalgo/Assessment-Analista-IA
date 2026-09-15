"""Usuarios de demo para el login.

Uno por asesor activo (rol asesor, ve su propia cola) y un gerente por
empresa (ve la cola de cualquier asesor de su empresa). Las contraseñas
salen de SEED_PASSWORD_ASESOR y SEED_PASSWORD_GERENTE: nunca de un archivo
commiteado. Emails: <asesor_id>@DOMINIO_DEMO y gerente.<empresa_id>@DOMINIO_DEMO.
"""

import os
from collections import Counter

from backend.api.auth import hashear
from backend.db.conexion import conectar

# Un solo lugar donde vive el dominio de los correos de demo: los tests y la
# documentación lo leen de aquí. Con el valor repetido en cada archivo, cambiarlo
# rompe el login de los tests sin que nada lo avise.
DOMINIO_DEMO = "example.com"


def sembrar_usuarios() -> Counter:
    clave_asesor = os.environ["SEED_PASSWORD_ASESOR"]
    clave_gerente = os.environ["SEED_PASSWORD_GERENTE"]
    for clave in (clave_asesor, clave_gerente):
        if len(clave.encode("utf-8")) > 72:
            raise ValueError("bcrypt no admite contraseñas de más de 72 bytes")

    resumen: Counter = Counter()
    with conectar() as conn, conn.transaction():
        usuarios = [
            (f"{asesor_id.lower()}@{DOMINIO_DEMO}", empresa_id, asesor_id, "asesor", clave_asesor)
            for asesor_id, empresa_id in conn.execute(
                "SELECT asesor_id, empresa_id FROM asesores WHERE activo ORDER BY asesor_id"
            )
        ] + [
            (f"gerente.{empresa_id.lower()}@{DOMINIO_DEMO}", empresa_id, None, "gerente", clave_gerente)
            for (empresa_id,) in conn.execute("SELECT empresa_id FROM empresas ORDER BY empresa_id")
        ]
        for email, empresa_id, asesor_id, rol, clave in usuarios:
            conn.execute(
                """
                INSERT INTO usuarios (email, password_hash, empresa_id, asesor_id, rol, activo)
                VALUES (%s, %s, %s, %s, %s, true)
                ON CONFLICT (email) DO UPDATE SET
                    password_hash = EXCLUDED.password_hash,
                    empresa_id = EXCLUDED.empresa_id,
                    asesor_id = EXCLUDED.asesor_id,
                    rol = EXCLUDED.rol,
                    activo = true
                """,
                (email, hashear(clave), empresa_id, asesor_id, rol),
            )
            resumen[rol] += 1
    return resumen
