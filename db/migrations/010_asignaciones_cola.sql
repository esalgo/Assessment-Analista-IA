-- La asignación del día guarda de qué cola sale cada lead. `orden` es la
-- posición del lead en la lista de ese asesor dentro de esa cola.
ALTER TABLE asignaciones ADD COLUMN cola text NOT NULL
    CHECK (cola IN ('primer_contacto', 'seguimiento'));
