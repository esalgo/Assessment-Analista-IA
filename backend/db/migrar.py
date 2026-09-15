"""Aplica en orden los .sql de db/migrations/ que aún no se han aplicado."""

from pathlib import Path

from backend.config import MIGRACIONES_DIR
from backend.db.conexion import conectar


def aplicar_migraciones(directorio: Path = MIGRACIONES_DIR) -> list[str]:
    """Devuelve los nombres de las migraciones aplicadas en esta ejecución.

    Cada archivo corre en su propia transacción junto con su registro en
    schema_migrations: o se aplica entero y queda anotado, o no pasa nada.
    """
    aplicadas: list[str] = []
    with conectar() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     text PRIMARY KEY,
                aplicada_en timestamptz NOT NULL DEFAULT now()
            )
            """
        )

        ya_aplicadas = {fila[0] for fila in conn.execute("SELECT version FROM schema_migrations")}

        for archivo in sorted(directorio.glob("*.sql")):
            if archivo.name in ya_aplicadas:
                continue
            with conn.transaction():
                conn.execute(archivo.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (archivo.name,))
            aplicadas.append(archivo.name)
    return aplicadas
