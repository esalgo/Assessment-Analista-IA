-- historico_cierres.pidio_cita pasa de boolean a los valores del archivo (SI / NO).
--
-- Con boolean, el código que cruza el histórico con la extracción del LLM
-- tenía que traducir true/false a SI/NO al leer: una traducción silenciosa.
-- La extracción usa SI / NO / NO_INFORMA; el histórico solo trae SI y NO
-- porque ahí el dato ya está registrado. El CHECK no admite NO_INFORMA a
-- propósito: si apareciera en el histórico, sería un dato nuevo que revisar.
ALTER TABLE historico_cierres
    ALTER COLUMN pidio_cita TYPE text
    USING CASE WHEN pidio_cita THEN 'SI' ELSE 'NO' END;

ALTER TABLE historico_cierres
    ADD CONSTRAINT historico_cierres_pidio_cita_check CHECK (pidio_cita IN ('SI', 'NO'));
