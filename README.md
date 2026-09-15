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
- **"Tengo como 0 millones, ¿alcanza para la inicial?"** La definición inicial decía `SI` con monto 0, aplicando el principio de reportar literal. Pero `manifesto_cuota_inicial` no es un campo literal: es una categoría que cruza con el histórico, donde `SI` cierra 10,9 % contra 7,0 %. Un cliente con cero pesos pertenece al grupo de los que no tienen inicial, y ponerlo del otro lado contamina la variable calibrada.
  - v5 cambió la **definición de negocio**: `SI` exige un monto mayor que cero, y una cifra de cero es `NO`.
  - El acierto sobre los 35 casos pasó de ~30 % a **97 %** (68 de 70 llamadas).
  - La muestra de 10 escondía el problema por azar. Apareció al medir el subconjunto completo.
- **"No tengo inicial" sin forma de pago se resuelve aguas abajo, no con otra versión del prompt.** Si el tema de la inicial salió y el LLM dejó `forma_pago = no_informa`, el score usa `credito`: nadie que pague de contado dice "no tengo inicial". Es una regla derivada, con test, registrada en los factores del lead (28 leads). La salida del LLM queda intacta y la corrección es auditable.
- **El SKU del formulario no sirve para validar el de la conversación.** Crucé las dos fuentes esperando validación cruzada. En 590 leads coinciden el 3,6 %, contra 4,1 % esperado por azar con las distribuciones reales de cada una.
  - La coincidencia no supera el azar: en estos datos las dos señales son independientes (probablemente un artefacto del generador sintético) y no puedo usar una para validar la otra.
  - No es un error de extracción: sin LLM, el primer modelo que nombra el cliente da la misma coincidencia.
  - Por eso el acierto de la extracción se mide contra un set etiquetado a mano, no contra el formulario.
  - **El score usa el SKU de la conversación cuando existe**, porque lo que el cliente pide por escrito es evidencia más rica que un campo de formulario. Se guardan los dos y el tablero muestra ambos cuando difieren.

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

## Qué haría con más tiempo

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
