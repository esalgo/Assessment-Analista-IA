-- Tablas de referencia. Salvo asesores (RLS en 004), no llevan RLS:
-- son catálogo compartido o analítica.

CREATE TABLE empresas (
    empresa_id text PRIMARY KEY
);

CREATE TABLE puntos_venta (
    punto_venta_id text PRIMARY KEY,
    empresa_id     text NOT NULL REFERENCES empresas(empresa_id)
);

CREATE TABLE ciudades (
    nombre text PRIMARY KEY
);

CREATE TABLE marcas (
    marca text PRIMARY KEY
);

CREATE TABLE motos (
    sku                  text    PRIMARY KEY,
    marca                text    NOT NULL REFERENCES marcas(marca),
    linea                text    NOT NULL,
    cilindraje           integer NOT NULL,
    segmento             text    NOT NULL,
    precio_lista         bigint  NOT NULL,
    unidades_disponibles integer NOT NULL,
    UNIQUE (marca, linea)
);

-- Una fila por cada punto de venta de puntos_venta_disponibles.
CREATE TABLE inventario_pv (
    sku            text NOT NULL REFERENCES motos(sku),
    punto_venta_id text NOT NULL REFERENCES puntos_venta(punto_venta_id),
    PRIMARY KEY (sku, punto_venta_id)
);

CREATE TABLE asesores (
    asesor_id              text    PRIMARY KEY,
    nombre                 text    NOT NULL,
    punto_venta_id         text    NOT NULL REFERENCES puntos_venta(punto_venta_id),
    empresa_id             text    NOT NULL REFERENCES empresas(empresa_id),
    capacidad_diaria_leads integer NOT NULL CHECK (capacidad_diaria_leads >= 0),
    activo                 boolean NOT NULL,
    fecha_ingreso          date    NOT NULL
);

-- Sin RLS: el login busca por email antes de que exista app.empresa_id.
-- Su aislamiento se hace en el endpoint. Las contraseñas las siembra
-- `python -m backend.cli seed-usuarios` desde el .env, nunca este archivo.
CREATE TABLE usuarios (
    usuario_id    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text        UNIQUE NOT NULL,
    password_hash text        NOT NULL,
    empresa_id    text        NOT NULL REFERENCES empresas(empresa_id),
    asesor_id     text        REFERENCES asesores(asesor_id),
    rol           text        NOT NULL DEFAULT 'asesor' CHECK (rol IN ('asesor', 'gerente')),
    activo        boolean     NOT NULL DEFAULT true,
    creado_en     timestamptz NOT NULL DEFAULT now()
);

-- Los valores de canal, manifesto_cuota_inicial, forma_pago y desenlace
-- son exactamente los del archivo: la extracción IA usa los mismos para
-- poder cruzarlos con el score.
CREATE TABLE historico_cierres (
    lead_id                  text    PRIMARY KEY,
    fecha_registro           date    NOT NULL,
    canal                    text    NOT NULL CHECK (canal IN ('WhatsApp', 'Meta Ads', 'Formulario Web')),
    empresa_id               text    NOT NULL REFERENCES empresas(empresa_id),
    punto_venta_id           text    NOT NULL REFERENCES puntos_venta(punto_venta_id),
    modelo_cotizado          text    NOT NULL,
    sku                      text    REFERENCES motos(sku),
    precio_lista             bigint  NOT NULL,
    horas_al_primer_contacto numeric,
    numero_contactos         integer NOT NULL,
    manifesto_cuota_inicial  text    NOT NULL CHECK (manifesto_cuota_inicial IN ('SI', 'NO', 'NO_INFORMA')),
    forma_pago               text    NOT NULL CHECK (forma_pago IN ('contado', 'credito', 'no_informa')),
    pidio_cita               boolean NOT NULL,
    desenlace                text    NOT NULL CHECK (desenlace IN ('Cerrado', 'Perdido', 'Sin gestión'))
);
