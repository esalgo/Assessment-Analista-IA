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

## Supuestos

- **`FECHA_REFERENCIA`, no `now()`.** La validación de fechas futuras (y más adelante la urgencia del score) usa la máxima fecha inequívoca del dataset (2026-09-14), configurable por variable de entorno. El dataset es un corte estático: con la fecha del sistema, `normalize` daría resultados distintos según el día en que se corra. En operación real la referencia sería la fecha de ejecución.

## Tests de base de datos

Necesitan una base desechable en `TEST_DATABASE_URL`. Sin ella, se omiten:

```bash
docker run -d --rm --name pg_test -e POSTGRES_USER=leads_app \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=leads_test \
  -p 55432:5432 pgvector/pgvector:0.8.6-pg18
TEST_DATABASE_URL=postgresql://leads_app:test@localhost:55432/leads_test pytest
```
