# Set de validación — etiquetado manual

Etiqueta **antes** de mirar la salida del modelo. Deja el valor que dirías tú leyendo la conversación.

Valores: `forma_pago` contado/credito/no_informa · `manifesto_cuota_inicial` SI/NO/NO_INFORMA · `pidio_cita` SI/NO/NO_INFORMA · `pidio_cotizacion` SI/NO/NO_INFORMA · `intencion` compra_inmediata/comparando/explorando/descartado/no_informa · `objecion` precio/tasa/cuota/disponibilidad/tramites/historial_crediticio/sin_inicial/ninguna/otra

---


## LD-00020 — WhatsApp

*Por qué está aquí: cliente casi no habla, asesor lleva la conversación*

- **cliente**: Qsé, estoy averiguando por la Honda Dio 110
- **asesor**: ¡Buen día! Con mucho gusto le colaboro. La Honda Dio 110 está en $6.890.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **asesor**: ¿Sigue interesado? quedo atento

```
modelo_mencionado      = Honda Dio 110
forma_pago             = no_informa
manifesto_cuota_inicial= NO_INFORMA
cuota_inicial_cop      = null
pidio_cita             = NO_INFORMA
pidio_cotizacion       = NO_INFORMA
intencion              = no_informa
objecion               = ninguna
```


## LD-00052 — formulario web

*Por qué está aquí: cliente casi no habla, asesor lleva la conversación*

- **cliente**: Buenos días, quiero información de la Bajaj Pulsar NS 160
- **asesor**: ¡Hola! Con mucho gusto le colaboro. La Bajaj Pulsar NS 160 está en $11.290.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **asesor**: ¿Sigue interesado? quedo atento

```
modelo_mencionado      = Bajaj Pulsar NS 160
forma_pago             = no_informa
manifesto_cuota_inicial= NO_INFORMA
cuota_inicial_cop      = null
pidio_cita             = NO_INFORMA
pidio_cotizacion       = NO_INFORMA
intencion              = no_informa
objecion               = ninguna
```


## LD-00160 — WhatsApp

*Por qué está aquí: dos conversaciones del mismo lead*


**Conversación 1** (2026-08-12 11:54:00)

- **cliente**: Qué más pues, me interesa la Suzuki Best 125
- **asesor**: ¡Buenas! Con mucho gusto le colaboro. La Suzuki Best 125 está en $6.590.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Era por curiosidad nomás
- **cliente**: Voy a consultar en la casa y le digo
- **asesor**: Sin problema, cualquier cosa quedo atento por acá
- **cliente**: Dale pues

**Conversación 2** (2026-08-19 11:54:00)

- **cliente**: Hola buenas, quiero información de la Bajaj Dominar 400
- **asesor**: ¡Hola! Con mucho gusto le colaboro. La Bajaj Dominar 400 está en $24.900.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada, tengo 2000mil para la inicial
- **asesor**: Perfecto. ¿Usted tiene cómo demostrar ingresos? Le puedo dejar el estudio de crédito adelantado
- **cliente**: Claro, tengo contrato indefinido
- **cliente**: ¿Puedo pasar mañana a la sede a verla?
- **asesor**: Claro que sí, lo esperamos. Estamos de 8 a 6, ¿le separo la moto mientras tanto?
- **cliente**: Listo, sepáremela

```
modelo_mencionado      = Bajaj Dominar 400
forma_pago             = credito
manifesto_cuota_inicial= SI
cuota_inicial_cop      = 2000000
pidio_cita             = SI
pidio_cotizacion       = NO_INFORMA / Dudé en elegir
intencion              = compra_inmediata
objecion               = ninguna
```


## LD-00209 — WhatsApp

*Por qué está aquí: dos conversaciones del mismo lead*


**Conversación 1** (2026-09-01 18:21:00)

- **cliente**: Hola, vi el anuncio de la Hero Eco Deluxe 100
- **asesor**: ¡Hola buenas! Con mucho gusto le colaboro. La Hero Eco Deluxe 100 está en $4.990.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada. Tengo como 1 millones, ¿alcanza para la inicial?
- **asesor**: Con esa inicial la cuota le queda alrededor de $410.000 a 48 meses.
- **cliente**: Estoy en centrales
- **asesor**: Le entiendo. ¿Le mando la cotización formal al WhatsApp para que la revise con calma?
- **cliente**: Listo, envíemela

**Conversación 2** (2026-09-05 18:21:00)

- **cliente**: Qsé, estoy averiguando por la Bajaj Pulsar NS 125
- **asesor**: ¡Qué más pues! Con mucho gusto le colaboro. La Bajaj Pulsar NS 125 está en $8.990.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: De contado, ya tengo la plata lista, 9,0 millones
- **asesor**: Perfecto. ¿Usted tiene cómo demostrar ingresos? Le puedo dejar el estudio de crédito adelantado
- **cliente**: Claro, tengo contrato indefinido
- **cliente**: ¿A qué hora los puedo visitar hoy?
- **asesor**: Claro que sí, lo esperamos. Estamos de 8 a 6, ¿le separo la moto mientras tanto?
- **cliente**: Listo, sepáremela

```
modelo_mencionado      = Bajaj Pulsar NS 125
forma_pago             = contado
manifesto_cuota_inicial= NO_INFORMA
cuota_inicial_cop      = null
pidio_cita             = SI
pidio_cotizacion       = SI
intencion              = compra_inmediata
objecion               = ninguna
```


## LD-00022 — WhatsApp

*Por qué está aquí: objeción de historial crediticio (centrales/Datacrédito)*

- **cliente**: Buenos días, estoy averiguando por la Suzuki GN 125
- **asesor**: ¡Hola! Con mucho gusto le colaboro. La Suzuki GN 125 está en $7.490.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada. Tengo como $800.000, ¿alcanza para la inicial?
- **asesor**: Con esa inicial la cuota le queda alrededor de $320.000 a 48 meses.
- **cliente**: Tengo un reporte viejo en centrales, ¿eso afecta?
- **asesor**: Le entiendo. ¿Le mando la cotización formal al WhatsApp para que la revise con calma?
- **cliente**: Bueno, mándela y yo le digo

```
modelo_mencionado      = Suzuki GN 125
forma_pago             = credito
manifesto_cuota_inicial= SI
cuota_inicial_cop      = 800000
pidio_cita             = NO_INFORMA
pidio_cotizacion       = SI
intencion              = explorando
objecion               = historial_crediticio
```


## LD-00030 — WhatsApp

*Por qué está aquí: dice que no tiene inicial*

- **cliente**: Hola buenas, vi el anuncio de la Suzuki GN 125
- **asesor**: ¡Qué más pues! Con mucho gusto le colaboro. La Suzuki GN 125 está en $7.490.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Estoy es comparando por ahora
- **cliente**: No tengo inicial
- **asesor**: Sin problema, cualquier cosa quedo atento por acá
- **cliente**: Ok

```
modelo_mencionado      = Suzuki GN 125
forma_pago             = no_informa
manifesto_cuota_inicial= NO_INFORMA
cuota_inicial_cop      = null
pidio_cita             = NO_INFORMA
pidio_cotizacion       = NO_INFORMA
intencion              = comparando
objecion               = ninguna
```


## LD-00068 — WhatsApp

*Por qué está aquí: monto cero ("0 millones")*

- **cliente**: Buen día, vi el anuncio de la AKT Dynamic R3 125
- **asesor**: ¡Buen día! Con mucho gusto le colaboro. La AKT Dynamic R3 125 está en $5.590.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada. Tengo como como 0 millonzitos, ¿alcanza para la inicial?
- **asesor**: Con esa inicial la cuota le queda alrededor de $410.000 a 48 meses.
- **cliente**: Estoy mirando también otra marca
- **asesor**: Le entiendo. ¿Le mando la cotización formal al WhatsApp para que la revise con calma?
- **cliente**: Sí porfa, mándemela

```
modelo_mencionado      = AKT Dynamic R3 125
forma_pago             = credito
manifesto_cuota_inicial= SI
cuota_inicial_cop      = 0
pidio_cita             = NO_INFORMA
pidio_cotizacion       = SI
intencion              = explorando
objecion               = ninguna
```


## LD-00018 — FORMULARIO WEB

*Por qué está aquí: monto en jerga (palos/millonzitos/1200mil)*

- **cliente**: Buenas tardes, estoy averiguando por la Honda Navi
- **asesor**: ¡Qué más pues! Con mucho gusto le colaboro. La Honda Navi está en $7.290.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada, tengo como 2 millonzitos para la inicial
- **asesor**: Perfecto. ¿Usted tiene cómo demostrar ingresos? Le puedo dejar el estudio de crédito adelantado
- **cliente**: Sí señor, trabajo en empresa con contrato fijo
- **cliente**: ¿Puedo pasar mañana a la sede a verla?
- **asesor**: Claro que sí, lo esperamos. Estamos de 8 a 6, ¿le separo la moto mientras tanto?
- **cliente**: Hágale pues, ya voy en camino

```
modelo_mencionado      = Honda Navi
forma_pago             = credito
manifesto_cuota_inicial= SI
cuota_inicial_cop      = 2000000
pidio_cita             = SI
pidio_cotizacion       = NO_INFORMA
intencion              = compra_inmediata
objecion               = ninguna
```


## LD-00027 — Meta Ads

*Por qué está aquí: monto en jerga (palos/millonzitos/1200mil)*

- **cliente**: Qsé, quiero información de la Suzuki Best 125
- **asesor**: ¡Qsé! Con mucho gusto le colaboro. La Suzuki Best 125 está en $6.590.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada, tengo 3000mil para la inicial
- **asesor**: Perfecto. ¿Usted tiene cómo demostrar ingresos? Le puedo dejar el estudio de crédito adelantado
- **cliente**: Claro, tengo contrato indefinido
- **cliente**: ¿Puedo pasar mañana a la sede a verla?
- **asesor**: Claro que sí, lo esperamos. Estamos de 8 a 6, ¿le separo la moto mientras tanto?
- **cliente**: Listo, sepáremela

```
modelo_mencionado      = Suzuki Best 125
forma_pago             = credito
manifesto_cuota_inicial= SI
cuota_inicial_cop      = 3000000
pidio_cita             = SI
pidio_cotizacion       = NO_INFORMA
intencion              = compra_inmediata
objecion               = ninguna
```


## LD-00079 — formulario web

*Por qué está aquí: pago de contado con monto*

- **cliente**: Buenos días, estoy averiguando por la Bajaj Dominar 400
- **asesor**: ¡Buenos días! Con mucho gusto le colaboro. La Bajaj Dominar 400 está en $24.900.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: De contado, ya tengo la plata lista, 24,9 millones
- **asesor**: Perfecto. ¿Usted tiene cómo demostrar ingresos? Le puedo dejar el estudio de crédito adelantado
- **cliente**: Sí, soy independiente pero tengo extractos
- **cliente**: ¿A qué hora los puedo visitar hoy?
- **asesor**: Claro que sí, lo esperamos. Estamos de 8 a 6, ¿le separo la moto mientras tanto?
- **cliente**: Sí por favor, voy saliendo

```
modelo_mencionado      = Bajaj Dominar 400
forma_pago             = contado
manifesto_cuota_inicial= NO_INFORMA
cuota_inicial_cop      = null
pidio_cita             = SI
pidio_cotizacion       = NO_INFORMA
intencion              = compra_inmediata
objecion               = ninguna
```


## LD-00058 — Formulario Web

*Por qué está aquí: busca alternativa más barata o usada*

- **cliente**: Qué más pues, quiero información de la Honda XR 150L
- **asesor**: ¡Qué más pues! Con mucho gusto le colaboro. La Honda XR 150L está en $11.490.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: ¿Y no tienen algo más económico? tipo la Honda CB 125F Twister
- **asesor**: Claro. la Honda CB 125F Twister está en $7.990.000 más papeles
- **cliente**: Esa sí me sirve. Tengo como 2 millonzitos de inicial
- **cliente**: ¿Mañana los visito?

```
modelo_mencionado      = Honda CB 125F Twister
forma_pago             = credito
manifesto_cuota_inicial= SI
cuota_inicial_cop      = 2000000
pidio_cita             = SI
pidio_cotizacion       = NO_INFORMA
intencion              = compra_inmediata
objecion               = precio
```


## LD-00025 — Meta Ads

*Por qué está aquí: crédito con intención de visita*

- **cliente**: Qué más pues, quiero información de la Hero Dash 110
- **asesor**: ¡Buenas! Con mucho gusto le colaboro. La Hero Dash 110 está en $6.290.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada, tengo 2,5 millones para la inicial
- **asesor**: Perfecto. ¿Usted tiene cómo demostrar ingresos? Le puedo dejar el estudio de crédito adelantado
- **cliente**: Claro, tengo contrato indefinido
- **cliente**: Voy esta tarde para allá, ¿hasta qué hora abren?
- **asesor**: Claro que sí, lo esperamos. Estamos de 8 a 6, ¿le separo la moto mientras tanto?
- **cliente**: Listo, sepáremela

```
modelo_mencionado      = Hero Dash 110
forma_pago             = credito
manifesto_cuota_inicial= SI
cuota_inicial_cop      = 2500000
pidio_cita             = SI
pidio_cotizacion       = NO_INFORMA
intencion              = compra_inmediata
objecion               = ninguna
```


## LD-00026 — WhatsApp

*Por qué está aquí: conversación larga*

- **cliente**: Buenas, quiero información de la AKT Dynamic R3 125
- **asesor**: ¡Qué más pues! Con mucho gusto le colaboro. La AKT Dynamic R3 125 está en $5.590.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada, tengo 2 millones para la inicial
- **asesor**: Perfecto. ¿Usted tiene cómo demostrar ingresos? Le puedo dejar el estudio de crédito adelantado
- **cliente**: Sí señor, trabajo en empresa con contrato fijo
- **cliente**: Voy esta tarde para allá, ¿hasta qué hora abren?
- **asesor**: Claro que sí, lo esperamos. Estamos de 8 a 6, ¿le separo la moto mientras tanto?
- **cliente**: Hágale pues, ya voy en camino

```
modelo_mencionado      = AKT Dynamic R3 125
forma_pago             = credito
manifesto_cuota_inicial= SI
cuota_inicial_cop      = 2000000
pidio_cita             = SI
pidio_cotizacion       = NO_INFORMA
intencion              = compra_inmediata
objecion               = ninguna
```


## LD-00013 — Meta Ads

*Por qué está aquí: canal Meta Ads con señal completa*

- **cliente**: Qué más pues, quiero información de la Honda CB 190R
- **asesor**: ¡Buenas! Con mucho gusto le colaboro. La Honda CB 190R está en $13.990.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: A crédito, ¿cómo es el proceso?
- **asesor**: Con esa inicial la cuota le queda alrededor de $320.000 a 48 meses.
- **cliente**: Es que la necesito esta semana
- **asesor**: Le entiendo. ¿Le mando la cotización formal al WhatsApp para que la revise con calma?
- **cliente**: Sí porfa, mándemela

```
modelo_mencionado      = Honda CB 190R
forma_pago             = credito
manifesto_cuota_inicial= NO_INFORMA
cuota_inicial_cop      = null
pidio_cita             = NO
pidio_cotizacion       = SI
intencion              = compra_inmediata
objecion               = otra / Dudé en elegir
```


## LD-00032 — whatsapp

*Por qué está aquí: caso normal de control*

- **cliente**: Buenos días, quiero información de la Bajaj Dominar 400
- **asesor**: ¡Buenas! Con mucho gusto le colaboro. La Bajaj Dominar 400 está en $24.900.000 más matrícula y SOAT. ¿La está buscando de contado o financiada?
- **cliente**: Financiada, pero primero quiero saber cuánto queda la cuota
- **asesor**: Con esa inicial la cuota le queda alrededor de $320.000 a 48 meses.
- **cliente**: Estoy mirando también otra marca
- **asesor**: Le entiendo. ¿Le mando la cotización formal al WhatsApp para que la revise con calma?
- **cliente**: Bueno, mándela y yo le digo

```
modelo_mencionado      = Bajaj Dominar 400
forma_pago             = credito
manifesto_cuota_inicial= NO_INFORMA
cuota_inicial_cop      = null
pidio_cita             = NO_INFORMA
pidio_cotizacion       = SI
intencion              = explorando
objecion               = cuota
```

