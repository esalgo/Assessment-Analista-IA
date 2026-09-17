# Arquitectura

Tres vistas del mismo sistema: **qué le pasa a un lead** (flujo de datos), **cómo están guardados** (modelo entidad-relación) y **dónde corre todo** (despliegue). Los diagramas son Mermaid, así que se versionan como texto y GitHub los dibuja solo.

**Los mismos diagramas en SVG**, para verlos con zoom o llevarlos a una presentación: [flujo de datos](diagramas/flujo-datos.svg) · [MER: el camino de un lead](diagramas/mer-camino-del-lead.svg) · [MER: referencia](diagramas/mer-referencia.svg) · [despliegue](diagramas/despliegue.svg). Se abren en el navegador y escalan sin perder nitidez. Para regenerarlos después de cambiar un diagrama, pega el bloque en [mermaid.live](https://mermaid.live) y exporta a SVG, o guárdalo en un `.mmd` y corre `docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/data" minlag/mermaid-cli:11.4.2 -i diagrama.mmd -o diagrama.svg -b white` (así se generó `mer-camino-del-lead.svg`). Mermaid exporta con fondo transparente, y las líneas oscuras desaparecen en visores con fondo oscuro: cada SVG lleva como primer elemento un `<rect id="fondo-blanco">` del tamaño del `viewBox`, que hay que volver a agregar tras exportar.

## 1. Flujo de datos

De los cinco archivos de entrada a la lista del día de un asesor. Cada etapa es un subcomando del CLI, corre sola y es idempotente.

```mermaid
flowchart TD
    subgraph entrada["data/input (montado solo lectura)"]
        A1["leads.csv<br/>1.503 filas"]
        A2["conversaciones.json<br/>677"]
        A3["historico_cierres.csv<br/>2.200"]
        A4["catalogo_motos.csv<br/>24"]
        A5["asesores.csv<br/>42"]
    end

    A1 & A2 & A3 & A4 & A5 --> E1

    E1["ingest<br/>sin limpiar nada"] --> R[("raw_*<br/>todo texto")]
    R --> E2["load-reference<br/>catálogos e histórico"]
    R --> E3["normalize<br/>teléfonos, 4 formatos de fecha,<br/>ciudades, canal, estado, nombres"]
    E2 --> E3
    E3 --> Q[("cuarentena<br/>LD-01501 + 12 conversaciones huérfanas")]
    E3 --> E4["resolve-models<br/>190 textos → 24 SKUs<br/>exacto → parcial → fuzzy"]
    E4 --> E5["dedupe<br/>identidad (empresa_id, teléfono)<br/>49 fusiones · 91 cruces entre empresas NO"]
    E5 --> E6["extract-ai<br/>gpt-4o-mini, JSON Schema estricto<br/>640 leads · caché por hash"]
    E6 -.->|"solo si el hash es nuevo"| LLM(["OpenAI"])
    E6 --> E7["score<br/>pesos del histórico + urgencia<br/>dos colas · temperatura"]
    H[("historico_cierres<br/>2.200 cierres")] -->|"pesos de la regresión"| E7
    E2 --> H
    E7 --> E8["assign<br/>capacidad por punto de venta<br/>688 de 694 plazas"]
    E8 --> S[("asignaciones<br/>la cola de hoy")]
    S --> API["GET /leads/hoy"]
    API --> T["Tablero del asesor"]

    classDef etapa fill:#e8efff,stroke:#2459d6,color:#1d2330
    classDef tabla fill:#fff4d6,stroke:#9a6700,color:#1d2330
    class E1,E2,E3,E4,E5,E6,E7,E8 etapa
    class R,Q,H,S tabla
```

**Lo que el diagrama deja ver:**

- `load-reference` es una etapa propia porque `leads` tiene llaves foráneas a `puntos_venta`, `motos` y `ciudades`: la dependencia es dura, no un orden de conveniencia.
- La llamada a OpenAI es la **única** salida a internet del pipeline, y solo ocurre cuando el hash de la conversación es nuevo.
- `historico_cierres` no se cruza con los leads del día: solo alimenta los pesos del score.
- Nada se borra: lo inválido va a `cuarentena` con un motivo específico.

## 2. Modelo entidad-relación

24 tablas. En un solo diagrama quedan ilegibles, así que van en dos: **el camino de un lead** y **los catálogos que lo sostienen**. Solo se muestran las columnas que explican una decisión, más `empresa_id` en todas las tablas que la llevan, porque es la columna del aislamiento; el esquema completo está en `db/migrations/`.

**La marca `RLS`** señala las ocho tablas con Row Level Security (`clientes`, `leads`, `conversaciones`, `mensajes`, `extracciones_ia`, `scores`, `asignaciones`, `asesores`). Todas llevan `empresa_id`, y en ellas una consulta de la API solo ve las filas de la empresa del token.

### 2.1 El camino de un lead

```mermaid
erDiagram
    clientes ||--o{ leads : agrupa
    leads ||--o{ leads : absorbe
    leads ||--o{ conversaciones : recibe
    conversaciones ||--o{ mensajes : contiene
    leads ||--o| extracciones_ia : extrae
    leads ||--o| scores : puntua
    scores ||--o{ asignaciones : encola

    clientes {
        bigint cliente_id PK "RLS"
        text empresa_id FK, UK "UNIQUE (empresa_id, telefono_normalizado)"
        text telefono_normalizado UK "único por empresa, no global"
        text nombre
    }
    leads {
        text lead_id PK "RLS"
        text empresa_id FK "la filtra RLS"
        bigint cliente_id FK
        text lead_canonico_id FK "si fue absorbido"
        jsonb motivo_fusion "regla y confianza"
        text canales "acumulados al fusionar"
        timestamptz fecha_registro
        text fecha_registro_metodo "inequívoco | ventana | coherencia"
        text sku FK
        text match_method "exacto | parcial | fuzzy | solo_marca"
        text estado_gestion
        timestamptz fecha_primer_contacto
    }
    conversaciones {
        text conversacion_id PK "RLS"
        text empresa_id FK
        text lead_id FK
        text canal "siempre WhatsApp"
    }
    mensajes {
        text conversacion_id PK "RLS"
        int orden PK
        text empresa_id FK
        text emisor "cliente | asesor"
        text texto
    }
    extracciones_ia {
        text lead_id PK "RLS"
        text conversacion_hash PK "clave de caché"
        text empresa_id FK
        text prompt_version
        jsonb payload "salida del LLM, nunca corregida"
    }
    scores {
        text lead_id PK "RLS: un cliente = su lead canónico"
        text empresa_id FK
        int score "0-100, 50 = tasa base"
        text temperatura "alta | media | baja"
        jsonb factores "puntos por variable + reglas derivadas"
        text cola "primer_contacto | seguimiento | descartado"
        text estado_consolidado "el más avanzado del grupo"
        text punto_venta_id FK "el del lead más reciente"
    }
    asignaciones {
        date fecha PK "RLS"
        text lead_id PK
        text empresa_id FK
        text asesor_id FK
        int orden
        text cola
    }
```

- **`clientes` tiene `UNIQUE (empresa_id, telefono_normalizado)`**, no `UNIQUE (telefono)`. El mismo número en dos comercializadoras son dos personas distintas para el sistema: el aislamiento vive en la restricción, no en el código.
- **`leads` apunta a sí misma.** Al fusionar, el lead absorbido no se borra: queda con `lead_canonico_id` y el `motivo_fusion` que justifica la decisión.
- **`scores` guarda una fila por cliente**, la del lead canónico, con el estado consolidado de todo el grupo. Si leyera solo el canónico, un cliente ya cotizado por un canal aparecería como `sin_gestion` por el otro.

### 2.2 Catálogos, asesores y acceso

```mermaid
erDiagram
    empresas ||--o{ puntos_venta : tiene
    empresas ||--o{ asesores : emplea
    empresas ||--o{ usuarios : autentica
    empresas ||--o{ clientes : posee
    puntos_venta ||--o{ asesores : ubica
    puntos_venta ||--o{ inventario_pv : almacena
    marcas ||--o{ motos : agrupa
    motos ||--o{ inventario_pv : disponible_en
    motos ||--o{ leads : interesa
    ciudades ||--o{ leads : ubica
    asesores ||--o{ asignaciones : atiende
    usuarios }o--|| asesores : es

    empresas {
        text empresa_id PK "3 comercializadoras"
    }
    puntos_venta {
        text punto_venta_id PK "15"
        text empresa_id FK
    }
    asesores {
        text asesor_id PK "RLS · 42, 40 activos"
        text punto_venta_id FK
        int capacidad_diaria_leads "694 en total"
        bool activo
    }
    usuarios {
        uuid usuario_id PK "sin RLS: el login es previo"
        text email UK
        text password_hash "bcrypt"
        text asesor_id FK "nulo si es gerente"
        text rol "asesor | gerente"
    }
    motos {
        text sku PK "24"
        text marca FK
        text linea
        text segmento
        bigint precio_lista
    }
    inventario_pv {
        text sku PK "qué moto hay en qué punto de venta"
        text punto_venta_id PK
    }
    marcas {
        text marca PK
    }
    ciudades {
        text nombre PK "37 variantes normalizadas"
    }
    leads {
        text lead_id PK "RLS"
    }
    clientes {
        bigint cliente_id PK "RLS"
    }
    asignaciones {
        date fecha PK "RLS"
    }
```

- **`usuarios` es la única tabla con `empresa_id` sin RLS.** El login ocurre antes de que exista `app.empresa_id`; con la política activa, la búsqueda por email devolvería cero filas y nadie podría entrar. Su aislamiento se hace en el endpoint.
- **`inventario_pv` tampoco lleva RLS**: es referencia compartida, y ponérsela rompería el join de disponibilidad.
- **`asesores.capacidad_diaria_leads`** es lo que hace que la asignación tenga un techo real por punto de venta, en vez de repartir a ojo.

### 2.3 Las demás tablas

No entran a los diagramas porque no tienen relaciones que explicar:

| Tabla | Para qué |
|---|---|
| `raw_leads`, `raw_conversaciones`, `raw_catalogo`, `raw_asesores`, `raw_historico` | Copia literal de cada archivo, todo texto, sin validar. Apuntan a `ingest_lotes` |
| `ingest_lotes` | Un registro por archivo cargado, con `source_hash` y número de filas |
| `cuarentena` | Filas descartadas con motivo específico, clave `(etapa, origen, clave, motivo)` |
| `historico_cierres` | Los 2.200 cierres pasados. Analítica: solo alimenta los pesos del score, nunca se cruza con los leads del día |
| `schema_migrations` | Qué migraciones se aplicaron |

## 3. Despliegue

Una sola máquina, un `docker-compose.yml` idéntico en local y en producción: solo cambia el `.env`.

```mermaid
flowchart TB
    U["Asesor / Gerente"] -->|"HTTPS 443"| CF
    CF["Cloudflare DNS<br/>nube gris: solo resuelve"] --> C

    subgraph vps["VPS · red interna de Docker"]
        C["caddy<br/>TLS automático (Let's Encrypt)<br/>sirve el Angular compilado<br/>único que publica 80 y 443"]
        A["api :8000<br/>FastAPI<br/>JWT + SET LOCAL ROLE app_tenant"]
        P[("postgres :5432<br/>RLS con FORCE<br/>volumen pg_data")]
        N["n8n :5678<br/>Schedule 6:00<br/>credencial Header Auth"]

        C -->|"/api/* (quita el prefijo)"| A
        C -->|"n8n.DOMINIO"| N
        A --> P
        N -->|"POST /pipeline/run<br/>X-Pipeline-Token"| A
    end

    A -.->|"solo en extract-ai,<br/>si el hash es nuevo"| O(["OpenAI API"])
    CLI["docker compose exec api<br/>python -m backend.cli run-all"] -.->|"plan B sin n8n"| P

    classDef publico fill:#e8efff,stroke:#2459d6,color:#1d2330
    classDef interno fill:#eef0f3,stroke:#475467,color:#1d2330
    class C publico
    class A,N interno
```

**Lo que el diagrama deja ver:**

- **Solo `caddy` publica puertos.** Postgres y n8n no son alcanzables desde internet; se hablan por nombre de servicio en la red interna de Docker.
- **n8n llama a `http://api:8000`**, no a la URL pública: el disparo diario no sale a internet ni depende del DNS.
- **La nube de Cloudflare está gris a propósito.** Con el proxy activo, el challenge de Let's Encrypt no llega a Caddy y el certificado no se emite.
- **El CLI es el plan B:** todo lo que hace n8n se puede hacer por SSH con un comando, que es el seguro contra "la URL no funciona el día de la sustentación".
- **El pipeline corre como superusuario y la API no.** El CLI escribe leads de las tres empresas a la vez; la API baja a `app_tenant` en cada request para que RLS la filtre.
