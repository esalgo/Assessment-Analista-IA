# Priorización de leads — Motos

Pipeline que convierte los leads crudos de tres comercializadoras de motos en **la lista de gestión del día de cada asesor**, ordenada por probabilidad de cierre y por la ventana de contacto que se está cerrando.

Entra: 1.503 filas de `leads.csv`, 677 conversaciones de WhatsApp, 2.200 cierres históricos, 24 motos y 42 asesores. Sale: 1.451 clientes únicos, cada uno con un score explicable, una temperatura y un puesto en la cola de un asesor concreto.

**Tablero:** `https://<DOMINIO>` · **API:** `https://<DOMINIO>/api/docs` · **Orquestación:** `https://n8n.<DOMINIO>`

> **Sobre los datos de este repositorio.** Los cinco archivos de entrada están versionados en `data/input/` para que cualquiera pueda reproducir el pipeline completo. Su `LEEME.txt` declara: *"Los datos son sintéticos y no corresponden a clientes reales"*, así que los nombres, teléfonos, correos y conversaciones que aparecen en el tablero y en la documentación no son información de personas. Lo que sí es real y nunca entra al repositorio son las credenciales: el `.env` está en `.gitignore` desde el primer commit y no aparece en ningún punto del historial.

## El problema, en números del propio dataset

| Hecho medido | Dónde está |
|---|---|
| Contactar en menos de 1 h cierra **15,1 %**; pasadas 48 h, **5,8 %**. La tasa base es 9,75 % (histórico sin los 179 "Sin gestión") | `docs/validacion.md` §2.3 |
| **451 clientes** llevan más de 48 h sin que nadie los toque | `docs/validacion.md` §2.5 |
| **823 de los 1.451 clientes no tienen conversación**: el score no puede depender de ella | `scores.sin_senal_conversacional` |
| **49 grupos** son la misma persona registrada dos veces dentro de una empresa, y 41 de ellos traen estados distintos | "Deduplicación" |
| **91 grupos** comparten teléfono entre empresas distintas y **no** se fusionan | "Deduplicación" |
| **PV-013** tarda 7,0 días en atender su cartera; PV-012, de la misma empresa, 0,9 | `docs/validacion.md` §2.5 |

## Cómo verlo

El tablero tiene dos vistas, según el rol del usuario que entra:

- **Asesor** (`<asesor_id>@example.com`): su cola del día en dos grupos, primer contacto y seguimiento. Al abrir un cliente ve el score desglosado en factores, las citas textuales de su conversación y las dos motos (la del formulario y la de la conversación) cuando difieren.
- **Gerente** (`gerente.<empresa_id>@example.com`): elige cualquier asesor de **su** empresa y ve, además, los días de cartera por punto de venta.

**Usuarios de demo para revisar el tablero:**

| Usuario | Rol | Qué muestra |
|---|---|---|
| `as-014@example.com` | asesor de EMP-01 | 20 clientes, 10 en temperatura alta, 14 con conversación |
| `as-041@example.com` | asesor de EMP-03 | 25 clientes, la cola más cargada |
| `gerente.emp-01@example.com` | gerente de EMP-01 | selector de asesor y días de cartera por punto de venta |
| `gerente.emp-03@example.com` | gerente de EMP-03 | incluye PV-013, el punto de venta represado |

Entrar con los dos gerentes, uno después del otro, es la forma más rápida de comprobar el aislamiento: cambian los asesores, los puntos de venta y los clientes.

**Las contraseñas van en el mensaje de entrega, no en este repositorio.** Se siembran desde el `.env` del servidor (`SEED_PASSWORD_ASESOR`, `SEED_PASSWORD_GERENTE`) con `python -m backend.cli seed-usuarios`, que las hashea con bcrypt. Ningún `.sql` versionado contiene una contraseña, ni siquiera de demo: un repositorio con credenciales escritas es exactamente lo que no debe pasar, aunque el entorno sea de prueba.

Hay un usuario por asesor activo (`<asesor_id en minúsculas>@example.com`) y uno por empresa (`gerente.<empresa_id en minúsculas>@example.com`).

**La demostración del aislamiento:** cierra sesión, entra como gerente de otra empresa y cambia todo (asesores, puntos de venta, clientes). No es un filtro del frontend: `empresa_id` sale del token firmado y el filtrado ocurre en Postgres con RLS.

## Cómo correrlo

Requisitos: Docker con Compose. No hace falta Python ni Node en la máquina.

```bash
cp .env.example .env          # llenar con valores reales (ver DEPLOY del servidor)
docker compose up -d --build

docker compose exec api python -m backend.cli migrate        # esquema + RLS
docker compose exec api python -m backend.cli run-all        # pipeline completo
docker compose exec api python -m backend.cli seed-usuarios  # usuarios de demo
```

En local, `DOMINIO=localhost docker compose up -d --build`: con el dominio real, Caddy pediría certificados a Let's Encrypt desde una máquina a la que el DNS no apunta.

Cada etapa corre sola y es idempotente: reejecutar no duplica nada ni cambia el resultado.

```bash
docker compose exec api python -m backend.cli normalize
docker compose exec api python -m backend.cli score
```

## Arquitectura

```
data/input/ (5 archivos)                     n8n  ── cron 6:00 ─┐
     │ montados :ro                                             │
     ▼                                                          ▼
  ingest → load-reference → normalize → resolve-models ──▶ POST /api/pipeline/run
              → dedupe → extract-ai → score → assign            (FastAPI)
                              │                                  │
                         OpenAI gpt-4o-mini                      │
                              │                                  ▼
                              └──────────▶ Postgres 18 ◀── RLS ── sesión app_tenant
                                                │
                                                ▼
                                    Angular (Caddy) ── https://<DOMINIO>
```

Una sola máquina, un `docker-compose.yml` para local y producción, cuatro servicios: `caddy` (TLS y estáticos), `api`, `postgres` y `n8n`. Solo Caddy publica puertos.

**Los tres diagramas están en [`docs/arquitectura.md`](docs/arquitectura.md)**, en Mermaid: el flujo de datos etapa por etapa, el modelo entidad-relación de las 24 tablas y el despliegue en el VPS.

**Todo lo que hace n8n se puede hacer sin n8n.** Dispara `POST /pipeline/run` y nada más: cero lógica en sus nodos. El mismo trabajo lo hace `python -m backend.cli run-all`, que es el plan B si la orquestación falla.

## Las ocho etapas

| Etapa | Qué hace | Resultado medido |
|---|---|---|
| `ingest` | Carga los 5 archivos **sin limpiar** a tablas `raw_*` | 1.503 filas, hash por archivo |
| `load-reference` | Catálogos y `historico_cierres` desde `raw_*` | 3 empresas, 15 PV, 42 asesores, 24 motos |
| `normalize` | Teléfonos, 4 formatos de fecha, ciudades, canal, estado, nombres, cuarentena | 1.500 leads; `LD-01501` y 2 duplicados idénticos fuera |
| `resolve-models` | 190 textos → 24 SKUs, con cascada y fuzzy | **0 sin resolver**, 0 SKUs inventados |
| `dedupe` | Identidad por `(empresa_id, telefono_normalizado)` | 49 fusiones; 91 cruces entre empresas **no** fusionados |
| `extract-ai` | LLM con structured outputs sobre las conversaciones | 640 leads, caché por hash, 3 min 23 s |
| `score` | Pesos de regresión + multiplicador de urgencia + dos colas | 1.451 clientes con factores explicables |
| `assign` | Capacidad por punto de venta y reparto entre asesores | 688 de 694 plazas; alertas por PV |

## Modelo de datos

Dos capas. **`raw_*`** guarda los archivos tal como llegaron, en texto: permite reprocesar sin volver a leer disco y deja la trazabilidad de qué venía de origen. **Capa core** (`clientes`, `leads`, `conversaciones`, `mensajes`, `extracciones_ia`, `scores`, `asignaciones`, más los catálogos) tiene tipos reales, enums y llaves foráneas.

Tres decisiones que vale la pena mirar:

- **La identidad del cliente es `(empresa_id, telefono_normalizado)`**, no el teléfono solo. La restricción vive en el motor, así que el aislamiento no depende de que nadie olvide un `WHERE`.
- **Nada se borra.** Las filas inválidas van a la tabla `cuarentena` con un motivo específico; los leads absorbidos por el dedupe se quedan con `lead_canonico_id` y `motivo_fusion`.
- **La salida del LLM no se corrige nunca.** Lo que el modelo devolvió queda intacto en `extracciones_ia`; cuando el score necesita otro valor, aplica una regla derivada con nombre y la registra en `scores.factores`.

**Limitación: la empresa de un lead y la de su cliente coinciden por el código, no por el motor.** `leads` guarda `empresa_id` además de `cliente_id`, por dos motivos: la política de RLS compara la columna de la propia fila, y el lead existe desde `normalize`, antes de que `dedupe` le asigne cliente. Hoy las dos empresas coinciden porque `dedupe` asigna `cliente_id` filtrando por empresa y teléfono, pero ninguna restricción lo impone. La corrección sería una llave foránea compuesta `(cliente_id, empresa_id)` en `leads` hacia `UNIQUE (cliente_id, empresa_id)` en `clientes`, que haría imposible colgar un lead de un cliente de otra empresa.

Las 10 migraciones están numeradas en `db/migrations/` y las aplica `backend.cli migrate`.

## Aislamiento multi-tenant

`empresa_id` **nunca** es parámetro de un endpoint: sale del JWT o no sale. Cada request abre transacción, hace `SET LOCAL ROLE app_tenant`, fija `app.empresa_id` y deja que las políticas de RLS filtren en Postgres.

Dos trampas que costaron depuración y están documentadas abajo: `FORCE ROW LEVEL SECURITY` no basta si la API se conecta como superusuario, y sin `autocommit=True` el contexto de una empresa sobrevive al request. `tests/test_aislamiento.py` prueba las dos.

## Componente de IA

`gpt-4o-mini` con structured outputs (JSON Schema estricto), llamada directa al SDK de OpenAI: sin frameworks de agentes, porque esto es extracción estructurada por lotes.

- **Prompt versionado** en `prompts/` (5 versiones, todas conservadas) y `prompt_version` guardado en cada extracción.
- **Caché por `sha256(conversación + prompt_version)`**: reejecutar no vuelve a pagar tokens ni cambia resultados.
- **`justificacion` con cita textual del cliente**, nunca resumen: es lo que permite auditar una respuesta en vivo.
- **Acierto medido contra 15 conversaciones etiquetadas a mano**, antes de ver la salida del modelo: **88 % global y 93 % en los campos que entran al score** (`docs/validacion.md` §1.8, reproducible con `python -m backend.llm.validar_extraccion`).
- **Las violaciones de las reglas del prompt se registran, no se corrigen** (`payload.violaciones`).

## API

| Endpoint | Quién | Qué devuelve |
|---|---|---|
| `GET /health` | público | estado del servicio |
| `POST /auth/login` | público | JWT con `empresa_id`, `asesor_id` y `rol` (2 h) |
| `GET /leads/hoy` | asesor (la suya) / gerente (cualquiera de su empresa) | la cola del día, en dos colas ordenadas |
| `GET /leads/{lead_id}` | asesor (solo clientes de su cola del día) / gerente (cualquiera de su empresa) | cliente consolidado: score, factores, citas y ambos SKU |
| `GET /asesores` | gerente | asesores activos de su empresa |
| `GET /resumen` | gerente | días de cartera por punto de venta |
| `POST /pipeline/run` | n8n, con `X-Pipeline-Token` | dispara el pipeline en segundo plano (202) |

Documentación interactiva en `/api/docs`.

## Automatización

n8n (`n8n/workflow.json`, versionado) con dos nodos: Schedule Trigger a las 6:00 de Bogotá y un HTTP Request a `http://api:8000/pipeline/run` por la red interna de Docker. El token viaja en una credencial Header Auth cifrada dentro de n8n, no en el JSON exportado ni en una variable de entorno legible desde los nodos.

Si la API responde 401 o 409 (ya hay una corrida en curso), la ejecución queda en rojo en el historial de n8n.

**Limitación: un fallo dentro del pipeline no se ve en n8n.** `POST /pipeline/run` responde 202 y corre `run_all` en segundo plano, así que n8n marca la ejecución en verde antes de que empiece la primera etapa. Si una etapa falla (un error de conexión, un `ErrorDeCatalogo`, un `assert` que no se cumple), su transacción hace rollback y las etapas siguientes no corren: las anteriores quedan con los datos nuevos y desde la que falló en adelante siguen los de la corrida anterior, incluidas `scores` y `asignaciones`. Pero el error solo queda en `docker compose logs api`. La revisión diaria se hace ahí, no en el historial de n8n. La corrección sería guardar el estado de la última corrida (terminó bien o falló, con el mensaje) y mostrarlo en `GET /health` o en el resumen del gerente.

## Tests

105 tests. No buscan cobertura: cubren los casos que rompen. La carpeta `tests/` no entra a la imagen, así que se monta al correrlos:

```bash
# 70 tests puros, sin base de datos
docker compose run --rm -v ./tests:/app/tests:ro -v ./pytest.ini:/app/pytest.ini:ro api pytest -q

# los 13 de API, contra la base con el pipeline ya corrido
docker compose run --rm -e PRUEBAS_API_DATOS_REALES=1 \
  -v ./tests:/app/tests:ro -v ./pytest.ini:/app/pytest.ini:ro api pytest tests/test_api.py
```

Los 22 restantes necesitan una base desechable en `TEST_DATABASE_URL` (ver el final de este archivo) o una base con datos; sin ellas se omiten en vez de fallar, y el comando lo dice.

Ejemplos de lo que se prueba: `573223242028` normaliza a 10 dígitos, `08/15/2026` se lee como agosto, `Hnda CB 190R` resuelve por fuzzy, un duplicado entre empresas **no** se fusiona, una conversación huérfana va a cuarentena sin romper el pipeline, un asesor recibe 403 al pedir la cola de otro, y un `INSERT` cruzado falla con `violates row-level security policy`.

## Dónde está cada requisito

| Requisito | Dónde |
|---|---|
| Ingesta y limpieza de datos sucios | `backend/stages/ingest.py`, `normalize.py`; "Fechas con barra", "Contactos sin hora" |
| Unificación de leads del mismo cliente entre canales | `backend/stages/dedupe.py`; "Deduplicación" |
| Enriquecimiento con IA sobre las conversaciones | `backend/llm/`, `prompts/`; `docs/validacion.md` §1 |
| Priorización con score explicable | `backend/stages/score.py`, `backend/scoring/`; `docs/validacion.md` §2 |
| Asignación por asesor | `backend/stages/assign.py`; `docs/validacion.md` §2.5 |
| Producto consultable | `backend/api/`, `frontend/`; "Tablero: sesión, token y roles" |
| Ejecución automática diaria | `n8n/workflow.json`; "Automatización" |
| Aislamiento entre comercializadoras | `db/migrations/004_rls.sql`, `backend/api/db.py`, `tests/test_aislamiento.py` |

## Hallazgos de implementación

### RLS con `FORCE` no basta si la API se conecta como superusuario

La imagen oficial de Postgres crea `POSTGRES_USER` como superusuario, y un superusuario se salta RLS siempre, con o sin `FORCE ROW LEVEL SECURITY`. Con el compose tal cual, todas las consultas habrían devuelto las filas de las tres empresas sin ningún error.

Solución: `db/migrations/004_rls.sql` crea el rol `app_tenant` (`NOLOGIN NOSUPERUSER NOBYPASSRLS`, sin ser dueño de ninguna tabla). Cada request fija `app.empresa_id` y hace `SET LOCAL ROLE app_tenant` dentro de su transacción. El test `tests/test_aislamiento.py::test_superusuario_sin_cambiar_de_rol_se_salta_rls` deja documentado el problema.

### Sin `autocommit=True`, el contexto del tenant sobrevive al request

En psycopg 3, una conexión sin autocommit abre una transacción implícita con la primera consulta. Todo `with conn.transaction()` posterior deja de ser un `BEGIN` y pasa a ser un **savepoint** dentro de esa transacción. `SET LOCAL ROLE` y `set_config(..., true)` duran hasta el fin de la transacción externa, no del savepoint.

Se detectó al probar el esquema: una sesión *sin* empresa fijada devolvió las filas de la empresa del bloque anterior y `current_user` seguía siendo `app_tenant` después de salir del `with`. En una pool, el siguiente request que reutilizara esa conexión habría visto datos de otra empresa.

Solución: todas las conexiones se abren con `autocommit=True` (`backend/db/conexion.py`), de modo que cada `transaction()` es una transacción real. El test `test_contexto_del_tenant_no_sobrevive_a_la_transaccion` lo verifica.

### Fechas con barra: dd/mm y mm/dd conviven de verdad

En `leads.csv`, el formato `xx/xx/yyyy` mezcla las dos convenciones: `fecha_registro` trae 204 dd/mm inequívocas, **59 mm/dd inequívocas** y 265 con ambos campos ≤ 12. Un default dd/mm con reintento habría leído mal esas 59 sin ningún error, porque el registro no tiene contra qué compararse. El formato con guion (`dd-mm-yyyy`) no tiene el problema: nunca aparece un mes > 12.

Resolución en cascada (`backend/stages/normalize.py`), guardando en cada lead el método que decidió:

| Método | `fecha_registro` | `fecha_primer_contacto` |
|---|---|---|
| `formato_inequivoco` | 1.257 | 822 |
| `ventana`: solo una lectura cae entre las fechas inequívocas del dataset | 214 (57 de ellas mm/dd) | 163 |
| `coherencia`: solo una lectura es compatible con "un lead no se contacta antes de existir" | 7 | 16 |
| `mas_cercana`: dos lecturas coherentes, gana la más cercana al registro (se marca ambigua) | — | 14 |
| `irresoluble_ddmm`: nada decide, se toma dd/mm (se marca ambigua) | 22 | 0 |

De las 265 ambiguas del registro, 22 tienen día igual a mes (`08/08/2026`): se lean como se lean, son la misma fecha y no cuentan como ambiguas.

**Por qué dd/mm como default:** es el formato mayoritario entre las fechas inequívocas con barra de `fecha_registro` (204 contra 59). El argumento sale del archivo, no de la convención local. En `fecha_primer_contacto` la proporción está casi empatada (96 contra 93), pero ahí ninguna fecha llega al default.

**Registro desempatado por el contacto.** Solo usa contactos inequívocos (un contacto ambiguo se resuelve a partir del registro y sería circular). De 29 registros irresolubles por ventana, el contacto decide 7: 6 confirman dd/mm y 1 pasa a mm/dd (`LD-00243`, que con dd/mm tenía el contacto 30 días antes del registro). Una regla que confirma el default en 6 de 7 casos no está reacomodando por sesgo. Quedan 22 marcados: 11 sin contacto, 9 con contacto ambiguo y 2 con un contacto compatible con ambas lecturas.

### Contactos sin hora: el 00:00 no es un dato

`dd-mm-yyyy` no trae hora y el parser produce medianoche. Comparado con un registro del mismo día a las 08:17, el contacto quedaba "antes" del registro. Con un parser ingenuo había 129 contactos anteriores al registro. Tras resolver las fechas quedaban 62, y **61 eran este artefacto**: contacto sin hora el mismo día del registro. El restante era `LD-00243`.

Solución: columna `fecha_contacto_sin_hora` (208 leads), comparación por día de calendario cuando el contacto no tiene hora, y el mismo día nunca descarta una lectura en el desempate. El score no debe calcular horas al contacto sobre esos 208.

### Cuánto vale el "0 contactos anteriores al registro"

El flag `contacto_antes_registro` da 0 en los 1.015 leads con contacto, pero ese cero **no es validación independiente** para todos. En 37 leads la fecha se eligió justamente por dejar el contacto después del registro, y verificar después esa misma condición es circular:

| Método que usó la relación registro-contacto | Leads |
|---|---|
| `fecha_registro_metodo = coherencia` | 7 |
| `fecha_contacto_metodo = coherencia` | 16 |
| `fecha_contacto_metodo = mas_cercana` | 14 |

**El número honesto: 0 contactos anteriores al registro en los 978 leads** cuyas fechas se resolvieron sin usar esa relación (formato inequívoco o ventana, que depende solo de la distribución de las demás fechas). Ahí el cero sí es evidencia de que la cascada no introduce inconsistencias.

### Los 14 de `mas_cercana` no son datos, son una heurística

Cuando las dos lecturas del contacto son coherentes, se elige la más cercana al registro. Eso **sesga hacia contactos más rápidos**, que es justo la variable que más predice cierre en el histórico (≤ 1 h cierra 15,1 %, > 48 h cierra 5,8 %). Estos 14 leads llevan `fecha_contacto_ambigua = true`, se tratan como confianza baja y **no entran al set de validación del score**: incluirlos inflaría artificialmente la relación entre rapidez de contacto y cierre.

### Resolución de modelos: 0 sin resolver, sin SKUs inventados

`modelo_interes_texto` trae 190 variantes para 24 SKUs. Cascada en `backend/stages/resolve_models.py`, de la regla más estricta a la más permisiva, sobre el texto normalizado (minúsculas, sin tildes, espacios colapsados, `A.K.T` → `akt`, año final quitado con `\s+20\d{2}\s*$`):

| `match_method` | Filas | Textos distintos | Confianza | Ejemplo |
|---|---|---|---|---|
| `exacto` | 1.077 | 122 | 100 | `HONDA CB 190R`, `Honda Navi 2026` |
| `exacto_linea` | 100 | 24 | 100 | `CB 190R` |
| `linea_parcial` | 69 | 18 | 100 | `Honda Dio`, `Honda XR` |
| `fuzzy` | 66 | 19 | 92,31 – 97,56 | `Hnda CB 190R`, `Bajai Dominar 400` |
| `solo_marca` | 109 | 7 | 100 (sobre la marca) | `Bajaj` (97), `Bajaj Pulsar` (10), `Honda CB` (2) |
| `sin_match` | 0 | 0 | — | |
| sin texto | 79 | — | — | |

- **`linea_parcial` compara palabras completas**, no caracteres: `Honda XR` resuelve a XR 150L porque `xr` y `xre` son palabras distintas. Por caracteres serían 63 resueltos y 18 a marca, en lugar de 69 y 12.
- **Marca con línea incompleta que calza con varias líneas queda en marca sin SKU**: `Bajaj Pulsar` puede ser NS 125, NS 160 o RS 200.
- **El fuzzy (`fuzz.ratio` ≥ 85) solo recibe los errores de tipeo de marca** (`Hnda`, `Bajai`, `Heroo`, `Suzuky`), porque las reglas anteriores ya resolvieron el resto. Sobre lo que realmente le llega: ganador entre 92,31 y 97,56, segundo candidato como máximo 84,21, margen mínimo 10,53 (`Bajai Pulsar NS 125` contra NS 160). Cada fila fuzzy guarda ambos scores (`match_confidence`, `match_score_segundo`).
- **Por qué no `WRatio`:** puntúa `Bajaj Pulsar` con 90 contra NS 125 y contra NS 160, y elige uno arbitrariamente.

### Deduplicación: por persona dentro de cada empresa, nunca entre empresas

Clave de identidad `(empresa_id, telefono_normalizado)`. Un teléfono en dos comercializadoras son dos clientes: fusionarlos rompería el aislamiento del requisito 8.

| | Grupos / leads |
|---|---|
| Teléfonos repetidos (global) | 140 |
| Cruzan empresa → **no se fusionan** | 91 |
| Dentro de la misma empresa → fusionados | **49** (28 cruzan canal, 21 mismo canal) |
| Teléfono compartido con nombre incompatible (no fusionados) | 0 |
| Leads: total / canónicos / absorbidos | 1.500 / **1.451** / 49 |

- **Canónico:** `fecha_registro` más antigua, desempate por `lead_id`. En 26 de los 49 grupos el `lead_id` menor no es el que llegó primero.
- **Guarda de nombre: falta un dato sí, datos que se contradicen no.** Apellidos = las dos últimas palabras si el nombre tiene tres o más, la última si tiene dos (verificado sobre los 1.500 leads: ningún nombre de tres palabras trae nombre de pila compuesto). Se fusiona si la inicial coincide y, cuando ambos traen dos apellidos, coinciden los dos; si uno trae solo uno, basta con que ese coincida. `M. Muñoz Ramírez` contra `Marcela Muñoz Escobar` **no** se fusiona: ambos declaran dos apellidos y uno se contradice.
- **Qué requirió de verdad cada uno de los 49:**

  | `comparacion_nombre` | Pares | Qué los resuelve |
  |---|---|---|
  | `iguales` | 31 | Difieren solo en tildes o mayúsculas. Con teléfono normalizado y nombre normalizado ya son el mismo registro: la guarda no decide nada. |
  | `falta_dato` | 18 | Aquí la guarda aplica de verdad: 9 con el nombre abreviado a la inicial (`Y. Castaño Valencia`) y 9 con un solo apellido, que coincide con el primero del otro (`María Valencia` / `María Fernanda Valencia Salazar`). |
  | `contradicen` | 0 | |

  Dos tercios de las fusiones las resuelve la normalización; la guarda de nombre es la que sostiene 18.
- **`motivo_fusion`** en cada absorbido: regla, confianza (1,0, o 0,8 en los 2 grupos con una fecha de registro ambigua, porque la elección del canónico también lo es), si cruzó canal y `comparacion_nombre`.
- **El canónico no hereda datos de los absorbidos.** La cola del día debe consolidar estado y primer contacto sobre el grupo completo (41 de 49 grupos tienen estados distintos).

### Extracción con LLM: corregir una definición de negocio no es perseguir un fallo del prompt

Cinco versiones del prompt, medidas sobre una muestra fija y sobre subconjuntos dirigidos. Detalle completo en [`docs/validacion.md`](docs/validacion.md).

- **Antes de atribuir una mejora al prompt se midió el ruido del modelo** (`python -m backend.cli medir-ruido`). Con `temperature=0`, solo `intencion_declarada` varía entre llamadas idénticas.
- **Un arreglo de schema, no de texto.** El modelo escribe el JSON en el orden de las propiedades. `cuota_inicial_cop` iba antes de `forma_pago`, así que el monto se fijaba antes de saber que la compra era de contado. Reordenar eliminó la causa; agregar advertencias al prompt solo la compensaba y desplazaba errores a otros campos.
- **"Tengo como 0 millones, ¿alcanza para la inicial?"** La definición inicial decía `SI` con monto 0, aplicando el principio de reportar literal. Pero `manifesto_cuota_inicial` no es un campo literal: es una categoría que cruza con el histórico, donde `SI` cierra 11,8 % y `NO` 8,7 % (histórico sin "Sin gestión"). Un cliente con cero pesos pertenece al grupo de los que no tienen inicial, y ponerlo del otro lado contamina la variable calibrada.
  - v5 cambió la **definición de negocio**: `SI` exige un monto mayor que cero, y una cifra de cero es `NO`.
  - El acierto sobre los 35 casos pasó de ~30 % a **97 %** (68 de 70 llamadas).
  - La muestra de 10 escondía el problema por azar. Apareció al medir el subconjunto completo.
- **"No tengo inicial" sin forma de pago se resuelve aguas abajo, no con otra versión del prompt.** Si el tema de la inicial salió y el LLM dejó `forma_pago = no_informa`, el score usa `credito`: nadie que pague de contado dice "no tengo inicial". Es una regla derivada, con test, registrada en los factores del lead (28 leads). La salida del LLM queda intacta y la corrección es auditable.
- **El SKU del formulario no sirve para validar el de la conversación.** Crucé las dos fuentes esperando validación cruzada. En 590 leads coinciden el 3,6 %, contra 4,1 % esperado por azar con las distribuciones reales de cada una.
  - La coincidencia no supera el azar: en estos datos las dos señales son independientes (probablemente un artefacto del generador sintético) y no puedo usar una para validar la otra.
  - No es un error de extracción: sin LLM, el primer modelo que nombra el cliente da la misma coincidencia.
  - Por eso el acierto de la extracción se mide contra un set etiquetado a mano, no contra el formulario.
  - **El SKU no entra al score** desde `logit_v2`: el precio salió del modelo porque su peso no se distinguía del ruido. Se guardan los dos y el tablero muestra ambos cuando difieren.

### Score: dos componentes con respaldo distinto

El score **no se resume en un AUC único**, porque sus dos partes se validan de forma distinta:

- **Señales de la conversación.** `pidio_cita`, `manifesto_cuota_inicial` y `forma_pago`, con pesos derivados por regresión logística sobre el histórico.
  - Validadas fuera de pliegue con los puntos de producción: **AUC 0,552**.
  - **El top 20 % cierra 1,31x la tasa base** (13 % contra 9,75 %).
  - **Temperatura alta cierra 13,9 % y baja 7,4 %.**
  - El score separa bien los extremos y ordena mal el centro.
- **Urgencia.** No es una variable del modelo, es un **multiplicador por tramo** (≤1 h, 1–4 h, 4–24 h, 24–48 h, >48 h). Cada multiplicador se calcula como tasa de cierre del tramo sobre la tasa base: **15,1 % de cierre con contacto en menos de una hora (×1,55) contra 5,8 % pasadas 48 horas (×0,59)**.

**La tabla de urgencia se lee al revés para un lead pendiente.**
- En el histórico, las horas son **hasta** el primer contacto: el tramo describe un resultado.
- En un lead pendiente, las horas son **desde el registro sin contacto**. Estar en el tramo ≤ 1 h no significa "cerró mucho": significa que **la ventana sigue abierta**, y que si se contacta ahora cae en el tramo que históricamente cerró 15,1 %.
- **El multiplicador premia la oportunidad, no un resultado.** Un cliente ya contactado no tiene tramo: la ventana del primer contacto ya se usó.

**Solo variables que existen al momento de priorizar.** El histórico trae `horas_al_primer_contacto` y `numero_contactos`, pero un lead pendiente no tiene ninguna de las dos. **El modelo aplicable pierde 3,1 puntos de AUC (0,592 → 0,561) frente al que tendría acceso a variables que no existen al momento de priorizar.** Es una limitación honesta del problema y está documentada.

**Solo pesos que se distinguen del ruido.** Canal y precio del modelo salieron del score: sus cuatro pesos tenían intervalos bootstrap que cruzaban el cero, y sin ellos el AUC pasa de 0,561 a 0,559.

**Pesos centrados en la tasa base.**
- `SI` suma y `NO` resta, según sus log-odds frente a la tasa base.
- `NO_INFORMA` / `no_informa` vale 0 puntos: sin información, sin ajuste.
- `forma_pago = no_informa` cierra 12,3 % en el histórico, pero ahí significa "el asesor no lo registró" y en un lead actual significa "no hay conversación". Darle ese peso premiaría a los leads sin conversación por no tener información.
- Pesos en `config/score_weights.json`.

**Escala 0–100.** 50 es la tasa base: un cliente sin señales y sin urgencia queda en 50. El 0 y el 100 son la peor y la mejor combinación **alcanzable** con los pesos, sin recorte arbitrario.

**Con una sola partición, el orden de los modelos no es confiable.** Se compararon logística, SVM RBF, Random Forest y Gradient Boosting con los mismos pliegues.
- **Solo reordenar las filas** del histórico, con los mismos datos y la misma semilla, movió el AUC de la logística de 0,538 a 0,558. Con esa partición, Random Forest parecía ganar por más que su desviación.
- El 0,619 del plan inicial no se reproduce con ningún conjunto de variables.
- Las decisiones se tomaron sobre CV5 repetida con 10 semillas: ninguna familia supera a la logística por más que la desviación entre pliegues. A rendimiento igual, se eligió la que produce puntos explicables.

### Priorizar no es predecir: dos colas, temperatura por señales, capacidad por punto de venta

Los tramos de urgencia son correctos sobre probabilidad de cierre, pero para un lead pendiente **castigan haber esperado**. En un orden global, los clientes que nadie ha tocado quedaban al final (score 20 contra 50 de un contactado sin señales), que es exactamente el problema que plantea el gerente.

- **Dos colas:** `primer_contacto` (nadie del grupo contactado, 451 clientes) y `seguimiento` (ya contactados, 860). Los 140 descartados no entran a ninguna.
- **Orden dentro de cada cola:** score y, a igual score, **horas transcurridas, lo más fresco primero**. Es la urgencia en forma continua, y además disuelve los empates: 582 clientes de seguimiento tienen score 50.
- **El multiplicador de urgencia es degenerado en este corte estático.** Los 451 pendientes llevan más de 48 h a la fecha de referencia, así que todos reciben ×0,59. Se conserva porque en operación diaria los leads del día sí caen en los tramos cortos.
- **La temperatura describe la calidad del lead, no si entra hoy:** alta = dos señales positivas fuertes (cita, contado, inicial declarada), media = una, baja = ninguna. Así se puede expresar que un lead es alta y no entra hoy porque su punto de venta se llenó (16 clientes de seguimiento).
- **La capacidad es por punto de venta, no global.** Un asesor de PV-003 no atiende un lead de PV-007.
  - En cada punto de venta, primer contacto recibe ⌈pendientes / `DIAS_ABSORBER_REPRESAMIENTO`⌉ (por defecto 2 días) y seguimiento el resto.
  - Se reparte entre asesores en proporción a su capacidad, con la misma proporción entre colas. **No se suponen asesores dedicados**, porque `asesores.csv` no trae roles.
  - **La proporción se respeta mientras ambas colas tengan clientes.** Si una no llena su parte, el sobrante pasa a la otra dentro del mismo punto de venta: **el objetivo de 2 días es un mínimo, no un techo**. Resultado: 688 de 694 plazas asignadas. Las 6 libres están en PV-012, que no tiene más clientes activos.
- **Cliente fusionado: se atiende en el punto de venta de su lead más reciente**, porque refleja el interés actual. El canónico es el más antiguo; en 39 grupos los dos leads están en puntos de venta distintos.
- **Desbalance que el pipeline reporta cada día:**
  - **PV-013**, con un solo asesor activo (12 diarios), no alcanza a absorber sus 31 pendientes en 2 días y no le queda nada para seguimiento: 7,0 días de cartera.
  - **PV-014**, con un solo asesor activo, necesita 4,9 días.
  - Otros seis puntos de venta superan los 2 días de cartera.
- **El rango de la escala sale de las combinaciones posibles.** Sumar el máximo de cada variable daba +72, con contado e inicial `SI` juntos, que no pueden coexistir. El máximo real es +56.

Detalle en [`docs/validacion.md`](docs/validacion.md), secciones 2.4 y 2.5.

### Tablero: sesión, token y roles

**El token vive en `sessionStorage` y dura 2 horas.** La alternativa correcta para producción no es guardarlo en memoria, sino una **cookie `httpOnly`**: ningún script de la página puede leerla, así que un XSS no puede robar la sesión. A cambio exige protección CSRF (cookie `SameSite` más un token anti-CSRF en las peticiones que escriben) y cuidar el dominio y el `Secure` de la cookie entre la API y el frontend. En este alcance, `sessionStorage` con expiración corta es una compensación razonable:

- El token muere al cerrar la pestaña y, de todos modos, a las 2 horas (la demo dura 30 minutos).
- Angular escapa todo lo que interpola y el frontend no inserta HTML crudo en ningún lado, lo que reduce la superficie de XSS, aunque no la elimina.
- Recargar la página no cierra la sesión, cosa que sí pasaría con el token solo en memoria.

**El JWT va firmado, no cifrado:** cualquiera puede leer sus claims decodificando el base64. Por eso solo lleva identificadores: `sub` (el UUID del usuario), `empresa_id`, `asesor_id`, `rol`, y las marcas de tiempo `iat` y `exp`. No lleva nombres ni correos. El frontend lee `rol` para decidir qué pantalla mostrar, pero eso no es control de acceso: la API verifica la firma y aplica el rol y la empresa en cada request.

**Vistas del gerente.** `GET /asesores` alimenta el selector de asesor y `GET /resumen` muestra los días de cartera por punto de venta, el hallazgo de PV-013 (7,0 días) de `docs/validacion.md` §2.5. Las dos responden 403 a un asesor, y ninguna filtra por empresa en la consulta: lo hace RLS. Por eso el selector del gerente de EMP-01 nunca muestra asesores de EMP-02, y `tests/test_api.py` lo verifica contra una consulta directa.

## Qué haría con más tiempo

- **Revocar la sesión de un usuario desactivado.** Hoy `POST /auth/login` comprueba `usuarios.activo`, pero después nadie vuelve a mirar esa tabla: los endpoints confían en el token firmado. Si un usuario se desactiva, su token sigue funcionando hasta que vence. La corrección es consultar `usuarios` por el claim `sub` (el UUID del usuario) en cada request y rechazar el token si la cuenta ya no está activa; el costo es una consulta por request, evitable con una caché corta. Con tokens de 2 horas la ventana es pequeña, y por eso no se hizo. Ese es también el motivo de conservar `sub`: sin él no hay a quién revocarle nada, y un token de gerente (con `asesor_id` nulo) sería indistinguible del de cualquier otro gerente de la misma empresa.

- **Agregar la interacción cita × forma de pago al modelo.** En el histórico, pedir cita no mejora el cierre cuando el cliente va a crédito (7–11 %), y sí lo sube a 14–24 % cuando va de contado o no informa. El modelo aditivo le da +24 a la cita en los dos casos, y eso desordena los deciles del medio. Se resuelve dentro de la logística con un término de interacción; hay que validarlo con CV repetida, porque varias combinaciones tienen menos de 50 leads.

- **Probar la hipótesis del Random Forest dentro de la logística.**
  - En producción, el bosque le saca +0,019 de AUC a la logística. Está por debajo de la desviación entre pliegues (0,038) y por eso no se persiguió: no compra nada hoy.
  - La hipótesis: el precio toma solo 24 valores, uno por modelo de moto, y el bosque probablemente aprende una **tasa de cierre por modelo** que un efecto lineal del precio no puede representar.
  - Si es así, se resuelve **dentro de la logística con variables dummy por segmento** (Trabajo, Deportiva, Scooter…), sin cambiar de familia ni necesitar SHAP para explicar los factores.
  - Probarla bien exige validación cruzada repetida sobre el mismo protocolo, no una partición.

## Supuestos

- **Recencia del descarte con `fecha_registro` como fecha sustituta.**
  - En un cliente fusionado, `descartado` se resuelve por recencia: si el descarte es el estado más reciente del grupo, el cliente está descartado; si hay un estado posterior, la persona volvió y vale el estado del embudo.
  - Los datos no traen la fecha de cambio de estado, así que "más reciente" se aproxima con la `fecha_registro` de cada lead del grupo. Es una **aproximación**: un registro nuevo después del descarte se interpreta como que el cliente volvió.
  - Afecta a 13 de los 49 grupos fusionados.

- **`FECHA_REFERENCIA`, no `now()`.** La validación de fechas futuras (y más adelante la urgencia del score) usa la máxima fecha inequívoca del dataset (2026-09-14), configurable por variable de entorno. El dataset es un corte estático: con la fecha del sistema, `normalize` daría resultados distintos según el día en que se corra. En operación real la referencia sería la fecha de ejecución.

## Tests de base de datos

Necesitan una base desechable en `TEST_DATABASE_URL`. Sin ella, se omiten:

```bash
docker run -d --rm --name pg_test -e POSTGRES_USER=leads_app \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=leads_test \
  -p 55432:5432 pgvector/pgvector:0.8.6-pg18
TEST_DATABASE_URL=postgresql://leads_app:test@localhost:55432/leads_test pytest
```
