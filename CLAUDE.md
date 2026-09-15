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

**Hash con `bcrypt` directo (sin `passlib`), nunca SHA256 pelado.** `passlib` 1.7.4 falla con `bcrypt` 5 al detectar el backend. Los usuarios de demo se siembran desde el CLI (`python -m backend.cli seed-usuarios`) leyendo las contraseñas del `.env`. **Nunca un `INSERT` con contraseña en texto plano dentro de un `.sql` commiteado**: eso es la causal de descalificación de credenciales expuestas, aunque sea data de demo.

### En la API

Tabla `usuarios` sembrada con `empresa_id`, `asesor_id` y contraseña hasheada. `POST /auth/login` devuelve un JWT con esos claims. Cada request abre transacción y fija la variable de sesión:

```python
async def db_sesion(token: str = Depends(oauth2)):
    claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    async with pool.connection() as conn:   # la pool se crea con autocommit=True
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE app_tenant")
            await conn.execute(
                "SELECT set_config('app.empresa_id', %s, true)",
                (claims["empresa_id"],),
            )
            yield conn
```

Dos cosas que hacen que esto funcione, y ninguna es opcional:

**`SET LOCAL ROLE app_tenant`.** Postgres ignora RLS para superusuarios, con `FORCE` o sin él, y el `POSTGRES_USER` de la imagen oficial es superusuario. `FORCE` solo cubre al dueño de la tabla. Por eso la migración crea `app_tenant`, un rol sin login, sin superusuario con `SELECT/INSERT/UPDATE/DELETE` sobre las tablas operacionales, y cada request baja a ese rol dentro de la transacción. Al terminar, el rol vuelve al original.

**La pool se abre con `autocommit=True`.** Sin autocommit, la primera consulta abre una transacción implícita y los `with conn.transaction()` siguientes son solo savepoints: `SET LOCAL ROLE` y `set_config(..., true)` siguen vigentes en el request siguiente que reutilice esa conexión. Eso es una filtración de contexto entre empresas por ciclo de vida de conexión, no por un fallo de las políticas. Verificado en la prueba del día 1.

`GRANT USAGE ON SCHEMA public TO app_tenant` además de los `GRANT` sobre las tablas, o todo falla con un error de permisos que no menciona el esquema.

`POST /auth/login` consulta `usuarios` cuando todavía no se sabe la empresa: ese endpoint no hace `SET LOCAL ROLE`, o `app_tenant` necesita `SELECT` sobre `usuarios`. Decídelo explícitamente.

**El pipeline NO baja de rol.** El CLI corre como superusuario a propósito, porque escribe leads de las tres empresas a la vez. Solo la API cambia a `app_tenant`.

`app_tenant` lleva permisos de escritura a propósito, no solo `SELECT`: así un `INSERT` cruzado falla con `violates row-level security policy` en vez de `permission denied`. El primero demuestra que la política funciona; el segundo solo demostraría que el `GRANT` funciona.

### Test obligatorio

El test tiene que pasar por el mismo camino que la API: abrir transacción, `SET LOCAL ROLE app_tenant`, fijar `app.empresa_id` y contar. Si corre como superusuario pasa siempre y no prueba nada.

Resultado esperado, con 3 leads sembrados (2 de EMP-01, 1 de EMP-02):

| Contexto | `count(*)` |
|---|---|
| superusuario, sin cambiar de rol | 3 (se salta RLS) |
| `app_tenant` + `EMP-01` | 2 |
| `app_tenant` + `EMP-02` | 1 |
| `app_tenant` sin empresa fijada | 0 |

Probar también escritura: un `INSERT` de un lead de otra empresa debe fallar con `violates row-level security policy`, y un `UPDATE` sobre un lead ajeno debe afectar 0 filas.
- **La deduplicación de clientes usa la clave `(empresa_id, telefono_normalizado)`**, nunca el teléfono solo

## Anomalías conocidas de los datos

Ya verificadas. No hay que redescubrirlas, hay que manejarlas.

### leads.csv (1.503 filas)
- **Teléfonos en formatos mixtos**: `3114997487`, `+57 322 1743999`, `302-683-4394`, `(315) 149-8889`, `573223242028`, y **151 con espacios sobrantes** al inicio o final. Normalizar a 10 dígitos: quitar todo lo que no sea dígito y el `57` inicial cuando el resultado tiene 12. Todos son recuperables **salvo uno** (`300123`, 6 dígitos) → `telefono_valido = false`, fuera del dedupe.
- **Cuatro formatos de fecha conviviendo en la misma columna**: `yyyy-mm-dd HH:MM:SS`, `xx/xx/yyyy HH:MM`, `dd-mm-yyyy`, e ISO con `T`. Parser en cascada.
- **El formato con barras mezcla dd/mm y mm/dd de verdad**, no es uno con excepciones. Ver la sección siguiente.
- `canal`: 9 variantes de capitalización → enum de 3
- `estado_gestion`: 10 variantes → enum de 6
- `ciudad`: 37 variantes, 79 nulos. Bogotá aparece como `Bogotá D.C.`, `Bogotá`, `Bogota`, `BOGOTA`, `bogotá`, `Bogota DC`. También `Rio Negro`/`Rionegro` y `Cartagena`/`Cartagena de Indias`.
- `modelo_interes_texto`: **190 valores distintos para 24 SKUs reales**, 80 nulos. Algunos traen solo la marca (`Bajaj`, `Honda`). Normalizar → match exacto → fuzzy (rapidfuzz, umbral 85). Guardar `match_confidence` y `match_method`. Los que solo traen marca se resuelven a marca sin SKU.
- **86 leads** con estado distinto de "sin gestión" pero sin `fecha_primer_contacto` → flag de inconsistencia, no borrar.
- **Nombres**: 281 con espacios al inicio o final, 305 en TODO MAYÚSCULAS, 24 en minúsculas, 21 abreviados (`Y. Castaño Valencia`). Normalizar a Title Case sobre el nombre recortado.
- **67 filas con la marca mal escrita** en `modelo_interes_texto`: `Hnda`, `Bajai`, `Heroo`, `Suzuky`. El fuzzy match las resuelve; el match exacto no.
- **Match exacto marca+línea cubre solo 925 de 1.423** modelos no nulos. Las otras 498 (solo-marca, typos, doble espacio, minúsculas, `A.K.T`) van al fuzzy.

### Fechas con barras: dd/mm y mm/dd conviven

| | dd/mm inequívoco | mm/dd inequívoco | ambiguo (ambos ≤12) |
|---|---|---|---|
| `fecha_registro` | 204 | **59** | 265 |
| `fecha_primer_contacto` | 96 | **93** | 216 |

Un default fijo con reintento está mal: en `fecha_registro` no hay contra qué comparar y los 59 mm/dd quedarían mal leídos en silencio.

**Resolución: cascada con ventana derivada.** Las 974 fechas de formato inequívoco caen todas entre el 1 de agosto y el 10 de septiembre de 2026 (solo meses 8 y 9). Para cada fecha ambigua se prueban las dos lecturas y se descarta la que caiga fuera de esa ventana. En `fecha_primer_contacto` se descartan además las anteriores al registro; si quedan dos, gana la más cercana al registro.

Rendimiento medido: resuelve 214 de 265 en `fecha_registro` (157 a dd/mm, **57 a mm/dd**) y 163 de 216 en `fecha_primer_contacto` (78 a dd/mm, **85 a mm/dd**).

Quedan 51 y 53 donde ambas lecturas caen en la ventana, pero **de esas, 22 y 23 tienen día igual a mes** (`08/08/2026`): las dos lecturas dan la misma fecha, así que no son ambiguas.

Estado final tras la cascada completa:

| | sin resolver | resueltos por heurística, marcados |
|---|---|---|
| `fecha_registro` | **22** (default dd/mm + flag) | 7 por `coherencia` |
| `fecha_primer_contacto` | 0 | **14** por `mas_cercana` |

`mas_cercana` no es evidencia, es un desempate: sesga hacia contactos más rápidos, que es justo la variable que más predice cierre. Son 14 de 1.500, así que el efecto agregado es despreciable, pero esos leads llevan confianza baja y **no entran al set de validación del score**.

**El default dd/mm sale de los datos** (204 inequívocos contra 59 en `fecha_registro`), no de la convención colombiana. Ese es el argumento que va al README.

**La ventana se calcula, no se escribe a mano.** Va desde la mínima fecha inequívoca menos 7 días hasta `FECHA_REFERENCIA`, sin margen por arriba porque nada puede ser posterior al corte. Márgenes de 0 a 7 días dan el mismo resultado (probado). Un número mágico deja de funcionar con otro corte de datos y es peor de defender.

Guardar por fecha el método que la resolvió y sacar los conteos en el log del pipeline: los 57 mm/dd de `fecha_registro` son la evidencia de que la trampa existía.

### Contactos sin hora (208 filas)

Los contactos en formato `dd-mm-yyyy` no traen hora. Comparar contra un `00:00` inventado producía 61 falsas inconsistencias de "contacto antes del registro".

- Columna **`fecha_contacto_sin_hora`** para que el scoring no calcule horas transcurridas sobre una medianoche que nadie observó
- Cuando falta la hora, la comparación con el registro es **por día de calendario**: el mismo día no es inconsistencia
- El desempate del registro por `coherencia` solo usa contactos **inequívocos**, y una diferencia de calendario real; un contacto sin hora el mismo día nunca descarta una lectura

Resultado: `contacto_antes_registro` pasa de 62 a 0. **Ojo al interpretarlo:** para los leads resueltos por `coherencia` ese cero está garantizado por construcción, porque se eligió la lectura que dejaba el contacto compatible. La validación independiente son los leads que no pasaron por coherencia.

### `FECHA_REFERENCIA`: nunca `now()`

La validación de "fecha en el futuro" y el multiplicador de urgencia del score usan una `FECHA_REFERENCIA` configurable, **por defecto el máximo de las fechas inequívocas del dataset**, no la fecha del sistema. Ese máximo es **`2026-09-14 01:35`**, y sale de `fecha_primer_contacto`; el máximo de `fecha_registro` es el 10 de septiembre, así que hay que mirar ambas columnas.

Dos razones. Idempotencia: con `now()` el resultado de `normalize` cambia según el día en que se corra. Y la demo: si la urgencia usa la fecha real, en tres semanas todos los leads estarán aplastados contra el piso del decay y el tablero dejará de diferenciar nada.

Va al README como supuesto explícito: el dataset es un corte estático y en operación real la referencia sería la fecha de ejecución.

### Cuarentena

Una sola tabla `cuarentena` con clave única `(etapa, origen, clave, motivo)`. Cada etapa borra **sus propias** filas (acotado por `etapa`, nunca un `TRUNCATE`) y las reescribe, así la tabla siempre refleja la última corrida.

**La regla es genérica, no hecha a la medida de una fila**: va a cuarentena toda fila con `fecha_registro` imposible o sin `canal`, porque no es un lead utilizable. Hoy solo la cumple `LD-01501`, y esa coincidencia es del dataset, no de la regla.

Dos precisiones:
- **"Imposible" es día 33, no "fuera de la ventana".** Una fecha parseable pero rara se marca con un flag, no se descarta. Si confundes las dos, botas leads buenos.
- El `motivo` registrado debe ser específico (`fecha_registro imposible: 2026-08-33`, `canal nulo`), no un genérico "fila inválida".

### Las tres últimas filas de leads.csv están plantadas

El archivo tiene 1.503 filas pero **1.500 leads reales**:

- **Fila 1501 — `LD-01501`**: registro de prueba del sistema. `nombre_cliente = "prueba prueba"`, `telefono = 300123`, `fecha_registro = 2026-08-33` (día 33, no existe), y `canal`, `email`, `ciudad` y `modelo` todos nulos. **No es un lead: va a cuarentena, no al pipeline.** Es también el único teléfono irrecuperable y el único canal nulo del archivo.
- **Filas 1502 y 1503**: copias **byte a byte** de `LD-00011` y `LD-00251`. `lead_id` duplicado con fila idéntica. Se eliminan antes del dedupe por identidad; son un caso distinto del dedupe por teléfono.

Detectar y reportar estas tres es barato y demuestra que validaste en vez de confiar.

### Duplicados
141 teléfonos repetidos en 283 filas.
- **73 grupos cruzan canal** → fusionar (lo pide el punto 2 del alcance)
- **91 grupos cruzan empresa** → **NO fusionar** (lo prohíbe el punto 8)

Al fusionar: conservar el `lead_id` más antiguo como canónico y acumular canales en `canales text[]`. Los absorbidos se quedan en `leads` con `lead_canonico_id` y `motivo_fusion`. **No existe tabla `leads_fusionados`** (ver decisión 3 abajo).

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

## Decisiones de modelado ya tomadas (día 1)

No las revises ni las cambies sin decírmelo.

1. **`canal`** guarda los valores del histórico (`WhatsApp`, `Meta Ads`, `Formulario Web`) para cruzar directo con `historico_cierres`.
2. **`estado_gestion`** en snake_case (`sin_gestion`, `cotizacion_enviada`…). El motivo es preferir identificadores sin tildes ni espacios en la base; la forma de presentación se resuelve en el frontend.
3. **Dedupe:** los leads absorbidos se quedan en `leads` con `lead_canonico_id` apuntando al canónico, que acumula `canales text[]`. No hay tabla `leads_fusionados`. Además, columna **`motivo_fusion`** con la regla que disparó y su confianza: sin eso no hay trazabilidad de por qué se fusionaron dos leads.
4. **`cuarentena`** es una sola tabla con clave única `(etapa, origen, clave, motivo)`.
5. **`extracciones_ia`** tiene clave `(lead_id, conversacion_hash)`. Solo el hash chocaría entre dos leads con el mismo texto.
6. **`temperatura`** restringida a `alta` / `media` / `baja`. `score_pesos` se crea el día 3, cuando existan los pesos.
7. **El pipeline corre sin RLS**, como superusuario, a propósito. Solo la API baja a `app_tenant`.
8. **Mensajes:** se reemplazan enteros por conversación, para que no queden sobrantes si el archivo trae menos.

## Extracción con IA

Schema JSON estricto en `backend/llm/schemas.py`. Tres campos usan **los valores del histórico** para poder cruzarlos:

- `forma_pago`: `contado` | `credito` | `no_informa` (histórico: `forma_pago_declarada`)
- `manifesto_cuota_inicial`: `SI` | `NO` | `NO_INFORMA`
- `pidio_cita`: `SI` | `NO` | `NO_INFORMA` — **no es boolean**: en el histórico vale `SI`/`NO`

**`NO_INFORMA` es su propia categoría, nunca se convierte en `NO`.** El histórico de `pidio_cita` solo tiene `SI`/`NO` porque ahí el dato ya está registrado; una conversación puede simplemente no tocar el tema. Qué peso recibe `NO_INFORMA` lo decide el score, no la extracción. `pidio_cotizacion` sigue la misma regla (`SI` | `NO` | `NO_INFORMA`) e `intencion_declarada` incluye `no_informa`. Los enums no son nullable: la ausencia se dice con `NO_INFORMA`, así hay una sola forma de decirlo.

Resto de campos: `modelo_interes_mencionado` y `cuota_inicial_cop` (nullable), `objecion_principal`, `confianza` (0-1) y `justificacion`.

`objecion_principal` incluye `sin_inicial` (no tiene para la inicial) e `historial_crediticio` (reportado, centrales, Datacrédito), separados de `cuota`, que es solo la mensualidad alta. Es información para el asesor: el histórico no tiene columna de objeción.

**`confianza` no se usa para priorizar.** La autoevaluación de un LLM está mal calibrada; en la muestra de v1 solo tomó 0,8 / 0,9 / 1,0. Queda en el JSON y nada más. Como señal de riqueza de la conversación se usa **`campos_informados`**: cuántos de `forma_pago`, `manifesto_cuota_inicial`, `pidio_cita`, `pidio_cotizacion` e `intencion_declarada` salieron distintos de no informa (0 a 5). Lo calcula el código, no el modelo.

**Validación de consistencia: registra, no corrige** (`backend/llm/validacion.py`). Si el código reescribe la salida, se pierde la medida de cuánto se equivoca el modelo. Las reglas del prompt verificables en código se chequean y las violaciones quedan en `payload.violaciones` y en el resumen de la etapa: `contado_con_cuota_inicial`, `monto_sin_manifestar_inicial`, `inicial_cero_marcada_como_si`, `justificacion_no_literal_del_cliente`. Cero violaciones prueba consistencia, no acierto: el acierto se mide contra el set etiquetado a mano, **nunca contra el SKU del formulario** (ver abajo). Los derivados (`sku_resuelto`, `campos_informados`, `violaciones`) se recalculan en cada corrida sin llamar a la API.

### Reglas derivadas en el score (decididas el día 3)

La salida del LLM en `extracciones_ia` nunca se modifica. Cuando el score necesita un valor distinto, lo calcula con una regla derivada en `backend/stages/score.py` y registra el nombre de la regla en `scores.factores`.

- **`forma_pago_para_score`:** si `manifesto_cuota_inicial` es `SI` o `NO` y `forma_pago` es `no_informa`, el score usa `credito` (regla `inicial_mencionada_implica_credito`). Nadie que pague de contado dice "no tengo inicial". Aplica a 28 leads.
- **`sku_para_score`:** el score usa el SKU de la conversación cuando existe y el del formulario como respaldo. Se guardan ambos y **el tablero muestra los dos cuando difieren**.

**El SKU del formulario y el de la conversación son independientes en estos datos:** coinciden 3,6 % contra 4,1 % esperado por azar. No se usa uno para validar el otro. No escribir en ningún lado que "los clientes pidieron algo distinto": es un artefacto del generador sintético, no una afirmación de negocio que los datos sostengan.

### Qué campos tienen calibración contra el histórico

Esto decide qué puede pesar en el score con pesos derivados de la regresión.

| Campo | Columna del histórico | ¿Calibrable? |
|---|---|---|
| `forma_pago` | `forma_pago_declarada` | Sí |
| `manifesto_cuota_inicial` | `manifesto_cuota_inicial` | Sí |
| `pidio_cita` | `pidio_cita` (`SI`/`NO`) | `SI` y `NO` sí. `NO_INFORMA` no existe en el histórico: su tratamiento es criterio propio |
| `sku_resuelto` | `modelo_cotizado`, `precio_lista` | Sí, a través del precio o segmento del modelo |
| `cuota_inicial_cop` | — | No: no hay columna de monto |
| `pidio_cotizacion` | — | No |
| `intencion_declarada` | — | No |
| `objecion_principal` | — | No, es información para el asesor |
| `campos_informados` | — | No |
| `confianza` | — | No, y no se usa |
| `estado_gestion` | — | No: el histórico no trae esa columna. Filtra la cola y da contexto al asesor; **no prioriza** |

Lo no calibrable solo entra al score como ajuste de criterio propio, declarado como tal en `factores` y en el README.

### Versiones del prompt

- `extraccion_v1`: primera versión. La muestra de 10 mostró: dinero de contado tomado como cuota inicial, `NO` con monto a la vez, "¿No tienen usadas?" sin clasificar como `precio`, y un ejemplo mal puesto en `pidio_cotizacion`.
- `extraccion_v2`: los arreglos van en el prompt, no en código. Reglas explícitas de inicial vs. contado, de inicial → `credito`, `precio` definido por significado y no con frases literales, y los dos valores nuevos de objeción.

  Resultado en la muestra: 0 violaciones, pero 4 regresiones de `NO_INFORMA` a `NO`/`SI` en `pidio_cita` y `pidio_cotizacion`, porque cada advertencia sobre un campo empuja al modelo a pronunciarse sobre él.
- `extraccion_v3`: la mitad de largo que v2 (494 palabras contra 986). Solo definiciones, sin advertencias ni casos límite; `NO` exige que el tema se haya mencionado y el cliente lo haya rechazado con palabras.

- `extraccion_v4`: v3 + **schema reordenado** (`forma_pago → manifesto_cuota_inicial → cuota_inicial_cop`) + "dice que" en `comparando`. El modelo escribe el JSON en el orden de las propiedades: un campo que depende de otro va después de él en el schema. 
- `extraccion_v5`: **corrección de una definición de negocio, no un arreglo del prompt.** `manifesto_cuota_inicial = SI` exige un monto mayor que cero y una cifra de cero es `NO`, porque es la categoría que cruza con el histórico. `cuota_inicial_cop` conserva el literal (0). Es la versión de la corrida completa.

Todas se conservan en `prompts/`. Resultados, medición de ruido y errores aceptados: `docs/validacion.md`.

**Antes de atribuir una mejora al prompt, se mide el ruido** con `python -m backend.cli medir-ruido`. Una diferencia entre versiones dentro de la variabilidad de llamadas idénticas no cuenta como efecto del cambio. El hash incluye la versión, así que cada una tiene su propia caché.

Reglas del prompt que no se negocian:
- **Solo cuentan las declaraciones del cliente.** Lo que dice el asesor es contexto; si el cliente no lo confirma, no es señal.
- **`justificacion` es cita textual del cliente** (≤200 chars, fragmentos separados por ` | `), nunca resumen. Es la defensa contra alucinación en la demo.
- **`modelo_interes_mencionado` es lo que escribió el cliente, sin normalizar ni completar.** `sku_resuelto` no lo produce el LLM: se calcula después con la cascada de `resolve-models` y se guarda con `sku_match_method` en el mismo `payload`.

### `cuota_inicial_cop` no tiene fuente de calibración

El histórico solo trae `manifesto_cuota_inicial` (`SI`/`NO`/`NO_INFORMA`), **sin ninguna columna de monto**. Si el monto entra al score, es por criterio propio y se declara así en `factores` y en el README, separado de los pesos derivados de la regresión. No se mezcla con ellos ni se presenta como calibrado.

El prompt vive en `prompts/extraccion_v1.md`, versionado. Nunca hardcodeado. Guardar `prompt_version` y `modelo_llm` en cada fila de `extracciones_ia`.

Concurrencia: `asyncio.Semaphore(8)` con reintentos y backoff exponencial.

## Scoring

Regresión logística entrenada sobre el histórico (sin las "Sin gestión"), coeficientes convertidos a puntos enteros y exportados a `config/score_weights.json`. El score de cada lead es la suma de puntos, con la lista de factores que aportaron guardada en `scores.factores` (jsonb).

**Las horas sin contacto son un multiplicador de urgencia, no una feature.** En el histórico predicen cierre; en un lead pendiente representan una ventana que se cierra.

**Dos componentes con respaldo distinto. Nunca se reporta un AUC único como si midiera el score completo.**
- **Señales de la conversación:** `logit_v2` (`python -m backend.scoring.entrenar`) con `pidio_cita`, `manifesto_cuota_inicial` y `forma_pago`. Validación fuera de pliegue de los puntos de producción (`python -m backend.scoring.validar_score`): AUC 0,552, lift del top 20 % 1,31x, temperatura alta 13,9 % contra baja 7,4 %. Cita × crédito es una interacción que el modelo aditivo no captura. **`canal` y precio no entran:** sus pesos cruzaban el cero. Tampoco `horas_al_primer_contacto` ni `numero_contactos`, que no existen al priorizar.
- **Urgencia:** multiplicador por tramo (≤1 h, 1–4 h, 4–24 h, 24–48 h, >48 h) = tasa del tramo / tasa base, **calculado en `entrenar.py` y guardado en `score_weights.json`, nunca escrito a mano**. Para un lead pendiente las horas son desde el registro sin contacto: **premia la oportunidad, no un resultado**. Un cliente ya contactado tiene multiplicador 1.

**Pesos centrados en la tasa base.** `SI` suma y `NO` resta según sus log-odds; `NO_INFORMA` / `no_informa` = 0 puntos (sin información, sin ajuste), también en `forma_pago`. 1 punto = 0,01 de log-odds.

**Escala 0–100 entera.** 50 = tasa base; 0 y 100 = peor y mejor combinación **alcanzable** (se enumeran las combinaciones que la extracción puede producir; contado con inicial SI no cuenta). Sin recortes.

**Priorizar no es predecir: dos colas.** `primer_contacto` (ningún lead del grupo contactado) y `seguimiento` (ya contactados); `descartado` queda fuera de cola. Nunca un orden global: el multiplicador castiga haber esperado y mandaría al final a los no contactados.
- **Orden en cada cola:** score descendente, desempate por horas transcurridas ascendentes (primer contacto: desde el registro; seguimiento: desde el primer contacto), último criterio `lead_id`.
- **Temperatura = calidad del lead, separada de la capacidad:** alta = dos señales positivas fuertes (`pidio_cita = SI`, `forma_pago = contado`, `manifesto_cuota_inicial = SI`), media = una, baja = ninguna. No depende de la posición ni de si entra hoy.
- **Capacidad por punto de venta, nunca global** (etapa `assign`): capacidad del PV = suma de sus asesores activos. Primer contacto = ⌈pendientes del PV / `DIAS_ABSORBER_REPRESAMIENTO`⌉ con tope en la capacidad; seguimiento = el resto. Reparto entre asesores proporcional a su capacidad, con la misma proporción entre colas. **No hay asesores dedicados**: `asesores.csv` no trae roles.
- `assign` reporta alertas por PV: pendientes que no se absorben en los días fijados y cartera activa que supera capacidad × días.
- **Traslado de sobrante entre colas**, en ambos sentidos y solo dentro del mismo PV: la proporción se respeta mientras ambas colas tengan clientes; el objetivo de días es un mínimo, no un techo. Seguimiento se reparte sobre la capacidad restante de cada asesor, así nadie supera la suya.
- **El cliente fusionado se asigna al PV de su lead más reciente** (`scores.punto_venta_id`), no al del canónico, que es el más antiguo.
- En este corte estático el multiplicador es constante para los pendientes (todos > 48 h); se conserva porque en operación diaria discrimina.
- `scores` guarda una fila por cliente (lead canónico) y se reemplaza entera en cada corrida (migración 009). `asignaciones` se reemplaza por fecha y guarda la cola (migración 010).

**Las comparaciones de modelos se deciden sobre CV repetida con varias semillas, nunca sobre una partición.** Con 197 positivos, la partición mueve el AUC tanto como la familia del modelo; solo reordenar las filas lo movió 2 puntos. El AUC 0.619 del plan inicial no se reproduce y no se cita. Los datos del entrenamiento se leen con `ORDER BY` fijo.

`historico_cierres.pidio_cita` es texto `SI`/`NO` desde la migración 008, igual que el archivo: sin traducción boolean al leer.

### Requisito: la cola del día consolida el grupo fusionado, no lee solo el canónico

`dedupe` deja el lead canónico **intacto**: conserva su propio `estado_gestion`, `fecha_primer_contacto`, punto de venta y SKU. Los absorbidos siguen en `leads` con `lead_canonico_id` apuntando a él. Consolidar es trabajo de `score`, y es obligatorio:

- **`estado_gestion`**: el más avanzado del grupo (canónico + absorbidos).
- **`fecha_primer_contacto`**: la más temprana del grupo.

Si `score` lee solo el canónico, un cliente con cotización enviada por un canal aparece como `sin_gestion` por el otro, y el asesor lo llama desde cero. Es exactamente la queja del gerente comercial. De los 49 grupos fusionados, **41 tienen estados distintos** entre sus leads: el caso no es teórico.

**Orden del embudo (decidido el día 3):** `sin_gestion → no_contesta → contactado → en_proceso → cotizacion_enviada`. El grupo toma el estado más avanzado de esa escala.

**`descartado` no está en la escala:** es una salida, no un avance. Se resuelve por recencia: si el descarte es el estado más reciente del grupo, el cliente está descartado; si es anterior a otro estado, la persona volvió y vale el estado del embudo. Afecta a 13 de los 49 grupos fusionados.

**Fecha sustituta: `fecha_registro` de cada lead del grupo.** Los leads no traen fecha de cambio de estado. Es una aproximación declarada en el README: un registro nuevo después del descarte cuenta como que la persona volvió.

### Variables del modelo: solo las que existen para un lead nuevo

El score se entrena sobre `historico_cierres` y se aplica a `leads`. Una variable que no se puede calcular para un lead actual no entra al entrenamiento, aunque suba el AUC.

| Variable del histórico | En un lead actual | ¿Entra? |
|---|---|---|
| `canal` | Directa (`leads.canal`) | Sí |
| `precio_lista` (vía `modelo_cotizado`) | Derivada: SKU (conversación o formulario) → `motos.precio_lista`. Sin SKU en los leads con solo marca y sin conversación | Sí, con categoría "sin precio" |
| `manifesto_cuota_inicial` | Derivada del LLM (640 leads); sin conversación queda `NO_INFORMA` | Sí |
| `forma_pago_declarada` | Derivada del LLM + regla `inicial_mencionada_implica_credito`; sin conversación queda `no_informa` | Sí |
| `pidio_cita` | Derivada del LLM (`SI`/`NO`/`NO_INFORMA`). El histórico solo tiene `SI`/`NO` | Sí, con tratamiento explícito de `NO_INFORMA` |
| `horas_al_primer_contacto` | Solo existe **después** del contacto: nula en los 485 leads pendientes, que son justo los que hay que priorizar; sin hora en 208 | **No** como feature. Es el multiplicador de urgencia |
| `numero_contactos` | **No existe** en `leads.csv` y no se deriva de nada (los mensajes de WhatsApp no son contactos del asesor) | **No** |

## Etapas del pipeline

```
ingest → load-reference → normalize → resolve-models → dedupe → extract-ai → score → assign
```

Cada una es un subcomando del CLI y corre sola. `run-all` las encadena.

**`load-reference` es una etapa propia, no parte de `normalize`.** Carga `empresas`, `puntos_venta`, `marcas`, `motos`, `inventario_pv`, `asesores` e `historico_cierres` desde las tablas `raw_*`. Son cosas distintas: la referencia es un upsert de catálogos que llegan limpios; `normalize` es parseo en cascada, cuarentena y flags. Y hay una dependencia dura, porque `leads` tiene llaves foráneas a `puntos_venta`, `motos` y `ciudades`: como etapa propia esa dependencia es explícita, escondida dentro de `normalize` es solo un orden de instrucciones que alguien puede reordenar.

Dos matices:
- **`historico_cierres` no es referencia, es analítica.** Se carga aquí por comodidad, pero solo la consume el entrenamiento del score. No se cruza con los leads del día.
- **`ciudades` no sale de ningún archivo**: se construye a partir de las 37 variantes. Va como datos semilla en una migración, no en esta etapa.

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

**Nombre del proyecto de Compose fijo (`name: leads-motos`).** Sin él, Compose usa el nombre de la carpeta (`project`) y los volúmenes chocan con otros proyectos del mismo equipo: el 15 de septiembre, n8n montó el `project_n8n_data` de otro proyecto y solo lo salvó que la clave de cifrado no coincidía.

**Postgres 18 monta el volumen en `/var/lib/postgresql`, no en `/var/lib/postgresql/data`.** Con el montaje viejo arranca la primera vez y falla en cualquier reinicio.

**En local, `DOMINIO=localhost docker compose up -d --build`.** Con el dominio real, Caddy pediría certificados a Let's Encrypt desde un equipo al que el DNS no apunta y gastaría intentos del límite.

**API detrás de Caddy:** `handle_path /api/*` quita el prefijo, las rutas de FastAPI no llevan `/api` y `root_path="/api"` corrige `/docs`. n8n llama directo a `http://api:8000/pipeline/run`.

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
- Fecha `09/12/2026` → la ventana la resuelve antes de llegar a la coherencia, porque diciembre queda fuera. Usa fechas distintas para cubrir los dos métodos por separado.
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
