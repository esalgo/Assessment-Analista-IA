-- Semilla de ciudades canónicas. No salen de ningún archivo: se construyen
-- a partir de las 37 variantes de leads.csv. El mapeo variante -> nombre
-- vive en backend/catalogos.py; la llave foránea leads.ciudad garantiza
-- que ese mapeo solo apunte a nombres de esta lista.
INSERT INTO ciudades (nombre) VALUES
    ('Barranquilla'),
    ('Bello'),
    ('Bogotá'),
    ('Cartagena'),
    ('Itagüí'),
    ('Medellín'),
    ('Montería'),
    ('Rionegro'),
    ('Santa Marta'),
    ('Soacha'),
    ('Soledad')
ON CONFLICT DO NOTHING;
