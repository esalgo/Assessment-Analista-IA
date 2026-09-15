# CLAUDE.md

Convenciones técnicas del repositorio. Léelo completo antes de escribir código.

Este archivo vive en la raíz del repo (`project/`) y **sí se commitea**: documenta las reglas con las que se construyó el sistema. El contexto de la prueba, el cronograma y el enunciado están un nivel más arriba, en el `CLAUDE.md` del workspace.

## Qué es esto

Prueba técnica para Analista de IA en una comercializadora de motos multimarca. El pipeline convierte leads crudos (CSV + JSON) en una lista priorizada de gestión diaria por asesor, enriquecida con información extraída de conversaciones de WhatsApp mediante LLM.

Se evalúa sobre 100 puntos. Los bloques pesados: Componente de IA (20), Datos y BD (15), Automatización (15), Ingeniería de software (12), Despliegue (10).

## Stack

- Python 3.12 con `pip` + `venv` y `requirements.txt`, paquete en `backend/`, CLI con Typer
- Postgres 18 en Docker vía `pgvector/pgvector:0.8.6-pg18`, con RLS. **La extensión `vector` NO se activa**: con 24 SKUs el matching se hace con `rapidfuzz`, que es determinista y explicable. No escribas `CREATE EXTENSION vector`.
- OpenAI `gpt-4o-mini` con structured outputs — cliente con `base_url` configurable
- FastAPI — `fastapi dev` en local, `fastapi run` en producción
- Angular con **pnpm** (nunca npm ni yarn), compilado a estático y servido por Caddy
- Despliegue: VPS de Hostinger con Docker Compose, dominio en Cloudflare (DNS only), TLS automático con Caddy
- n8n Community Edition `2.38.3` autohospedado en el mismo compose, con SQLite propio (no conectado al Postgres de la app)
- n8n para orquestación (dispara webhook, **no contiene lógica**)

## Reglas duras

1. **Idempotencia.** Cada etapa se puede reejecutar sin duplicar datos ni cambiar resultados. Usa upserts con clave natural, nunca inserts ciegos.
2. **La extracción con LLM se cachea** por `sha256(conversacion + prompt_version)`. Reejecutar no debe volver a llamar a la API.
3. **Cero credenciales en el repo.** Todo por variables de entorno, con `.env.example` documentado.
4. **Los datos crudos se cargan sin limpiar** a tablas `raw_*`. La limpieza ocurre en etapas posteriores, sobre la BD, nunca sobre los archivos.
5. **Nada de LangChain, LangGraph, RAG ni frameworks de agentes.** Esto es extracción estructurada batch. Llamada directa al SDK de OpenAI.
6. **Todo error de dato se registra, no se silencia.** Cada etapa emite un resumen con conteos de filas procesadas, corregidas y en cuarentena.
7. **Código que yo no pueda explicar no entra al repo.** Prefiere simple y legible sobre clever. Sin metaprogramación, sin abstracciones prematuras.

## Aislamiento multi-tenant (requisito crítico)

Tres comercializadoras comparten el CRM y **ninguna puede ver clientes de otra**.

### Regla base

**`empresa_id` nunca es parámetro de un endpoint.** Sale del token firmado o no sale. Un selector de empresa en el frontend es un filtro, no control de acceso: cualquiera cambia el valor y ve datos ajenos.

### En la base de datos

Para cada tabla operacional (`clientes`, `leads`, `conversaciones`, `mensajes`, `extracciones_ia`, `scores`, `asignaciones`, `asesores`):

```sql
ALTER TABLE <tabla> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <tabla> FORCE  ROW LEVEL SECURITY;

CREATE POLICY aisla_empresa ON <tabla>
  USING (empresa_id = current_setting('app.empresa_id', true));
```

**El `FORCE` no es opcional.** El dueño de una tabla está exento de sus propias políticas por defecto, y la API se conecta con el mismo usuario que creó el esquema. Sin `FORCE`, las políticas se ignoran en silencio: las consultas devuelven todo, no hay ningún error y el aislamiento es puro teatro. Es el fallo más caro posible en este proyecto.

Las tablas que **no** llevan RLS: `usuarios` (ver abajo, es un caso especial), `motos`, `marcas`, `inventario_pv`, `ciudades`, `empresas`, `puntos_venta`, `historico_cierres`, `score_pesos` y todas las `raw_*`. Son referencia compartida o analítica; poner RLS en `inventario_pv` rompe el join de disponibilidad.

### Tabla `usuarios`

```sql
CREATE TABLE usuarios (
  usuario_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         text UNIQUE NOT NULL,
  password_hash text NOT NULL,
  empresa_id    text NOT NULL REFERENCES empresas(empresa_id),
  asesor_id     text REFERENCES asesores(asesor_id),
  rol           text NOT NULL DEFAULT 'asesor',
  activo        boolean NOT NULL DEFAULT true,
  creado_en     timestamptz NOT NULL DEFAULT now()
);
```

Va en `002_referencia.sql`, y es la única tabla con `empresa_id` que **NO lleva RLS**: el login ocurre antes de que exista `app.empresa_id`, así que con la política activa la búsqueda por email devolvería cero filas y nadie podría entrar. Su aislamiento se hace en el endpoint.

`asesor_id` es nulable: un usuario con `rol = 'gerente'` ve todos los leads de su empresa; uno con `rol = 'asesor'` ve solo su cola. Dos líneas de condición en el endpoint.

**Hash con `bcrypt` vía `passlib`, nunca SHA256 pelado.** Los usuarios de demo se siembran desde el CLI (`python -m backend.cli seed-usuarios`) leyendo las contraseñas del `.env`. **Nunca un `INSERT` con contraseña en texto plano dentro de un `.sql` commiteado**: eso es la causal de descalificación de credenciales expuestas, aunque sea data de demo.

### En la API

Tabla `usuarios` sembrada con `empresa_id`, `asesor_id` y contraseña hasheada. `POST /auth/login` devuelve un JWT con esos claims. Cada request abre transacción y fija la variable de sesión:

```python
async def db_sesion(token: str = Depends(oauth2)):
    claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.empresa_id', %s, true)",
                (claims["empresa_id"],),
            )
            yield conn
```

El tercer argumento `true` de `set_config` lo hace local a la transacción, así que el valor no se filtra al siguiente request que reutilice esa conexión de la pool.

### Test obligatorio

Insertar leads de dos empresas, abrir sesión con `app.empresa_id = 'EMP-01'` y verificar que `SELECT count(*) FROM leads` devuelve solo los de esa empresa. Sin ese test, el aislamiento no está probado.
- **La deduplicación de clientes usa la clave `(empresa_id, telefono_normalizado)`**, nunca el teléfono solo

## Anomalías conocidas de los datos

Ya verificadas. No hay que redescubrirlas, hay que manejarlas.

### leads.csv (1.503 filas)
- **Teléfonos en formatos mixtos**: `3114997487`, `+57 322 1743999`, `302-683-4394`, `(315) 149-8889`, `573223242028`, y **151 con espacios sobrantes** al inicio o final. Normalizar a 10 dígitos: quitar todo lo que no sea dígito y el `57` inicial cuando el resultado tiene 12. Todos son recuperables **salvo uno** (`300123`, 6 dígitos) → `telefono_valido = false`, fuera del dedupe.
- **Cuatro formatos de fecha conviviendo en la misma columna**: `yyyy-mm-dd HH:MM:SS`, `xx/xx/yyyy HH:MM`, `dd-mm-yyyy`, e ISO con `T`. Parser en cascada.
- **96 fechas `mm/dd/yyyy` inequívocas** en `fecha_primer_contacto` (día > 12), más 309 ambiguas donde ambos campos son ≤ 12. Validación: si `fecha_primer_contacto < fecha_registro` o la fecha cae en el futuro, reintentar con el formato alterno.
- `canal`: 9 variantes de capitalización → enum de 3
- `estado_gestion`: 10 variantes → enum de 6
- `ciudad`: 37 variantes, 79 nulos. Bogotá aparece como `Bogotá D.C.`, `Bogotá`, `Bogota`, `BOGOTA`, `bogotá`, `Bogota DC`. También `Rio Negro`/`Rionegro` y `Cartagena`/`Cartagena de Indias`.
- `modelo_interes_texto`: **190 valores distintos para 24 SKUs reales**, 80 nulos. Algunos traen solo la marca (`Bajaj`, `Honda`). Normalizar → match exacto → fuzzy (rapidfuzz, umbral 85). Guardar `match_confidence` y `match_method`. Los que solo traen marca se resuelven a marca sin SKU.
- **86 leads** con estado distinto de "sin gestión" pero sin `fecha_primer_contacto` → flag de inconsistencia, no borrar.
- **Nombres**: 281 con espacios al inicio o final, 305 en TODO MAYÚSCULAS, 24 en minúsculas, 21 abreviados (`Y. Castaño Valencia`). Normalizar a Title Case sobre el nombre recortado.
- **67 filas con la marca mal escrita** en `modelo_interes_texto`: `Hnda`, `Bajai`, `Heroo`, `Suzuky`. El fuzzy match las resuelve; el match exacto no.
- **Match exacto marca+línea cubre solo 925 de 1.423** modelos no nulos. Las otras 498 (solo-marca, typos, doble espacio, minúsculas, `A.K.T`) van al fuzzy.

### Las tres últimas filas de leads.csv están plantadas

El archivo tiene 1.503 filas pero **1.500 leads reales**:

- **Fila 1501 — `LD-01501`**: registro de prueba del sistema. `nombre_cliente = "prueba prueba"`, `telefono = 300123`, `fecha_registro = 2026-08-33` (día 33, no existe), y `canal`, `email`, `ciudad` y `modelo` todos nulos. **No es un lead: va a cuarentena, no al pipeline.** Es también el único teléfono irrecuperable y el único canal nulo del archivo.
- **Filas 1502 y 1503**: copias **byte a byte** de `LD-00011` y `LD-00251`. `lead_id` duplicado con fila idéntica. Se eliminan antes del dedupe por identidad; son un caso distinto del dedupe por teléfono.

Detectar y reportar estas tres es barato y demuestra que validaste en vez de confiar.

### Duplicados
141 teléfonos repetidos en 283 filas.
- **73 grupos cruzan canal** → fusionar (lo pide el punto 2 del alcance)
- **91 grupos cruzan empresa** → **NO fusionar** (lo prohíbe el punto 8)

Al fusionar: conservar el `lead_id` más antiguo como canónico, acumular canales en array, registrar los absorbidos en `leads_fusionados`.

### conversaciones.json (677)
- **12** referencian `lead_id` que no existen en leads.csv → cuarentena, no romper el pipeline
- **25** leads tienen 2 conversaciones → concatenar cronológicamente antes de extraer
- `fecha_inicio` viene en un solo formato limpio (`yyyy-mm-dd HH:MM:SS`); `emisor` solo toma los valores `cliente` y `asesor`
- **Las 677 conversaciones declaran canal `WhatsApp`, pero 301 pertenecen a leads cuyo canal es Meta Ads o Formulario Web.** Esto **no es un error**: el cliente llegó por un canal y después escribió por WhatsApp. Es la señal multicanal que el enunciado pide detectar. No las descartes ni "corrijas" el canal del lead.
- Cortas: ~390 caracteres, 6,4 mensajes de media
- **861 de 1.503 leads no tienen conversación.** El scoring debe funcionar sin señal conversacional.

### historico_cierres.csv (2.200)
- Tasa base de cierre: 9,0 % (197 cerrados, 1.824 perdidos, 179 sin gestión)
- **Las 179 "Sin gestión" tienen `horas_al_primer_contacto` nulo y `numero_contactos = 0`** → fuga de información, **excluir del entrenamiento del score**
- 179 nulos en `horas_al_primer_contacto` corresponden exactamente a esas filas

### Lo que está limpio (no pierdas tiempo ahí)

Verificado: integridad referencial perfecta. Los 15 puntos de venta coinciden entre `leads`, `asesores`, `historico` y `catalogo`; ningún punto de venta pertenece a dos empresas; ningún lead está en un punto de venta de otra empresa. En el histórico, los 2.200 `modelo_cotizado` tienen match exacto en el catálogo y los 2.200 `precio_lista` coinciden. Los 803 emails son válidos y en minúsculas. `campania` tiene 5 valores limpios. `catalogo_motos` y `asesores` no tienen anomalías de formato.

### Dónde están los archivos fuente

`data/input/` en la raíz del repo: los cinco archivos entregados más el `LEEME.txt`. **Se commitean**: el `LEEME.txt` confirma que los datos son sintéticos y sin ellos el evaluador no puede correr el pipeline. El compose los monta en `/app/data/input` como solo lectura.

### Formato de los CSV
Separador `,` (coma), encoding UTF-8 **sin BOM**, saltos de línea CRLF. `asesores.fecha_ingreso` viene en ISO `yyyy-mm-dd`, limpio.

El paquete incluye un `LEEME.txt` que confirma estas convenciones. Léelo antes de escribir el parser.

## Extracción con IA

Schema estricto, todos los campos nullable. Tres campos usan **exactamente los valores del histórico** para poder cruzarlos:

- `forma_pago`: `contado` | `credito` | `no_informa`
- `manifesto_cuota_inicial`: `SI` | `NO` | `NO_INFORMA`
- `pidio_cita`: boolean

Más: `modelo_interes_mencionado`, `sku_resuelto`, `cuota_inicial_cop`, `pidio_cotizacion`, `intencion_declarada`, `objecion_principal`, `confianza`, `justificacion` (≤200 chars, cita textual del fragmento que sustenta la extracción).

El prompt vive en `prompts/extraccion_v1.md`, versionado. Nunca hardcodeado. Guardar `prompt_version` y `modelo_llm` en cada fila de `extracciones_ia`.

Concurrencia: `asyncio.Semaphore(8)` con reintentos y backoff exponencial.

## Scoring

Regresión logística entrenada sobre el histórico (sin las "Sin gestión"), coeficientes convertidos a puntos enteros y exportados a `config/score_weights.json`. El score de cada lead es la suma de puntos, con la lista de factores que aportaron guardada en `scores.factores` (jsonb).

**Las horas sin contacto son un multiplicador de urgencia, no una feature.** En el histórico predicen cierre; en un lead pendiente representan una ventana que se cierra.

Referencia medida: AUC 0.619 en CV5. El decil alto llega a 15,5 % de cierre (lift 1,6x sobre la base de 9 %).

## Etapas del pipeline

```
ingest → normalize → resolve-models → dedupe → extract-ai → score → assign
```

Cada una es un subcomando del CLI y corre sola. `run-all` las encadena.

```bash
# entorno Python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# pipeline
python -m backend.cli run-all          # pipeline completo
python -m backend.cli normalize        # una etapa
pytest                             # tests

# API
fastapi dev backend/api/main.py        # local, con recarga
fastapi run backend/api/main.py        # producción

# frontend
cd frontend && pnpm install && pnpm start   # solo pnpm, nunca npm ni yarn

# infra (local y VPS usan el mismo compose)
docker compose up -d
docker compose logs -f caddy       # aquí se ve la emisión del certificado
docker compose exec api python -m backend.cli migrate
```

**Despliegue:** el `docker-compose.yml` es el mismo en local y en producción. Solo cambia el `.env`. El `.env` nunca se commitea; `.env.example` sí, con valores de ejemplo. Exponer credenciales es causal de descalificación, así que `.gitignore` debe incluir `.env` desde el primer commit.

**Imágenes fijadas** (no uses `latest` en ninguna): `pgvector/pgvector:0.8.6-pg18`, `docker.n8n.io/n8nio/n8n:2.38.3`, `python:3.12-slim`, `node:24-alpine`, `caddy:2-alpine`.

**Archivos de infraestructura en la raíz del repo:** `docker-compose.yml`, `Dockerfile` (API, python:3.12-slim), `Dockerfile.web` (multietapa: node:24-alpine compila Angular → caddy:2-alpine lo sirve), `Caddyfile`, `.env.example`.

**Nunca borres el volumen `caddy_data`:** guarda los certificados de Let's Encrypt y el límite son 5 por semana para el mismo dominio.

**Puertos:** solo Caddy publica 80 y 443. Postgres y n8n no exponen puertos al exterior; se comunican por la red interna de Docker usando los nombres de servicio (`postgres:5432`, `api:8000`, `n8n:5678`).

**Dependencias:** se agregan a `requirements.txt` a mano, con versión fijada (`==`). No uses Poetry, uv ni pip-tools. En el frontend, solo `pnpm` — no generes `package-lock.json` ni `yarn.lock`.

## Estructura

```
backend/
  cli.py
  config.py
  db/           conexión, pool, sesión con RLS
  stages/       ingest, normalize, resolve_models, dedupe, extract_ai, score, assign
  llm/          cliente, schemas, caché
  api/          main.py, rutas, auth
db/migrations/  SQL numerado y versionado
data/input/     los 5 archivos fuente + LEEME.txt (se commitean)
prompts/        prompts versionados
config/         score_weights.json
tests/
frontend/       Angular (pnpm)
docs/           validacion.md, arquitectura
```

## Tests que importan

No busques cobertura alta. Cubre los casos raros:
- Teléfono `573223242028` → normaliza a `3223242028`
- Teléfono `  3149037411  ` con espacios → normaliza igual
- Teléfono `300123` → marcado inválido, fuera del dedupe
- `LD-01501` ("prueba prueba", fecha `2026-08-33`) → cuarentena, no entra al pipeline
- Fila con `lead_id` duplicado e idéntica → se elimina, queda una sola
- `Hnda CB 190R` → resuelve al SKU de Honda CB 190R por fuzzy
- Conversación WhatsApp sobre un lead de canal Meta Ads → se procesa igual, no se descarta
- Fecha `08/15/2026` → 15 de agosto, no falla
- Fecha `09/12/2026` ambigua → resuelta por coherencia con `fecha_registro`
- Los cuatro formatos (`2026-08-29 22:58:00`, `19/08/2026 17:40`, `09-08-2026`, `2026-08-24T14:11:00`) parsean correctamente
- Duplicado cross-canal → fusionado
- Duplicado cross-empresa → **NO** fusionado
- `modelo_interes_texto = "Bajaj"` → marca sin SKU, no SKU inventado
- Conversación con `lead_id` huérfano → cuarentena, pipeline sigue
- Reejecutar una etapa → mismo resultado, sin duplicados

## Estilo

- Español en comentarios, docstrings, logs y mensajes del CLI
- Nombres de tablas y columnas en español (coherente con los archivos fuente)
- Type hints en todo
- Sin comentarios que repitan lo que el código ya dice
