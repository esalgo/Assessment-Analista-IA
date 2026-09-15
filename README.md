# Priorización de leads — Motos

> README en construcción. Por ahora recoge hallazgos a medida que aparecen.

## Hallazgos de implementación

### RLS con `FORCE` no basta si la API se conecta como superusuario

La imagen oficial de Postgres crea `POSTGRES_USER` como superusuario, y un superusuario se salta RLS siempre, con o sin `FORCE ROW LEVEL SECURITY`. Con el compose tal cual, todas las consultas habrían devuelto las filas de las tres empresas sin ningún error.

Solución: `db/migrations/004_rls.sql` crea el rol `app_tenant` (`NOLOGIN NOSUPERUSER NOBYPASSRLS`, sin ser dueño de ninguna tabla). Cada request fija `app.empresa_id` y hace `SET LOCAL ROLE app_tenant` dentro de su transacción. El test `tests/test_aislamiento.py::test_superusuario_sin_cambiar_de_rol_se_salta_rls` deja documentado el problema.

### Sin `autocommit=True`, el contexto del tenant sobrevive al request

En psycopg 3, una conexión sin autocommit abre una transacción implícita con la primera consulta. Todo `with conn.transaction()` posterior deja de ser un `BEGIN` y pasa a ser un **savepoint** dentro de esa transacción. `SET LOCAL ROLE` y `set_config(..., true)` duran hasta el fin de la transacción externa, no del savepoint.

Se detectó al probar el esquema: una sesión *sin* empresa fijada devolvió las filas de la empresa del bloque anterior y `current_user` seguía siendo `app_tenant` después de salir del `with`. En una pool, el siguiente request que reutilizara esa conexión habría visto datos de otra empresa.

Solución: todas las conexiones se abren con `autocommit=True` (`backend/db/conexion.py`), de modo que cada `transaction()` es una transacción real. El test `test_contexto_del_tenant_no_sobrevive_a_la_transaccion` lo verifica.

## Tests de base de datos

Necesitan una base desechable en `TEST_DATABASE_URL`. Sin ella, se omiten:

```bash
docker run -d --rm --name pg_test -e POSTGRES_USER=leads_app \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=leads_test \
  -p 55432:5432 pgvector/pgvector:0.8.6-pg18
TEST_DATABASE_URL=postgresql://leads_app:test@localhost:55432/leads_test pytest
```
