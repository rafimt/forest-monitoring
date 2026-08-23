# Forest / Vegetation Monitoring

A Streamlit app to compute and visualize **vegetation indices** (NDVI, EVI, SAVI, NDRE, GNDVI)
for user-defined areas over time, using **Google Earth Engine** (Sentinel-2) and **PostGIS**.

## Features
- Upload an AOI (shapefile / GeoPackage / GeoJSON); points are auto-buffered to areas
- Monthly **median** index values over a date range (2017–present)
- Interactive map (multiple basemaps) + time-series chart with rolling trend
- 5 switchable indices, KPI cards, CSV-friendly data table
- Results cached in PostGIS (compute once, view instantly)

## Stack
Streamlit · Google Earth Engine · PostgreSQL/PostGIS · GeoPandas · Plotly · Docker

## Quick start
```bash
python -m venv venv && venv\Scripts\activate
# install geo stack first (see doc/01), then:
pip install -r requirements.txt

docker compose up -d                 # PostGIS on host port 5435
earthengine authenticate             # one-time GEE login

python -m app.ingest_ndvi            # compute + store indices for AOIs in data/input/
streamlit run app/view.py            # http://localhost:8501
```

## Structure
- `app/` — Streamlit app, GEE compute, DB access, ingest script
- `db/init.sql` — PostGIS schema (`aoi`, `ndvi_series`)
- `doc/` — step-by-step build guide
- `data/input/` — AOI files

See `PLAN.md` for the full plan and `doc/` for detailed steps.
