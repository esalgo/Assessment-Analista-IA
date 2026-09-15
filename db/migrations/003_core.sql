-- Capa core: datos limpios que produce el pipeline.
-- Toda tabla operacional lleva empresa_id para que RLS (004) la filtre.

-- Identidad deduplicada. La clave incluye empresa_id: un mismo teléfono
-- en dos comercializadoras son dos clientes distintos (requisito 8).
CREATE TABLE clientes (
    cliente_id           bigserial PRIMARY KEY,
    empresa_id           text NOT NULL REFERENCES empresas(empresa_id),
    telefono_normalizado text NOT NULL,
    nombre               text NOT NULL,
    email                text,
    UNIQUE (empresa_id, telefono_normalizado)
);

-- Todos los leads válidos quedan aquí, también los absorbidos por el
-- dedupe: estos apuntan a su canónico en lead_canonico_id y guardan en
-- motivo_fusion la regla que disparó y su confianza, por ejemplo
-- {"regla": "mismo_telefono_empresa", "confianza": 1.0}. La lista del
-- día trabaja solo con los canónicos (lead_canonico_id IS NULL).
--
-- Los enums limpios van en snake_case (sin_gestion, cotizacion_enviada,
-- alta/media/baja): identificadores sin tildes, espacios ni mayúsculas
-- en la base. La forma de mostrarlos es asunto del frontend. canal es la
-- excepción: usa los valores del histórico para cruzarse con él.
CREATE TABLE leads (
    lead_id                     text        PRIMARY KEY,
    empresa_id                  text        NOT NULL REFERENCES empresas(empresa_id),
    punto_venta_id              text        NOT NULL REFERENCES puntos_venta(punto_venta_id),
    cliente_id                  bigint      REFERENCES clientes(cliente_id),
    lead_canonico_id            text        REFERENCES leads(lead_id),
    motivo_fusion               jsonb,
    canales                     text[]      NOT NULL DEFAULT '{}',
    fecha_registro              timestamptz NOT NULL,
    canal                       text        NOT NULL CHECK (canal IN ('WhatsApp', 'Meta Ads', 'Formulario Web')),
    nombre_cliente              text        NOT NULL,
    telefono_normalizado        text,
    telefono_valido             boolean     NOT NULL,
    email                       text,
    ciudad                      text        REFERENCES ciudades(nombre),
    modelo_interes_texto        text,
    sku                         text        REFERENCES motos(sku),
    marca                       text        REFERENCES marcas(marca),
    match_method                text        CHECK (match_method IN ('exacto', 'fuzzy', 'solo_marca', 'sin_match')),
    match_confidence            numeric(5, 2),
    estado_gestion              text        NOT NULL CHECK (estado_gestion IN (
                                    'sin_gestion', 'contactado', 'cotizacion_enviada',
                                    'en_proceso', 'no_contesta', 'descartado')),
    fecha_primer_contacto       timestamptz,
    fecha_contacto_ambigua      boolean     NOT NULL DEFAULT false,
    estado_sin_contacto         boolean     NOT NULL DEFAULT false,
    campania                    text,
    CHECK ((lead_canonico_id IS NULL) = (motivo_fusion IS NULL))
);

CREATE INDEX leads_empresa_idx ON leads (empresa_id);

-- Registro de todo lo que se aparta del pipeline: el lead de prueba,
-- las filas duplicadas, las conversaciones huérfanas. Nada se borra en
-- silencio. La clave única hace que reejecutar no duplique entradas.
CREATE TABLE cuarentena (
    cuarentena_id bigserial   PRIMARY KEY,
    etapa         text        NOT NULL,
    origen        text        NOT NULL,
    clave         text        NOT NULL,
    motivo        text        NOT NULL,
    payload       jsonb,
    registrado_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (etapa, origen, clave, motivo)
);

CREATE TABLE conversaciones (
    conversacion_id text        PRIMARY KEY,
    lead_id         text        NOT NULL REFERENCES leads(lead_id),
    empresa_id      text        NOT NULL REFERENCES empresas(empresa_id),
    canal           text        NOT NULL,
    fecha_inicio    timestamptz NOT NULL
);

CREATE TABLE mensajes (
    conversacion_id text    NOT NULL REFERENCES conversaciones(conversacion_id),
    orden           integer NOT NULL,
    empresa_id      text    NOT NULL REFERENCES empresas(empresa_id),
    emisor          text    NOT NULL CHECK (emisor IN ('cliente', 'asesor')),
    hora            time    NOT NULL,
    texto           text    NOT NULL,
    PRIMARY KEY (conversacion_id, orden)
);

-- conversacion_hash = sha256(conversaciones concatenadas + prompt_version).
-- Si ya existe la fila para ese lead y hash, extract-ai no llama a la API.
CREATE TABLE extracciones_ia (
    lead_id           text        NOT NULL REFERENCES leads(lead_id),
    conversacion_hash text        NOT NULL,
    empresa_id        text        NOT NULL REFERENCES empresas(empresa_id),
    prompt_version    text        NOT NULL,
    modelo_llm        text        NOT NULL,
    payload           jsonb       NOT NULL,
    creado_en         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (lead_id, conversacion_hash)
);

CREATE TABLE scores (
    lead_id                  text        PRIMARY KEY REFERENCES leads(lead_id),
    empresa_id               text        NOT NULL REFERENCES empresas(empresa_id),
    score                    integer     NOT NULL,
    temperatura              text        NOT NULL CHECK (temperatura IN ('alta', 'media', 'baja')),
    factores                 jsonb       NOT NULL,
    sin_senal_conversacional boolean     NOT NULL,
    score_version            text        NOT NULL,
    calculado_en             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE asignaciones (
    fecha      date    NOT NULL,
    lead_id    text    NOT NULL REFERENCES leads(lead_id),
    empresa_id text    NOT NULL REFERENCES empresas(empresa_id),
    asesor_id  text    NOT NULL REFERENCES asesores(asesor_id),
    orden      integer NOT NULL,
    PRIMARY KEY (fecha, lead_id)
);
