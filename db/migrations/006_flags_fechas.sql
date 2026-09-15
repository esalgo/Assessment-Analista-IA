-- Trazabilidad de cómo normalize resolvió cada fecha.
--
-- *_metodo:
--   formato_inequivoco  el texto solo admite una lectura
--   ventana             xx/xx/yyyy ambigua; solo una lectura cae en la ventana
--   coherencia          registro: solo una lectura deja el contacto inequívoco en
--                       o después del registro (un lead no se contacta antes de existir).
--                       contacto: de las lecturas en ventana, solo una es >= registro
--   mas_cercana         (contacto) dos lecturas coherentes; gana la más cercana al registro
--   irresoluble_ddmm    ninguna regla decide; se toma dd/mm, el formato mayoritario
--                       entre las fechas inequívocas con barra del archivo
--
-- fecha_*_ambigua = true cuando el método es mas_cercana o irresoluble_ddmm:
-- la fecha guardada es una elección, no un dato.
-- fecha_contacto_sin_hora: el contacto venía como dd-mm-yyyy; la hora 00:00
-- guardada no es un dato observado y no debe usarse para calcular horas.
-- contacto_antes_registro: inconsistencia del dato. Se marca, no se corrige.
-- Si el contacto no tiene hora, se compara por día de calendario.
ALTER TABLE leads
    ADD COLUMN fecha_registro_metodo   text    NOT NULL DEFAULT 'formato_inequivoco'
        CHECK (fecha_registro_metodo IN ('formato_inequivoco', 'ventana', 'coherencia',
                                         'irresoluble_ddmm')),
    ADD COLUMN fecha_registro_ambigua  boolean NOT NULL DEFAULT false,
    ADD COLUMN fecha_contacto_metodo   text
        CHECK (fecha_contacto_metodo IN ('formato_inequivoco', 'ventana', 'coherencia',
                                         'mas_cercana', 'irresoluble_ddmm')),
    ADD COLUMN fecha_contacto_sin_hora boolean NOT NULL DEFAULT false,
    ADD COLUMN contacto_antes_registro boolean NOT NULL DEFAULT false;
