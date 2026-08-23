CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS aoi (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    geom         GEOMETRY(MultiPolygon, 4326) NOT NULL,
    uploaded_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ndvi_series (
    id           SERIAL PRIMARY KEY,
    aoi_id       INTEGER REFERENCES aoi(id) ON DELETE CASCADE,
    image_date   DATE NOT NULL,          -- first of the month for monthly series
    median_ndvi  DOUBLE PRECISION,       -- monthly median NDVI over the AOI
    evi          DOUBLE PRECISION,       -- Enhanced Vegetation Index
    savi         DOUBLE PRECISION,       -- Soil Adjusted Vegetation Index
    ndre         DOUBLE PRECISION,       -- Normalized Difference Red Edge
    gndvi        DOUBLE PRECISION,       -- Green NDVI
    n_images     INTEGER,                -- how many scenes fed the month
    source       TEXT,
    computed_at  TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_aoi_geom ON aoi USING GIST (geom);
