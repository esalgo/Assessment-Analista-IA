# Validación

## 1. Extracción con LLM

Modelo: `gpt-4o-mini`, `temperature=0`, structured outputs con JSON Schema estricto (`backend/llm/schemas.py`). Prompts versionados en `prompts/`.

### 1.1 Variabilidad del modelo: medida antes de atribuir mejoras al prompt

Con `temperature=0`, `gpt-4o-mini` no es del todo determinista. Antes de comparar versiones del prompt medí cuánto cambia la salida entre llamadas **idénticas**. Una diferencia entre versiones menor que esa variabilidad no se puede atribuir al prompt.

Reproducible con:

```bash
python -m backend.cli medir-ruido --repeticiones 3 --lead-id LD-00002 --lead-id LD-00009 ...
```

`medir-ruido` llama al LLM sin caché y sin guardar nada.

**Muestra:** los 10 leads de la sección 1.2.

| Campo | `extraccion_v3` (6 llamadas por lead) | `extraccion_v4` (3 llamadas por lead) |
|---|---|---|
| `modelo_interes_mencionado` | 0 de 10 leads | 0 de 10 |
| `forma_pago` | 0 | 0 |
| `manifesto_cuota_inicial` | 0 | 0 |
| `cuota_inicial_cop` | 0 | 0 |
| `pidio_cita` | 0 | 0 |
| `pidio_cotizacion` | 0 | 0 |
| `intencion_declarada` | **2** (LD-00002, LD-00010) | **1** (LD-00063) |
| `objecion_principal` | 0 | 0 |
| `justificacion` (redacción) | 1 | 1 |
| `confianza` | 0 | 1 |

**Conclusión:** los campos calibrables y `pidio_cotizacion` fueron estables en todas las llamadas repetidas. `intencion_declarada` oscila siempre entre `explorando` y `comparando`, así que un cambio en ese campo, en un solo lead, entre dos versiones del prompt no es evidencia de nada. Las demás diferencias entre versiones de la tabla 1.2 sí son efecto del prompt o del schema.

**Límite de la medición:** estable en la muestra no significa estable en el corpus. La sección 1.3 muestra un campo que en la muestra parecía resuelto y no lo estaba.

### 1.2 Historia del prompt sobre una muestra fija de 10 leads

La muestra se eligió a propósito para cubrir las trampas del corpus:
- dos conversaciones del mismo lead (LD-00024)
- inicial "0 millones" (LD-00063, LD-00193)
- dinero de contado con monto (LD-00044)
- centrales de riesgo o Datacrédito (LD-00002, LD-00045)
- "¿algo más económico?" (LD-00040, LD-00046)
- cliente que se retracta de la inicial (LD-00010)
- cliente que no vuelve a escribir (LD-00009)

Valores esperados según las reglas del prompt. ✔ = correcto, ✘ = incorrecto, ~ = dentro del ruido medido.

| Lead | Campo | Esperado | v1 | v2 | v3 | v4 |
|---|---|---|---|---|---|---|
| LD-00044 | `manifesto_cuota_inicial` / `cuota_inicial_cop` | `NO_INFORMA` / null (contado) | ✘ `SI` / 6.800.000 | ✔ | ✘ `NO_INFORMA` / 6.800.000 | ✔ |
| LD-00010 | `manifesto_cuota_inicial` / `cuota_inicial_cop` | `NO` / null (se retracta) | ✘ `NO` / 1.000.000 | ✘ `SI` / 1.000.000 | ✔ | ✔ |
| LD-00063 | `manifesto_cuota_inicial` / `cuota_inicial_cop` | `SI` / 0 | ✔ | ✔ | ✔ | ✘ `NO` / null |
| LD-00045 | `pidio_cita` | `NO_INFORMA` | ✔ | ✘ `NO` | ✔ | ✔ |
| LD-00045 | `pidio_cotizacion` | `NO_INFORMA` | ✔ | ✘ `NO` | ✔ | ✔ |
| LD-00024 | `pidio_cotizacion` | `NO_INFORMA` | ✔ | ✘ `SI` | ✔ | ✔ |
| LD-00044 | `pidio_cotizacion` | `NO_INFORMA` | ✔ | ✘ `NO` | ✘ `NO` | ✘ `NO` |
| LD-00193 | `intencion_declarada` | `no_informa` | ✔ | ✔ | ✘ `comparando` | ✘ `comparando` |
| LD-00002 | `intencion_declarada` | `explorando` | ✔ | ✔ | ~ `comparando` | ✔ |
| Todos | `justificacion` literal del cliente | 10 de 10 | 10 | 10 | 10 | 10 |
| Todos | violaciones de consistencia | 0 | 2 | 0 | 2 | 0 |

**La misma muestra dentro de la corrida completa con v5.**
- `forma_pago`, `manifesto_cuota_inicial` y `pidio_cita` salen correctos en los 10 leads, con la definición de negocio de v5 (LD-00063 y LD-00193 pasan a `NO`, ver sección 1.3).
- En campos sin calibración:
  - LD-00024 vuelve a marcar `pidio_cotizacion = SI` al aceptar que le separen la moto.
  - LD-00063 y LD-00193 marcan `comparando`.
  - Ambos se aceptan como error medido (sección 1.4).

Qué cambió en cada versión y por qué:

- **v1 → v2.** Reglas de inicial frente a contado, inicial ⇒ `credito`, `precio` definido por significado, objeciones `sin_inicial` e `historial_crediticio`. Corrigió los fallos de v1 y **rompió cuatro `NO_INFORMA`**: cada advertencia agregada sobre un campo empuja al modelo a pronunciarse sobre ese campo en vez de admitir que no sabe.
- **v2 → v3.** La mitad de largo (494 palabras contra 986): solo definiciones, sin advertencias. Recuperó los `NO_INFORMA` y resolvió la retractación. Reapareció el monto de contado.
- **v3 → v4.** **Cambio de schema, no de texto.** Con structured outputs el modelo escribe el JSON en el orden de las propiedades, y `cuota_inicial_cop` iba antes de `forma_pago` y `manifesto_cuota_inicial`: el modelo fijaba el monto antes de decidir que la compra era de contado. Reordenar a `forma_pago → manifesto_cuota_inicial → cuota_inicial_cop` eliminó la causa. Además, "dice que" en la definición de `comparando`.

La validación de consistencia (`backend/llm/validacion.py`) registra las violaciones sin corregirlas. Cero violaciones prueba consistencia interna, no acierto: en v2, LD-00010 no tenía violaciones y aun así estaba mal, porque resolvió la contradicción hacia el lado equivocado.

### 1.3 Inicial "0 millones": por qué validar con 10 casos no basta

**Lo que mostraba la muestra.** Tenía dos casos de inicial cero, LD-00063 y LD-00193, y los dos salían `SI` + 0 en v3, que era la regla acordada. En v4, LD-00063 pasó a `NO` de forma estable (3 de 3 llamadas). Parecía una regresión del reordenamiento del schema.

**Lo que mostró el subconjunto dirigido.** En vez de culpar a v4 con dos casos, se midieron **todas** las conversaciones donde el cliente dice "tengo (como) 0 millones / palos / millonzitos": 38 leads, 2 llamadas por lead, con v3 y con v4.

| | `NO` / null | `SI` / 0 | `NO_INFORMA` |
|---|---|---|---|
| Se retracta después ("No tengo inicial"), 3 leads: esperado `NO` | v3: 6 de 6 · v4: 6 de 6 | — | — |
| Solo dice la cifra cero, 35 leads: esperado `SI` / 0 | v3: 48 de 70 · v4: 44 de 70 | v3: 20 de 70 · v4: 24 de 70 | v3: 2 · v4: 2 |

- El modelo leía "tengo 0 millones" como "no tiene inicial" en dos tercios de las llamadas, **con v3 y con v4 por igual**. No era una regresión.
- Que los dos casos de la muestra salieran `SI` en v3 fue **azar**: la muestra de 10 escondía un fallo que afectaba a ~5 % del corpus, en un campo calibrado contra el histórico.

**La corrección fue a la definición de negocio, no al prompt.**
- La regla "`SI` + monto 0" aplicaba el principio de reportar literal. Pero `manifesto_cuota_inicial` no es un campo literal: es la categoría que cruza con el histórico, donde `SI` cierra 10,9 % contra 7,0 % sin inicial.
- Un cliente con cero pesos pertenece al grupo de los que no tienen inicial. Clasificar 35 casos como `SI` contaminaba la variable calibrada. El modelo no estaba equivocado: la definición sí.
- **v5** cambia esa definición: `SI` exige un monto mayor que cero y una cifra de cero es `NO`. El monto literal se pide igual en `cuota_inicial_cop` (0, no null): los dos campos dicen cosas distintas y está bien que difieran.

**Verificación de v5 sobre el mismo subconjunto** (no sobre la muestra de 10):

| | Resultado |
|---|---|
| Solo cifra cero, 70 llamadas: `manifesto_cuota_inicial = NO` | **66 de 70** |
| De las 4 restantes: LD-00570 (2 llamadas) | `contado` / `NO_INFORMA`, **correcto**: en una segunda conversación el cliente compra de contado, y vale lo último que dijo. La etiqueta esperada estaba mal. |
| De las 4 restantes: LD-01356 (2 llamadas) | `SI` / 0, **error** estable. Queda registrado como violación `inicial_cero_marcada_como_si`. |
| **Acierto de `manifesto_cuota_inicial`** | **68 de 70 (97,1 %)**, frente a ~30 % en v3 y v4 |
| Se retracta, 6 llamadas | 6 de 6 `NO` / null |
| `cuota_inicial_cop = 0` conservado | **1 de 66**. El modelo pone null cuando responde `NO`. Error aceptado: el monto no tiene calibración contra el histórico. |

### 1.4 Errores aceptados en campos sin calibración

Estos campos no entran al score con pesos de la regresión (ver `CLAUDE.md`, "Qué campos tienen calibración contra el histórico"). Sus fallos se aceptan como error medido y no se persiguen con más texto en el prompt.

- **`pidio_cotizacion` en LD-00044: `NO` en lugar de `NO_INFORMA`,** estable en v2, v3 y v4. Nadie mencionó una cotización; es probable que el modelo tome "¿le separo la moto?" / "Listo, sepáremela" como un cierre que reemplaza a la cotización. No se agregó una advertencia porque, como mostró v2, eso desplaza el error a otros leads.
- **`intencion_declarada`:** oscila entre `explorando` y `comparando` dentro del ruido, y en LD-00193 marca `comparando` de forma estable sin que el cliente compare nada.
- **`objecion_principal` en LD-00063:** `sin_inicial` en lugar de `precio` ante "¿No tienen usadas?". Es defendible, porque el cliente también dijo tener 0 de inicial.

- **`cuota_inicial_cop` con cifra cero:** null en lugar de 0 en 65 de 66 respuestas `NO` (sección 1.3).

### 1.5 Corrida completa con `extraccion_v5`

640 leads con conversación (665 conversaciones válidas; 25 leads tienen dos). 3 min 23 s con `Semaphore(8)`.
- **1 llamada falló** después de 5 intentos por el límite de 200K tokens por minuto (LD-00993). No detuvo la etapa.
- **La reejecución** tomó 639 de caché y envió solo esa.

**Distribución por campo:**

| Campo | Valores |
|---|---|
| `forma_pago` | credito 355 · no_informa 230 · contado 55 |
| `manifesto_cuota_inicial` | NO_INFORMA 338 · SI 222 · NO 80 |
| `pidio_cita` | NO_INFORMA 436 · SI 201 · NO 3 |
| `pidio_cotizacion` | NO_INFORMA 364 · SI 233 · NO 43 |
| `intencion_declarada` | compra_inmediata 230 · comparando 188 · explorando 171 · no_informa 51 |
| `objecion_principal` | ninguna 403 · precio 72 · sin_inicial 60 · historial_crediticio 46 · tasa 38 · cuota 21 |
| `campos_informados` (0-5) | 0: 50 · 1: 149 · 2: 28 · 3: 93 · 4: 303 · 5: 17 |

**Violaciones de consistencia registradas (no corregidas):**

| Violación | Leads | Lectura |
|---|---|---|
| `justificacion_no_literal_del_cliente` | 27 | 25 son cosméticas: el fragmento existe pero con otra mayúscula inicial ("Tengo…" dentro de "Financiada, tengo…") o entre comillas. **2 citan texto del asesor** (LD-00482, LD-01421). |
| `inicial_cero_marcada_como_si` | 1 | LD-01356 (sección 1.3). |

Las violaciones y los demás campos derivados se recalculan en cada corrida sobre las extracciones guardadas, sin llamar a la API: dependen del código de validación, no del LLM.

### 1.6 Regla derivada en el score: inicial mencionada implica crédito

En 28 leads el cliente dice "No tengo inicial" sin declarar forma de pago, y el LLM deja `forma_pago = no_informa`. La primera versión de la validación lo marcaba como violación.

**Decisión:** es `credito`, porque nadie que pague de contado dice "no tengo inicial". No se resolvió con una v6 del prompt, sino **aguas abajo, como regla derivada y visible** en la etapa score (`forma_pago_para_score` en `backend/stages/score.py`):

> si `manifesto_cuota_inicial` es `SI` o `NO` (el tema de la inicial salió) y `forma_pago` es `no_informa`, el score usa `credito` y registra la regla `inicial_mencionada_implica_credito` en sus factores.

- La salida del LLM en `extracciones_ia` queda intacta. La corrección es determinista, tiene test y es auditable lead por lead, que es distinto de reescribir la salida en silencio.
- Efecto: `forma_pago` para el score queda credito 383 · no_informa 202 · contado 55 (LLM: 355 · 230 · 55). La regla aplica en 28 leads.
- La validación ya no lo marca como violación.

### 1.7 SKU del formulario frente a SKU de la conversación: no sirven para validarse entre sí

Crucé las dos fuentes esperando una **validación cruzada**: si el LLM extrae bien el modelo, debería coincidir con el que el cliente puso en el formulario.

| | Leads |
|---|---|
| SKU por las dos vías | 590 |
| Coinciden | **21 (3,6 %)** |
| Coincidencia esperada por azar con las distribuciones reales de cada fuente, Σ p_formulario(sku) · p_conversación(sku) | **4,1 %** (24,1 leads) |
| Formulario sin SKU (solo marca o sin modelo), SKU por conversación | 50 |

**La coincidencia no supera el azar.** En estos datos las dos señales son estadísticamente independientes, así que **no puedo usar una para validar la otra**.
- Lo más probable es que sea un artefacto del generador sintético, que asignó el modelo del formulario y el de la conversación por separado.
- **No es una afirmación sobre los clientes.** No significa que 569 clientes pidieran por WhatsApp algo distinto de lo que pusieron en el formulario: los datos no permiten sostener eso.

Lo que sí se comprobó:
- **No es un error de extracción.** Sin LLM, el modelo que el cliente nombra en su primer mensaje coincide con el formulario en los mismos 21 de 590. Los 640 modelos de la conversación resolvieron por match `exacto`.
- **No depende del subgrupo.** Es igual de baja sin los clientes que cambian de modelo en la conversación, sin los que tienen dos conversaciones y en cada canal del lead (Meta Ads 5/160, WhatsApp 14/332, Formulario Web 2/98).

**Consecuencias:**
- **El acierto de la extracción no se mide contra el formulario.** Se mide contra el set de validación etiquetado a mano.
- **El score usa el SKU de la conversación cuando existe** (`sku_para_score`), y el del formulario como respaldo. Es un criterio defendible fuera de este dataset: lo que el cliente pide por escrito en una conversación es evidencia más rica que un campo de formulario. En estos datos sale de la conversación en los 640 leads con conversación.
- **Se guardan los dos** (`leads.sku` y `extracciones_ia.payload.sku_resuelto`), y el tablero muestra ambos cuando difieren. El asesor necesita ver qué puso el cliente en el formulario y qué pidió por WhatsApp.

La lista de diferencias se regenera en `data/output/sku_formulario_vs_conversacion.csv`, que no se commitea.

### 1.9 Reproducibilidad: la corrida completa repetida desde cero

El 15 de septiembre se levantó el stack con `docker compose` sobre un Postgres limpio y se corrió el pipeline completo, con **640 llamadas nuevas al LLM** (la caché vive en la base, así que no se reutilizó nada). Luego se comparó contra la corrida original, lead por lead.

| | Original | Desde cero |
|---|---|---|
| Leads / clientes / conversaciones / extracciones | 1.500 / 1.451 / 665 / 640 | idénticos |
| Cuarentena, resolución de modelos, dedupe | — | idénticos |
| Temperatura por cola | — | idéntica |
| Asignados por punto de venta y cola | 688 | idénticos |

**Lo que cambió, todo atribuible a la variabilidad del LLM** con `temperature=0`:
- **46 de 640 leads** tienen al menos un campo distinto:
  - `pidio_cotizacion` en 26;
  - `intencion_declarada` en 13;
  - `objecion_principal` en 7;
  - **campos calibrados solo en 2:** LD-01454 (`manifesto_cuota_inicial` `NO` → `NO_INFORMA`) y LD-00931 (`pidio_cita` `NO` → `NO_INFORMA`).
- **Esos 2 cambian de score:** LD-01454 pasa de 5 a 20 y LD-00931 de 45 a 50. Por eso **un cliente entra a la lista del día y otro sale** (entra LD-01454, sale LD-00887), y 16 clientes cambian de asesor u orden dentro de su punto de venta.

**Lectura:**
- La medición de ruido de la sección 1.1 se hizo sobre 10 leads y ahí `pidio_cotizacion` fue estable. En el corpus completo varía en el 4 % de los leads: otra vez, 10 casos no alcanzaban para verlo.
- Los campos que entran al score variaron en 2 de 640 leads (0,3 %).
- Por eso **la caché importa también para la estabilidad, no solo para el costo**: reejecutar el pipeline sobre la misma base no vuelve a llamar al LLM y da exactamente el mismo resultado (verificado disparando `POST /pipeline/run`).

### 1.8 Pendiente

- Set de validación etiquetado a mano con acierto por campo: es la medida de acierto de la extracción (ver 1.7).

## 2. Score

### 2.0 Qué respalda cada parte del score

El score tiene dos componentes, con respaldo distinto. **Ningún AUC de este documento mide el score completo.**

| Componente | Qué es | Respaldo |
|---|---|---|
| Señales de la conversación | `pidio_cita`, `manifesto_cuota_inicial` y `forma_pago`, con pesos en puntos | Regresión logística sobre el histórico. Puntos de producción fuera de pliegue: **AUC 0,552, lift del top 20 % 1,31x**; temperatura alta 13,9 % contra baja 7,4 % (secciones 2.1, 2.2 y 2.6) |
| Urgencia | Multiplicador por tramo de horas sin contacto. **No es una variable del modelo**: un lead pendiente todavía no tiene horas al primer contacto | Tabla de tasas de cierre del histórico por rapidez del primer contacto (sección 2.3) |

### 2.1 Comparación de familias de modelos

Reproducible con `python -m backend.scoring.comparar_modelos`. Solo mide: no entrena el modelo del score.

**Datos.** `historico_cierres` sin las 179 filas "Sin gestión", que tienen `horas_al_primer_contacto` nulo y `numero_contactos = 0`: el desenlace se filtra en las variables. Quedan 2.021 filas, con 197 cerradas (9,7 %), leídas con `ORDER BY lead_id`.

**Variables.**
- **produccion**: las que existen para un lead nuevo al momento de priorizarlo: `canal`, `manifesto_cuota_inicial`, `forma_pago`, `pidio_cita` (one-hot) y log de `precio_lista`.
- **completo**: produccion más `horas_al_primer_contacto` y `numero_contactos`, que no existen al priorizar. Solo sirve para medir el costo de la restricción.
- `empresa_id`, `punto_venta_id` y `fecha_registro` quedan fuera de ambos conjuntos, para que la diferencia entre los dos mida solo las variables no disponibles.

**Método.**
- Validación cruzada estratificada de 5 pliegues, métrica AUC, los mismos pliegues para los cuatro modelos. Por eso la diferencia contra la logística es pareada.
- Estandarización para la logística y el SVM.
- Sin ajuste de hiperparámetros: ajustarlos sobre los mismos pliegues inflaría el AUC del modelo ajustado.
- Además de la partición con semilla 42, la CV5 se repite con 10 semillas de partición.

#### Hallazgo metodológico: con una sola partición, el orden de los modelos no es confiable

> **El AUC cambió 2 puntos solo por el orden de las filas.** Con los mismos 2.021 registros y la misma semilla 42, la logística de producción dio **0,538** antes de recargar `historico_cierres` y **0,558** después. La recarga reescribió las filas, la consulta no tenía `ORDER BY` y cada fila cayó en otro pliegue. **Con esa segunda partición, Random Forest parecía ganar de verdad:** +0,029 ± 0,024, una ventaja mayor que su propia desviación pareada. Nada del modelo ni de los datos había cambiado.

Es una demostración más fuerte que la de las semillas, porque nadie eligió la partición: salió de un detalle de implementación. Con 197 positivos, el AUC depende tanto de qué filas caen en qué pliegue como del modelo:

- **Cambiar la semilla de partición** mueve el AUC medio de la logística de producción entre 0,546 y 0,575.
- **Con 10 semillas**, la ventaja de Random Forest baja a +0,019 y va de −0,001 a +0,035.
- **El AUC 0,619 del plan inicial no se reproduce con ningún conjunto de variables.** Lo más probable es que haya salido de una sola partición favorable.

Por eso:
- los datos de entrenamiento se leen con `ORDER BY lead_id`;
- se reportan las dos tablas;
- **las decisiones se toman sobre la CV repetida**, nunca sobre una partición.

#### Variables de producción

CV5 con semilla 42:

| Modelo | AUC medio | Desv. entre pliegues | Δ vs logística (media ± desv. pareada) |
|---|---|---|---|
| Regresión logística | 0.558 | 0.038 | — |
| SVM (kernel RBF) | 0.481 | 0.055 | -0.078 ± 0.039 |
| Random Forest | 0.588 | 0.031 | +0.029 ± 0.024 |
| Gradient Boosting | 0.563 | 0.060 | +0.005 ± 0.030 |

CV5 repetida con 10 semillas de partición:

| Modelo | AUC medio (10 semillas) | Rango entre semillas | Δ vs logística (rango) |
|---|---|---|---|
| Regresión logística | 0.561 | 0.546–0.575 | — |
| SVM (kernel RBF) | 0.499 | 0.469–0.521 | -0.062 (-0.089 a -0.033) |
| Random Forest | 0.580 | 0.570–0.594 | +0.019 (-0.001 a +0.035) |
| Gradient Boosting | 0.568 | 0.551–0.577 | +0.007 (-0.010 a +0.019) |

#### Todas las variables (incluye las no disponibles al priorizar)

CV5 con semilla 42:

| Modelo | AUC medio | Desv. entre pliegues | Δ vs logística (media ± desv. pareada) |
|---|---|---|---|
| Regresión logística | 0.592 | 0.044 | — |
| SVM (kernel RBF) | 0.544 | 0.021 | -0.048 ± 0.050 |
| Random Forest | 0.568 | 0.032 | -0.023 ± 0.057 |
| Gradient Boosting | 0.609 | 0.030 | +0.018 ± 0.045 |

CV5 repetida con 10 semillas de partición:

| Modelo | AUC medio (10 semillas) | Rango entre semillas | Δ vs logística (rango) |
|---|---|---|---|
| Regresión logística | 0.592 | 0.577–0.604 | — |
| SVM (kernel RBF) | 0.550 | 0.533–0.563 | -0.042 (-0.061 a -0.023) |
| Random Forest | 0.576 | 0.562–0.591 | -0.016 (-0.035 a -0.003) |
| Gradient Boosting | 0.612 | 0.591–0.627 | +0.020 (-0.003 a +0.038) |

#### Lectura y decisión

- **Con la CV repetida, ninguna familia supera a la logística por más que la desviación entre pliegues** (0,038 en producción). SVM queda por debajo; Gradient Boosting empata.
- **Random Forest en producción** saca +0,019, por debajo de esa desviación. **No se persigue.** Hay una hipótesis sin probar, escrita en el README en "Qué haría con más tiempo".
- **Decisión: regresión logística.** A rendimiento igual gana el modelo que produce un score explicable: coeficientes → puntos enteros → factores que el asesor ve por lead. Un bosque necesitaría SHAP para lo mismo.
- **Costo de la restricción:** la logística pasa de **0,592 a 0,561** (10 semillas), una pérdida de **3,1 puntos de AUC** frente a un modelo con variables que no existen al momento de priorizar. Con la semilla 42, la diferencia pareada es +0,033 ± 0,017.

### 2.2 Modelo del score: `logit_v2`

Reproducible con `python -m backend.scoring.entrenar`, que escribe `config/score_weights.json`. Es determinista: dos corridas producen el mismo archivo.

**Método.**
1. **Ajuste.** Regresión logística sin regularización (máxima verosimilitud).
2. **Centrado en la tasa base.** Cada categoría recibe su coeficiente menos el promedio, ponderado por filas del histórico, de los coeficientes de las categorías **informadas**. Un lead con información sube o baja respecto de la tasa base; uno con `NO_INFORMA` / `no_informa` queda en **0 puntos**: sin información, sin ajuste. Así `NO_INFORMA` no equivale a `NO`, el mismo cuidado que se tuvo desde la extracción.
3. **Puntos.** 1 punto = 0,01 de log-odds, redondeado a entero.
4. **Intervalo.** Percentiles 5–95 de los puntos sobre 500 remuestreos bootstrap del histórico.

| Variable | Categoría | Puntos | Intervalo 90 % | Tasa de cierre en el histórico |
|---|---|---|---|---|
| `pidio_cita` | SI | **+24** | +5 a +40 | 11,8 % (594) |
| | NO | **−10** | −17 a −2 | 8,9 % (1.427) |
| | NO_INFORMA | 0 | — | no existe en el histórico |
| `manifesto_cuota_inicial` | SI | **+16** | +5 a +30 | 11,8 % (822) |
| | NO | **−19** | −35 a −6 | 8,7 % (687) |
| | NO_INFORMA | 0 | — | 7,8 % (512) |
| `forma_pago` | contado | **+32** | +5 a +53 | 11,8 % (347) |
| | credito | **−9** | −15 a −1 | 8,4 % (1.275) |
| | no_informa | 0 | — | 12,3 % (399) |

Tasa base: 9,75 %. Los seis pesos informados tienen el signo esperado y un intervalo que no cruza el cero.

**Por qué `canal` y precio salieron (`logit_v1` → `logit_v2`).**
- En `logit_v1` sus cuatro pesos tenían intervalos que cruzaban el cero: WhatsApp −4 a +19, Formulario Web −38 a +23, Meta Ads −31 a +7, precio −2 a +50.
- Tres variables con intervalos firmes se defienden mejor que cinco con dos que no se distinguen del ruido.
- **Costo en AUC:** 0,561 con canal y precio contra **0,559 sin ellos** (CV5 repetida con 10 semillas; rango 0,545–0,571). La diferencia es 0,002, muy por debajo de la variación entre semillas.

**Por qué `forma_pago = no_informa` vale 0 aunque en el histórico cierra 12,3 %.** Es la misma etiqueta para dos cosas distintas:
- en el histórico, `no_informa` significa "el asesor no lo registró";
- en un lead actual, significa "no hay conversación".

Darle el peso del histórico (cerca de +20) premiaría a los 860 leads sin conversación por no tener información.

### 2.3 Urgencia: multiplicadores por tramo, derivados de la tabla del histórico

Tasa de cierre según las horas al primer contacto (histórico sin "Sin gestión"). El multiplicador de cada tramo lo calcula `entrenar.py`: **tasa del tramo / tasa base**. No se escribe a mano.

| Tramo | Leads | Cerrados | Tasa de cierre | Multiplicador |
|---|---|---|---|---|
| ≤ 1 h | 377 | 57 | **15,1 %** | **1,55** |
| 1–4 h | 493 | 57 | 11,6 % | 1,19 |
| 4–24 h | 604 | 47 | 7,8 % | 0,80 |
| 24–48 h | 234 | 18 | 7,7 % | 0,79 |
| > 48 h | 313 | 18 | **5,8 %** | **0,59** |

**Qué hacen los tramos, y qué no.**
- Los tramos son correctos **sobre probabilidad de cierre**: un lead contactado pasadas 48 h cierra 5,8 %.
- **Priorizar no es predecir.** Para un lead pendiente, las horas corren desde el registro sin contacto, y el multiplicador **castiga haber esperado**: cuanto más tiempo lleva sin tocar, más baja su score.
- En un orden global eso manda al final a los clientes que nadie ha tocado, justo lo contrario del problema que plantea el gerente (40 % sin contacto en 24 h). Por eso el orden se hace en **dos colas separadas** (sección 2.5), y el multiplicador no compara pendientes contra contactados.
- Un cliente ya contactado no tiene tramo: la ventana del primer contacto ya se usó. Su multiplicador es 1.

**En este corte estático, el multiplicador es degenerado para los pendientes.**
- Frente a la `FECHA_REFERENCIA` (2026-09-14 01:35), los 451 clientes pendientes en cola llevan más de 48 h desde el registro. La cola más fresca lleva 92 h.
- Todos reciben ×0,59: el multiplicador es una constante y no cambia el orden dentro de la cola. La señal más fuerte del histórico quedaría anulada.
- La razón es que el dataset es un corte fijo: el registro más reciente es del 10 de septiembre y la referencia del 14. En operación diaria, los leads del día caerían en ≤ 1 h o 1–4 h, y ahí el multiplicador sí separa.
- Se conserva por esa razón, y la urgencia se recupera en forma continua como **desempate por horas** dentro de cada cola.

### 2.4 Escala 0–100

**Mapeo.**
- tasa del cliente = sigmoide(logit(tasa base) + puntos / 100) × multiplicador
- relativo = logit(tasa del cliente) − logit(tasa base)
- **50 = tasa base:** un cliente sin señales y sin urgencia (relativo 0) queda en 50.
- **0 y 100 son la peor y la mejor combinación alcanzable**, calculadas desde los pesos, sin recorte. Por encima de 50 se escala con el máximo alcanzable y por debajo con el mínimo.

**Hallazgo: el rango real no es la suma de los extremos de cada variable.**
- La primera versión del mapeo tomaba el máximo sumando el mejor valor de cada variable: contado (+32) + inicial `SI` (+16) + cita `SI` (+24) = +72.
- **Esa combinación no puede ocurrir.** Con `forma_pago = contado`, la inicial es siempre `NO_INFORMA` por regla del prompt, y la regla `inicial_mencionada_implica_credito` también cambia `no_informa`.
- El máximo real es contado + cita = **+56**. Con +72, el 100 habría correspondido a un cliente imposible, la escala útil habría quedado comprimida y ningún cliente real habría pasado de ~72.
- `puntos_posibles` enumera las combinaciones que la extracción puede producir, pasándolas por las mismas reglas del score. Hay 15 valores posibles, de −38 a +56. Un test verifica que la combinación imposible no aparece.

**Distribución global** sobre 1.451 clientes (los 1.500 leads consolidados en sus grupos fusionados), antes de separar colas:

| Score | Clientes | Pendientes | Sin conversación | Descartados | Acumulado |
|---|---|---|---|---|---|
| 75 | 41 | 0 | 0 | 7 | 41 |
| 64 | 105 | 0 | 0 | 16 | 146 |
| 53 | 54 | 0 | 0 | 9 | 200 |
| **50** | **671** | 0 | 548 | 89 | **871** |
| 48 | 13 | 13 | 0 | 0 | 884 |
| 45 | 61 | 0 | 0 | 6 | 945 |
| 35 | 101 | 42 | 0 | 4 | 1.046 |
| 23 | 20 | 20 | 0 | 1 | 1.066 |
| **20** | **344** | 344 | 275 | 8 | 1.410 |
| 15 | 21 | 21 | 0 | 0 | 1.431 |
| 5 | 20 | 20 | 0 | 0 | 1.451 |

Dos problemas hacían inviable un orden global con umbrales de score:
1. **Solo hay 11 valores y un empate de 671 clientes en 50.** Con 694 de capacidad, ningún umbral de score se acerca: ≥ 53 son 200 clientes y ≥ 50 son 871.
2. **Los pendientes quedaban debajo de los contactados.** Un pendiente sin señales queda en 20 y un contactado sin señales en 50 (ver sección 2.3).

### 2.5 Dos colas, temperatura por señales y asignación por punto de venta

Reproducible con `python -m backend.cli score` y `python -m backend.cli assign`.

#### Colas

- **`primer_contacto`:** ningún lead del grupo contactado. 451 clientes.
- **`seguimiento`:** ya contactados. 860 clientes.
- **Fuera de cola:** estado consolidado `descartado`. 140 clientes, incluidos 9 sin contacto registrado (la inconsistencia de estado sin fecha de contacto); por eso son 451 pendientes y no 460.

**Orden dentro de cada cola:** score descendente; a igual score, **horas transcurridas ascendentes**, lo más fresco primero.
- En `primer_contacto` son horas desde el registro; en `seguimiento`, desde el primer contacto.
- El último criterio es `lead_id`: quedan 53 empates exactos de score y horas, casi todos contactos sin hora del mismo día.
- **El desempate disuelve el empate en 50.** Los 582 clientes de seguimiento con score 50 los ordena el desempate, no el score.

#### Temperatura: calidad del lead, separada de la capacidad

**El primer intento estaba fundido con la capacidad.**
- La temperatura salía de la posición: `alta` = entra hoy, `media` = mañana, `baja` = el resto.
- Con 2 días para absorber, `baja` quedaba vacía en las dos colas, así que la temperatura no informaba ninguna decisión.

**Ahora describe la calidad del lead según sus señales** (`temperatura_por_senales`):
- **alta** = dos señales positivas fuertes;
- **media** = una;
- **baja** = ninguna.
- Las señales fuertes son `pidio_cita = SI`, `forma_pago = contado` y `manifesto_cuota_inicial = SI`. Como contado e inicial `SI` no coexisten, el máximo son dos.

| Cola | Alta | Media | Baja |
|---|---|---|---|
| `primer_contacto` | 55 | 19 | 377 |
| `seguimiento` | 123 | 45 | 692 |
| descartado | 23 | 10 | 107 |

**Quién se atiende hoy lo decide la capacidad** (siguiente sección). Ahora se puede expresar lo que antes no: **16 clientes de seguimiento con temperatura alta (12) o media (4) no entran hoy** porque la capacidad de su punto de venta se llenó.

#### Asignación: capacidad por punto de venta, no global

Un asesor de PV-003 no puede atender un lead de PV-007: repartir desde el agregado de 694 asignaría leads que nadie puede trabajar. Por cada punto de venta:

1. **Capacidad** = suma de `capacidad_diaria_leads` de sus asesores activos.
2. **Objetivo entre colas:** primer contacto = ⌈pendientes / `DIAS_ABSORBER_REPRESAMIENTO`⌉, con tope en la capacidad; seguimiento = el resto.
3. **Traslado de sobrante** (`trasladar_sobrante`): si una cola tiene menos clientes que su parte, lo que sobra pasa a la otra, en cualquier sentido y solo dentro del mismo punto de venta.
4. **Reparto entre asesores, proporcional a su capacidad y con la misma proporción entre colas para todos.**
   - No hay asesores dedicados: `asesores.csv` no trae nada que distinga roles, y suponerlos sería decidir en silencio.
   - Primero se reparten las cuotas de primer contacto (método del resto mayor) y luego seguimiento, sobre la capacidad que le queda a cada asesor. Así nadie supera la suya, ni por redondeo ni por el traslado.
5. **Cada lead**, en orden de prioridad, va al asesor con más cuota libre en proporción a la suya, para que los mejores leads no se concentren en uno.

**La proporción entre colas se respeta mientras ambas tengan clientes.**
- Cuando una se agota, su capacidad sobrante pasa a la otra.
- **El objetivo de 2 días es un mínimo, no un techo:** si seguimiento no llena su parte, primer contacto recibe más de ⌈pendientes / 2⌉.
- Sin el traslado, PV-001 dejaba 15 plazas sin usar con 12 pendientes esperando, y PV-012 dejaba 18 con 13 pendientes.
- **Rama inalcanzable, declarada:** con la fórmula actual el traslado solo va de seguimiento a primer contacto. El objetivo de primer contacto es ⌈pendientes / días⌉ ≤ pendientes, así que esa cola nunca deja sobrante y **el traslado de primer contacto hacia seguimiento no se ejecuta nunca** en el pipeline. Se deja por simetría, marcada con un comentario en `trasladar_sobrante`, y cubierta por un test que llama a la función directamente. Solo se volvería alcanzable si cambia la fórmula del objetivo, por ejemplo con un tope fijo para primer contacto.

**Resultado: 688 de 694 plazas asignadas.**
- **Las 6 libres están en PV-012:** 86 de capacidad y solo 80 clientes activos, no queda nadie más a quién asignar.
- En los otros 14 puntos de venta la capacidad se usa completa.

**Verificado:** ningún asesor supera su capacidad, ningún cliente va a un asesor de otro punto de venta, y no hay plazas libres en ningún punto de venta con clientes activos sin asignar.

| PV | Asesores | Capacidad | Pendientes | Seguimiento | Objetivo primer / seguim. | Asignados primer / seguim. | Libres | Días de cartera |
|---|---|---|---|---|---|---|---|---|
| PV-001 | 4 | 77 | 24 | 55 | 12 / 65 | **22** / 55 | 0 | 1,0 |
| PV-002 | 4 | 63 | 29 | 50 | 15 / 48 | 15 / 48 | 0 | 1,3 |
| PV-003 | 4 | 66 | 36 | 57 | 18 / 48 | 18 / 48 | 0 | 1,4 |
| PV-004 | 2 | 32 | 25 | 55 | 13 / 19 | 13 / 19 | 0 | **2,5** |
| PV-005 | 2 | 40 | 32 | 57 | 16 / 24 | 16 / 24 | 0 | **2,2** |
| PV-006 | 2 | 35 | 30 | 67 | 15 / 20 | 15 / 20 | 0 | **2,8** |
| PV-007 | 2 | 24 | 26 | 51 | 13 / 11 | 13 / 11 | 0 | **3,2** |
| PV-008 | 3 | 60 | 42 | 58 | 21 / 39 | 21 / 39 | 0 | 1,7 |
| PV-009 | 3 | 55 | 32 | 64 | 16 / 39 | 16 / 39 | 0 | 1,7 |
| PV-010 | 2 | 27 | 20 | 63 | 10 / 17 | 10 / 17 | 0 | **3,1** |
| PV-011 | 4 | 60 | 33 | 56 | 17 / 43 | 17 / 43 | 0 | 1,5 |
| PV-012 | 4 | 86 | 26 | 54 | 13 / 73 | **26** / 54 | **6** | 0,9 |
| PV-013 | 1 | 12 | 31 | 53 | 12 / 0 | 12 / 0 | 0 | **7,0** |
| PV-014 | 1 | 20 | 33 | 65 | 17 / 3 | 17 / 3 | 0 | **4,9** |
| PV-015 | 2 | 37 | 32 | 55 | 16 / 21 | 16 / 21 | 0 | **2,4** |

Días de cartera = (pendientes + seguimiento) / capacidad.

**Desbalance entre demanda y capacidad, información para el gerente:**
- **PV-013 no alcanza a absorber sus 31 pendientes en 2 días:** tiene un solo asesor activo (12 diarios) y otro inactivo, y toda su capacidad se va a primer contacto sin dejar nada para seguimiento. Su cartera activa tarda 7,0 días.
- **PV-014** tiene el mismo patrón (un activo, un inactivo, 20 diarios): 4,9 días de cartera y solo 3 plazas para seguimiento.
- **PV-004, PV-005, PV-006, PV-007, PV-010 y PV-015** tienen más cartera activa que la que atienden en 2 días (entre 2,2 y 3,2 días).

#### Días de cartera por punto de venta: lo que el gerente no preguntó

Días de cartera = clientes activos (pendientes + seguimiento) / capacidad diaria de los asesores activos. Ordenado de mayor a menor.

| # | PV | Empresa | Asesores activos (inactivos) | Capacidad diaria | Pendientes | Seguimiento | Cartera activa | Días de cartera |
|---|---|---|---|---|---|---|---|---|
| 1 | **PV-013** | EMP-03 | 1 (1) | 12 | 31 | 53 | 84 | **7,0** |
| 2 | **PV-014** | EMP-03 | 1 (1) | 20 | 33 | 65 | 98 | **4,9** |
| 3 | PV-007 | EMP-02 | 2 | 24 | 26 | 51 | 77 | 3,2 |
| 4 | PV-010 | EMP-02 | 2 | 27 | 20 | 63 | 83 | 3,1 |
| 5 | PV-006 | EMP-02 | 2 | 35 | 30 | 67 | 97 | 2,8 |
| 6 | PV-004 | EMP-01 | 2 | 32 | 25 | 55 | 80 | 2,5 |
| 7 | PV-015 | EMP-03 | 2 | 37 | 32 | 55 | 87 | 2,4 |
| 8 | PV-005 | EMP-01 | 2 | 40 | 32 | 57 | 89 | 2,2 |
| 9 | PV-009 | EMP-02 | 3 | 55 | 32 | 64 | 96 | 1,7 |
| 10 | PV-008 | EMP-02 | 3 | 60 | 42 | 58 | 100 | 1,7 |
| 11 | PV-011 | EMP-03 | 4 | 60 | 33 | 56 | 89 | 1,5 |
| 12 | PV-003 | EMP-01 | 4 | 66 | 36 | 57 | 93 | 1,4 |
| 13 | PV-002 | EMP-01 | 4 | 63 | 29 | 50 | 79 | 1,3 |
| 14 | PV-001 | EMP-01 | 4 | 77 | 24 | 55 | 79 | 1,0 |
| 15 | PV-012 | EMP-03 | 4 | 86 | 26 | 54 | 80 | 0,9 |
| | **Total** | | 40 (2) | 694 | 451 | 860 | 1.311 | 1,9 |

**Lectura:**
- **La demanda es casi pareja y la capacidad no.** Cada punto de venta tiene entre 77 y 100 clientes activos, pero la capacidad diaria va de 12 a 86: siete veces más en un extremo que en el otro.
- **PV-013 y PV-012 tienen la misma cartera** (84 y 80 clientes) y son de la misma empresa (EMP-03). Uno tarda 7,0 días en atenderla; el otro, 0,9, y hoy le sobran 6 plazas.
- **Los dos puntos de venta con peor cartera son los únicos con un asesor inactivo.** El problema no es el volumen de leads, es la dotación.
- **El pipeline no traslada leads entre puntos de venta:** un asesor solo atiende los de su punto de venta. Reasignar personal dentro de EMP-03 es una decisión del gerente, y este reporte es el insumo.

#### Cliente fusionado: punto de venta del lead más reciente

- `dedupe` elige como canónico el lead con **`fecha_registro` más antigua** (desempate por `lead_id`), así que el canónico nunca es el más reciente.
- Para asignar se usa el punto de venta del **lead más reciente** del grupo, porque refleja el interés actual del cliente. Se guarda en `scores.punto_venta_id`.
- En 39 de los 49 grupos fusionados los dos leads están en puntos de venta distintos, siempre de la misma empresa. En los 39 el absorbido es el más reciente, así que los 39 se atienden en el punto de venta del absorbido.
- De esos 39: 32 van a seguimiento, 1 a primer contacto y 6 quedan fuera por descartados. **18 entran hoy.**
- **Efecto a vigilar:** la regla lleva 2 clientes a PV-013 (LD-00528 y LD-00564), el punto de venta más saturado, y 1 alta a PV-014 (LD-01146) que no entra hoy.

| Canónico | PV · registro · estado del canónico | Absorbido | PV asignado · registro · estado del absorbido | Cola | Temperatura | Entra hoy |
|---|---|---|---|---|---|---|
| LD-00004 | PV-002 · 2026-08-03 · sin_gestion | LD-00052 | **PV-004** · 2026-08-06 · descartado | descartado | baja | no |
| LD-00091 | PV-004 · 2026-08-06 · en_proceso | LD-00920 | **PV-002** · 2026-08-23 · sin_gestion | seguimiento | alta | sí |
| LD-00122 | PV-003 · 2026-08-02 · sin_gestion | LD-00294 | **PV-001** · 2026-08-07 · contactado | seguimiento | baja | sí |
| LD-00201 | PV-008 · 2026-08-14 · descartado | LD-01163 | **PV-009** · 2026-08-20 · en_proceso | seguimiento | baja | sí |
| LD-00235 | PV-006 · 2026-08-04 · contactado | LD-00730 | **PV-008** · 2026-08-30 · no_contesta | seguimiento | baja | no |
| LD-00308 | PV-006 · 2026-08-11 · contactado | LD-00991 | **PV-009** · 2026-08-31 · contactado | seguimiento | media | sí |
| LD-00336 | PV-013 · 2026-08-10 · contactado | LD-00954 | **PV-011** · 2026-08-11 · sin_gestion | seguimiento | alta | sí |
| LD-00387 | PV-002 · 2026-08-22 · sin_gestion | LD-01032 | **PV-003** · 2026-08-26 · en_proceso | seguimiento | alta | sí |
| LD-00404 | PV-008 · 2026-08-02 · en_proceso | LD-01330 | **PV-007** · 2026-08-30 · cotizacion_enviada | seguimiento | baja | no |
| LD-00411 | PV-004 · 2026-08-27 · en_proceso | LD-00807 | **PV-001** · 2026-08-29 · cotizacion_enviada | seguimiento | baja | sí |
| LD-00414 | PV-002 · 2026-09-01 · no_contesta | LD-00353 | **PV-003** · 2026-09-06 · descartado | descartado | media | no |
| LD-00434 | PV-012 · 2026-08-25 · descartado | LD-00320 | **PV-011** · 2026-08-31 · descartado | descartado | baja | no |
| LD-00449 | PV-009 · 2026-08-02 · contactado | LD-00615 | **PV-010** · 2026-08-04 · cotizacion_enviada | seguimiento | baja | no |
| LD-00455 | PV-003 · 2026-08-09 · no_contesta | LD-00972 | **PV-002** · 2026-08-24 · sin_gestion | seguimiento | media | sí |
| LD-00514 | PV-003 · 2026-08-11 · sin_gestion | LD-00273 | **PV-001** · 2026-08-20 · contactado | seguimiento | baja | sí |
| LD-00528 | PV-014 · 2026-08-06 · sin_gestion | LD-00265 | **PV-013** · 2026-08-25 · en_proceso | seguimiento | baja | no |
| LD-00564 | PV-011 · 2026-08-21 · descartado | LD-01449 | **PV-013** · 2026-09-04 · no_contesta | seguimiento | baja | no |
| LD-00640 | PV-007 · 2026-08-11 · contactado | LD-01117 | **PV-009** · 2026-09-07 · descartado | descartado | alta | no |
| LD-00694 | PV-004 · 2026-08-13 · en_proceso | LD-00412 | **PV-001** · 2026-09-05 · contactado | seguimiento | alta | sí |
| LD-00769 | PV-003 · 2026-08-30 · sin_gestion | LD-00061 | **PV-004** · 2026-09-04 · cotizacion_enviada | seguimiento | baja | no |
| LD-00811 | PV-008 · 2026-08-03 · descartado | LD-00133 | **PV-010** · 2026-09-08 · no_contesta | seguimiento | baja | no |
| LD-00814 | PV-010 · 2026-08-02 · cotizacion_enviada | LD-01350 | **PV-006** · 2026-09-07 · cotizacion_enviada | seguimiento | baja | no |
| LD-00855 | PV-009 · 2026-08-18 · sin_gestion | LD-00072 | **PV-010** · 2026-09-04 · contactado | seguimiento | baja | no |
| LD-00858 | PV-012 · 2026-08-22 · contactado | LD-01306 | **PV-015** · 2026-09-05 · sin_gestion | seguimiento | alta | sí |
| LD-00890 | PV-008 · 2026-09-03 · sin_gestion | LD-00042 | **PV-006** · 2026-09-08 · sin_gestion | primer_contacto | baja | sí |
| LD-00950 | PV-010 · 2026-09-02 · sin_gestion | LD-00073 | **PV-009** · 2026-09-05 · no_contesta | seguimiento | baja | no |
| LD-00975 | PV-006 · 2026-08-14 · descartado | LD-01333 | **PV-009** · 2026-08-24 · contactado | seguimiento | baja | no |
| LD-01070 | PV-001 · 2026-08-01 · contactado | LD-01164 | **PV-004** · 2026-09-06 · descartado | descartado | media | no |
| LD-01115 | PV-009 · 2026-08-15 · no_contesta | LD-00981 | **PV-008** · 2026-09-08 · sin_gestion | seguimiento | baja | sí |
| LD-01146 | PV-011 · 2026-08-02 · descartado | LD-00850 | **PV-014** · 2026-08-11 · contactado | seguimiento | alta | no |
| LD-01271 | PV-002 · 2026-08-06 · contactado | LD-00034 | **PV-004** · 2026-08-23 · no_contesta | seguimiento | baja | no |
| LD-01283 | PV-008 · 2026-08-05 · sin_gestion | LD-00328 | **PV-007** · 2026-08-09 · cotizacion_enviada | seguimiento | alta | sí |
| LD-01298 | PV-003 · 2026-08-19 · descartado | LD-00703 | **PV-005** · 2026-08-22 · sin_gestion | seguimiento | baja | no |
| LD-01336 | PV-001 · 2026-08-08 · no_contesta | LD-00200 | **PV-005** · 2026-08-20 · descartado | descartado | baja | no |
| LD-01344 | PV-015 · 2026-08-21 · contactado | LD-01390 | **PV-011** · 2026-09-04 · contactado | seguimiento | baja | sí |
| LD-01385 | PV-007 · 2026-08-24 · contactado | LD-00581 | **PV-009** · 2026-08-25 · cotizacion_enviada | seguimiento | baja | sí |
| LD-01391 | PV-014 · 2026-08-05 · cotizacion_enviada | LD-01182 | **PV-011** · 2026-09-06 · sin_gestion | seguimiento | baja | no |
| LD-01430 | PV-003 · 2026-08-25 · descartado | LD-00214 | **PV-001** · 2026-08-31 · contactado | seguimiento | baja | sí |
| LD-01438 | PV-005 · 2026-08-06 · descartado | LD-00783 | **PV-002** · 2026-08-07 · contactado | seguimiento | baja | sí |

### 2.6 Validación del score sobre el histórico: deciles, lift y temperatura

Reproducible con `python -m backend.scoring.validar_score`.

**Qué se valida.**
- El **componente de señales** con los puntos que usa producción (`NO_INFORMA` / `no_informa` = 0). La urgencia tiene su propia tabla (sección 2.3) y no se mezcla aquí.
- **Predicciones fuera de pliegue:** los puntos de cada lead salen de pesos entrenados sin ese lead, en CV5 repetida con 10 semillas.
- **Empates:** hay muchos, así que los deciles se forman desempatando al azar y se promedian las 10 repeticiones.
- **Sin la regla `inicial_mencionada_implica_credito`.** Esa regla describe cómo el LLM llena `forma_pago` en una conversación. En el histórico cambiaría 318 filas donde un asesor registró `no_informa`, que cierran **12,9 %**, por encima de la base. Aplicarla baja el AUC de 0,552 a 0,544 y el lift del top 20 % de 1,31x a 1,30x.

**AUC de los puntos de producción: 0,552** (rango entre repeticiones 0,545–0,566). Es menor que el 0,559 de la sección 2.2 porque ese número mide la probabilidad del modelo, que sí usa el coeficiente de `no_informa`. El score que se aplica pone esas categorías en 0, y es el que se valida.

#### Tasa de cierre por decil de puntos

| Decil (1 = mayor puntaje) | Tasa de cierre (media 10 rep.) | Rango entre repeticiones | Lift vs base |
|---|---|---|---|
| 1 | 13,5 % | 10,8 %–14,8 % | **1,38x** |
| 2 | 12,1 % | 10,4 %–13,4 % | 1,24x |
| 3 | 8,9 % | 7,4 %–10,9 % | 0,91x |
| 4 | 10,7 % | 7,9 %–12,4 % | 1,10x |
| 5 | 9,1 % | 6,4 %–10,9 % | 0,93x |
| 6 | 10,6 % | 9,4 %–12,4 % | 1,09x |
| 7 | 10,4 % | 8,4 %–12,9 % | 1,07x |
| 8 | 6,2 % | 4,0 %–7,9 % | 0,63x |
| 9 | 6,8 % | 5,0 %–9,4 % | 0,70x |
| 10 | 9,2 % | 7,9 %–9,9 % | 0,94x |

Tasa base: 9,75 %.

**Lift del top 20 %: 1,31x** (13 % de cierre contra 9,75 %). El mínimo entre repeticiones es 1,22x.

**Lectura.**
- **Los dos deciles de arriba sí separan:** 13,5 % y 12,1 %, con lift por encima de 1,2x en todas las repeticiones.
- **La parte baja también:** los deciles 8 y 9 cierran 6–7 %.
- **El medio no está ordenado** (deciles 3 a 7 entre 8,9 % y 10,7 %), y **el decil 10 vuelve a 9,2 %**. El score separa los extremos, pero no ordena bien el centro.

#### Tasa de cierre por combinación de señales

Descriptiva: no usa pesos, así que no tiene fuga.

| Cita | Inicial | Forma de pago | Leads | Tasa de cierre | Lift vs base |
|---|---|---|---|---|---|
| SI | SI | contado | 34 | 23,5 % | 2,41x |
| SI | SI | no_informa | 46 | 19,6 % | 2,01x |
| SI | NO | contado | 37 | 18,9 % | 1,94x |
| SI | NO | no_informa | 46 | 17,4 % | 1,78x |
| SI | NO_INFORMA | contado | 28 | 14,3 % | 1,47x |
| NO | NO_INFORMA | no_informa | 55 | 12,7 % | 1,31x |
| NO | NO_INFORMA | contado | 64 | 12,5 % | 1,28x |
| NO | SI | no_informa | 139 | 11,5 % | 1,18x |
| SI | SI | credito | 142 | 11,3 % | 1,16x |
| NO | SI | credito | 368 | 10,6 % | 1,09x |
| NO | SI | contado | 93 | 9,7 % | 0,99x |
| NO | NO | no_informa | 87 | 9,2 % | 0,94x |
| NO | NO | credito | 286 | 7,7 % | 0,79x |
| SI | NO_INFORMA | credito | 95 | 7,4 % | 0,76x |
| SI | NO | credito | 140 | 7,1 % | 0,73x |
| NO | NO | contado | 91 | 5,5 % | 0,56x |
| NO | NO_INFORMA | credito | 244 | 5,3 % | 0,55x |
| SI | NO_INFORMA | no_informa | 26 | 3,8 % | 0,39x |

**Hallazgo: pedir cita solo ayuda cuando no es crédito.**
- Con crédito, pedir cita no mejora el cierre: 11,3 %, 7,4 % y 7,1 % según la inicial.
- Sin crédito (contado o sin informar), pedir cita lo sube a 14–24 %.
- Es una **interacción**, y el modelo aditivo le suma +24 a la cita sin importar la forma de pago. Eso explica buena parte del desorden de los deciles del medio.
- Ojo con los tamaños: varias combinaciones tienen entre 26 y 46 leads, y con 30 leads una tasa del 20 % tiene un intervalo de ±14 puntos. La dirección del efecto se repite en las tres combinaciones con crédito y en las cuatro sin crédito con cita.
- **No se corrigió:** agregar la interacción cita × forma de pago es un cambio de modelo, y queda en el README en "Qué haría con más tiempo".

#### Temperatura × desenlace

La temperatura es una regla sobre las señales, sin parámetros entrenados, así que no necesita validación cruzada.

| Temperatura | Cerrado | Perdido | Total | Tasa de cierre | Lift vs base |
|---|---|---|---|---|---|
| alta | 53 | 327 | 380 | **13,9 %** | **1,43x** |
| media | 94 | 875 | 969 | 9,7 % | 1,00x |
| baja | 50 | 622 | 672 | **7,4 %** | **0,76x** |

- **La temperatura ordena de forma monótona:** una lead alta cierra casi el doble que una baja (13,9 % contra 7,4 %).
- Separa mejor que el orden fino del score, porque agrupa las señales en tres niveles en vez de sumar pesos que no capturan la interacción.

