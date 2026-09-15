-- Capa raw: los archivos fuente tal cual llegan, todo como texto.
-- No se valida ni se limpia nada aquí. La limpieza ocurre en etapas
-- posteriores leyendo estas tablas, nunca los archivos.

-- Un lote por carga de archivo. Si el sha256 del archivo coincide con
-- el último lote, ingest no vuelve a cargarlo.
CREATE TABLE ingest_lotes (
    lote_id      bigserial PRIMARY KEY,
    archivo      text        NOT NULL,
    source_hash  text        NOT NULL,
    filas        integer     NOT NULL,
    cargado_en   timestamptz NOT NULL DEFAULT now()
);

-- fila_num es la posición en el archivo (1 = primera fila de datos).
-- No hay clave natural a propósito: las copias byte a byte de
-- LD-00011 y LD-00251 deben quedar aquí para detectarlas en normalize.
CREATE TABLE raw_leads (
    lote_id               bigint  NOT NULL REFERENCES ingest_lotes(lote_id),
    fila_num              integer NOT NULL,
    lead_id               text,
    fecha_registro        text,
    canal                 text,
    empresa_id            text,
    punto_venta_id        text,
    nombre_cliente        text,
    telefono              text,
    email                 text,
    ciudad                text,
    modelo_interes_texto  text,
    estado_gestion        text,
    fecha_primer_contacto text,
    campania              text,
    PRIMARY KEY (lote_id, fila_num)
);

-- Cada conversación se guarda como el objeto JSON completo del archivo.
CREATE TABLE raw_conversaciones (
    lote_id   bigint  NOT NULL REFERENCES ingest_lotes(lote_id),
    fila_num  integer NOT NULL,
    payload   jsonb   NOT NULL,
    PRIMARY KEY (lote_id, fila_num)
);

CREATE TABLE raw_catalogo (
    lote_id                  bigint  NOT NULL REFERENCES ingest_lotes(lote_id),
    fila_num                 integer NOT NULL,
    sku                      text,
    marca                    text,
    linea                    text,
    cilindraje               text,
    segmento                 text,
    precio_lista             text,
    puntos_venta_disponibles text,
    unidades_disponibles     text,
    PRIMARY KEY (lote_id, fila_num)
);

CREATE TABLE raw_asesores (
    lote_id                bigint  NOT NULL REFERENCES ingest_lotes(lote_id),
    fila_num               integer NOT NULL,
    asesor_id              text,
    nombre                 text,
    punto_venta_id         text,
    empresa_id             text,
    capacidad_diaria_leads text,
    activo                 text,
    fecha_ingreso          text,
    PRIMARY KEY (lote_id, fila_num)
);

CREATE TABLE raw_historico (
    lote_id                  bigint  NOT NULL REFERENCES ingest_lotes(lote_id),
    fila_num                 integer NOT NULL,
    lead_id                  text,
    fecha_registro           text,
    canal                    text,
    empresa_id               text,
    punto_venta_id           text,
    modelo_cotizado          text,
    precio_lista             text,
    horas_al_primer_contacto text,
    numero_contactos         text,
    manifesto_cuota_inicial  text,
    forma_pago_declarada     text,
    pidio_cita               text,
    desenlace                text,
    PRIMARY KEY (lote_id, fila_num)
);
