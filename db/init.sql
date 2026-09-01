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

-- Individual polygons (e.g. plantation plots) belonging to an AOI.
CREATE TABLE IF NOT EXISTS plot (
    id           SERIAL PRIMARY KEY,
    aoi_id       INTEGER REFERENCES aoi(id) ON DELETE CASCADE,
    plot_name    TEXT NOT NULL,                       -- e.g. "Whykong Range 1"
    geom         GEOMETRY(MultiPolygon, 4326) NOT NULL,
    area_ha      DOUBLE PRECISION,
    plant_year   TEXT,
    plant_type   TEXT,
    ecozone      TEXT,
    division     TEXT,
    range_name   TEXT,
    beat_name    TEXT,
    village      TEXT,
    union_name   TEXT,
    patches      TEXT,
    journal_id   TEXT,
    remarks      TEXT
);

-- ndvi_series can belong to a whole AOI (plot_id NULL) or a single plot.
ALTER TABLE ndvi_series ADD COLUMN IF NOT EXISTS plot_id INTEGER
    REFERENCES plot(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_aoi_geom ON aoi USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_plot_geom ON plot USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_series_plot ON ndvi_series (plot_id);
