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

### 1.8 Pendiente

- Set de validación etiquetado a mano con acierto por campo: es la medida de acierto de la extracción (ver 1.7).
