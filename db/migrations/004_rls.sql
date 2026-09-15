-- Aislamiento multi-tenant. Todo el control de acceso por empresa está
-- en este archivo.
--
-- Por qué hace falta un rol aparte: la imagen de Postgres crea
-- POSTGRES_USER como superusuario, y un superusuario se salta RLS
-- siempre, con o sin FORCE. La API se conecta con ese usuario, así que
-- en cada request hace, dentro de la transacción:
--
--   SELECT set_config('app.empresa_id', <claim del JWT>, true);
--   SET LOCAL ROLE app_tenant;
--
-- app_tenant no es superusuario ni dueño de las tablas, así que las
-- políticas se aplican. Ambos valores se deshacen al cerrar la
-- transacción y no se filtran a otro request de la pool.
--
-- El pipeline batch (CLI) sigue conectado como superusuario a propósito:
-- procesa las tres empresas a la vez.

-- CREATE ROLE es global al servidor, no a la base: si ya existe (por
-- ejemplo, una base de tests en el mismo servidor) no se vuelve a crear.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_tenant') THEN
        CREATE ROLE app_tenant NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO app_tenant;

GRANT SELECT ON empresas, puntos_venta, ciudades, marcas, motos,
    inventario_pv, historico_cierres TO app_tenant;

GRANT SELECT, INSERT, UPDATE, DELETE ON clientes, leads, conversaciones,
    mensajes, extracciones_ia, scores, asignaciones, asesores TO app_tenant;

-- FORCE además de ENABLE: sin FORCE, el dueño de la tabla queda exento
-- de sus políticas sin ningún aviso.
ALTER TABLE clientes        ENABLE ROW LEVEL SECURITY;
ALTER TABLE clientes        FORCE  ROW LEVEL SECURITY;
ALTER TABLE leads           ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads           FORCE  ROW LEVEL SECURITY;
ALTER TABLE conversaciones  ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversaciones  FORCE  ROW LEVEL SECURITY;
ALTER TABLE mensajes        ENABLE ROW LEVEL SECURITY;
ALTER TABLE mensajes        FORCE  ROW LEVEL SECURITY;
ALTER TABLE extracciones_ia ENABLE ROW LEVEL SECURITY;
ALTER TABLE extracciones_ia FORCE  ROW LEVEL SECURITY;
ALTER TABLE scores          ENABLE ROW LEVEL SECURITY;
ALTER TABLE scores          FORCE  ROW LEVEL SECURITY;
ALTER TABLE asignaciones    ENABLE ROW LEVEL SECURITY;
ALTER TABLE asignaciones    FORCE  ROW LEVEL SECURITY;
ALTER TABLE asesores        ENABLE ROW LEVEL SECURITY;
ALTER TABLE asesores        FORCE  ROW LEVEL SECURITY;

-- Sin app.empresa_id fijado, current_setting devuelve NULL y la
-- comparación nunca es verdadera: cero filas, no todas.
CREATE POLICY aisla_empresa ON clientes
    USING (empresa_id = current_setting('app.empresa_id', true));
CREATE POLICY aisla_empresa ON leads
    USING (empresa_id = current_setting('app.empresa_id', true));
CREATE POLICY aisla_empresa ON conversaciones
    USING (empresa_id = current_setting('app.empresa_id', true));
CREATE POLICY aisla_empresa ON mensajes
    USING (empresa_id = current_setting('app.empresa_id', true));
CREATE POLICY aisla_empresa ON extracciones_ia
    USING (empresa_id = current_setting('app.empresa_id', true));
CREATE POLICY aisla_empresa ON scores
    USING (empresa_id = current_setting('app.empresa_id', true));
CREATE POLICY aisla_empresa ON asignaciones
    USING (empresa_id = current_setting('app.empresa_id', true));
CREATE POLICY aisla_empresa ON asesores
    USING (empresa_id = current_setting('app.empresa_id', true));
