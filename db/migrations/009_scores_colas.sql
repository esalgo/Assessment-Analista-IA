-- Dos colas en lugar de un orden global.
--
-- primer_contacto: clientes que nadie ha contactado (ningún lead del grupo).
-- seguimiento:     clientes ya contactados.
-- descartado:      el estado consolidado del grupo es descartado; no entra a
--                  ninguna cola ni a la asignación del día.
--
-- Dentro de cada cola se ordena por score y se desempata por horas
-- transcurridas, lo más fresco primero. Quién se atiende hoy lo decide la
-- capacidad de cada punto de venta en `assign` (tabla asignaciones). La
-- temperatura describe la calidad del lead según sus señales, no si entra hoy.
ALTER TABLE scores ADD COLUMN cola text NOT NULL
    CHECK (cola IN ('primer_contacto', 'seguimiento', 'descartado'));
ALTER TABLE scores ADD COLUMN horas_desempate numeric(8, 2) NOT NULL;
ALTER TABLE scores ADD COLUMN estado_consolidado text NOT NULL;

-- Punto de venta que atiende al cliente: el del lead más reciente del grupo
-- fusionado, porque refleja el interés actual. Puede no ser el del canónico
-- (el canónico es el lead más antiguo).
ALTER TABLE scores ADD COLUMN punto_venta_id text NOT NULL REFERENCES puntos_venta(punto_venta_id);
