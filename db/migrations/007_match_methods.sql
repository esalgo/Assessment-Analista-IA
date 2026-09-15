-- Métodos de resolución de modelo_interes_texto, en el orden en que se prueban:
--   exacto         marca + línea completas, tras normalizar el texto
--   exacto_linea   solo la línea, sin marca (las 24 líneas son únicas entre marcas)
--   solo_marca     solo la marca, o marca + línea incompleta que calza con varias líneas
--   linea_parcial  marca + palabras que son el inicio de exactamente una línea de esa marca
--   fuzzy          fuzz.ratio >= 85 contra marca + línea (errores de tipeo: Hnda, Bajai)
--   sin_match      nada de lo anterior
--
-- match_confidence: 100 en las reglas deterministas; en fuzzy, el score del ganador.
-- match_score_segundo: solo en fuzzy, el score del segundo mejor candidato. La
-- distancia entre ambos dice cuán segura fue la elección.
ALTER TABLE leads DROP CONSTRAINT leads_match_method_check;
ALTER TABLE leads ADD CONSTRAINT leads_match_method_check
    CHECK (match_method IN ('exacto', 'exacto_linea', 'solo_marca', 'linea_parcial', 'fuzzy', 'sin_match'));

ALTER TABLE leads ADD COLUMN match_score_segundo numeric(5, 2);
