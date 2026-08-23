# Step 1: Setup — Streamlit + PostGIS + Google Earth Engine

## Goal

Get the three foundations running before any NDVI logic:
1. A **PostGIS** database in Docker
2. A bare **Streamlit** app that opens in the browser
3. **Google Earth Engine** authenticated in Python

After this step you have an empty-but-working app and a verified connection to both the
database and the imagery engine.

---

## Prerequisites

- Docker Desktop installed and running
- Python 3.10+ installed
- A free **Google Earth Engine** account — sign up at https://earthengine.google.com
  (approval is usually instant to a few hours)

---

## Part A — Project Skeleton + Virtual Environment

### 1. Create the folders

```
ndvi-analysis/
├── app/
│   ├── __init__.py
│   ├── main.py
│   └── config.py
├── db/
│   └── init.sql
├── docker-compose.yml
├── requirements.txt
├── .env
└── .env.example
```

### 2. Create the venv

From the project root:

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install the geospatial stack FIRST (Windows: order matters)

**Do not** just `pip install geopandas rasterio fiona`. On Windows these bind to **GDAL's
compiled C libraries**, and pip's default source builds usually fail (missing GDAL headers).
The fix is to install **binary wheels in dependency order**: GDAL → fiona → rasterio →
pyproj/shapely → geopandas.

There are two reliable ways. Pick one.

#### Option A — conda / mamba (recommended, least pain)

conda-forge ships GDAL and all bindings as prebuilt binaries that are guaranteed compatible.
This avoids the whole wheel-matching problem.

```bash
conda create -n ndvi python=3.11
conda activate ndvi
conda install -c conda-forge gdal fiona rasterio pyproj shapely geopandas
```

Then install the pure-Python packages (next section) with pip into the same env.

#### Option B — venv + pip wheels, in this exact order (verified on Python 3.11)

This is the path this project uses. On **Windows + Python 3.11**, modern pip (23+) installs all
of these as prebuilt `cp311-win_amd64` **wheels** — no compiling. Install them in dependency
order:

```bash
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip

# 1. geometry + projections (bundle GEOS / PROJ inside the wheel)
pip install shapely==2.0.6 pyproj==3.6.1

# 2. vector + raster I/O — these wheels BUNDLE GDAL (~23-25 MB each)
pip install fiona==1.9.6 rasterio==1.3.11

# 3. geopandas LAST — sits on top of fiona + pyproj + shapely
pip install geopandas==0.14.4
```

> **You do NOT need a separate `GDAL` package.** On Python 3.11 the `fiona` and `rasterio`
> wheels each bundle their own GDAL (that's why they're ~23–25 MB). Installing a standalone
> `GDAL` pip package on top can cause a version clash — skip it. GDAL 3.9.1 ships inside these
> wheels; verify with `python -c "import rasterio; print(rasterio.__gdal_version__)"`.
>
> **If you were on an older Python or a build did fail**, that's when you'd fetch a prebuilt
> `GDAL‑…‑cp311‑…‑win_amd64.whl` and `pip install` it *before* fiona/rasterio. On 3.11 with
> current pip this isn't necessary.

> **Why the order:** fiona and rasterio are Python bindings over GDAL's C library, so GDAL must
> resolve first (here, bundled in their own wheels). geopandas imports fiona, pyproj, and
> shapely at runtime, so it must come after all three.

### 4. Then install the pure-Python packages

Put these in `requirements.txt` (the geo libs above are installed separately, per Option A/B):

```
streamlit==1.62.0
earthengine-api==1.7.40
geemap==0.37.2
folium==0.20.0
streamlit-folium==0.27.4
plotly==6.9.0
sqlalchemy==2.0.52
geoalchemy2==0.20.0
psycopg2-binary==2.9.12
python-dotenv==1.2.3
pydantic-settings==2.15.0
```

(These are the versions verified working together on Python 3.11. `pandas` and `numpy` come in
automatically as dependencies of geopandas/streamlit — no need to pin them.)

```bash
pip install -r requirements.txt
```

> `geemap` pulls in some geo deps too, but with GDAL/fiona/rasterio/geopandas already installed
> correctly, it resolves cleanly. Keeping the compiled libs out of `requirements.txt` avoids pip
> trying to rebuild them.

### 5. Verify the geo stack imports

```bash
python -c "import geopandas, fiona, rasterio, pyproj, shapely; print('geo stack OK')"
```

If that prints `geo stack OK`, the hard part is done.

---

## Part B — PostGIS in Docker

### 6. `docker-compose.yml`

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    container_name: ndvi_db
    restart: unless-stopped
    environment:
      POSTGRES_DB: ndvi
      POSTGRES_USER: ndvi_user
      POSTGRES_PASSWORD: ndvi_pass
    ports:
      - "5434:5432"      # host 5434 -> container 5432 (avoids clashes with other PG)
    volumes:
      - ndvi_pgdata:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql

volumes:
  ndvi_pgdata:
```

> **Port note:** we map to host **5434** on purpose. If you have a native PostgreSQL (5432) or
> the bangladesh-webgis DB (5433) running, 5434 keeps this project's DB separate. Adjust if
> 5434 is also taken.

### 7. `db/init.sql`

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

-- Area-of-interest polygons uploaded by the user
CREATE TABLE IF NOT EXISTS aoi (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    geom         GEOMETRY(MultiPolygon, 4326) NOT NULL,
    uploaded_at  TIMESTAMP DEFAULT now()
);

-- Cached NDVI time series (one row per image date per AOI)
CREATE TABLE IF NOT EXISTS ndvi_series (
    id           SERIAL PRIMARY KEY,
    aoi_id       INTEGER REFERENCES aoi(id) ON DELETE CASCADE,
    image_date   DATE NOT NULL,          -- first of the month for monthly series
    median_ndvi  DOUBLE PRECISION,       -- monthly median NDVI over the AOI
    n_images     INTEGER,                -- how many scenes fed the month
    source       TEXT,
    computed_at  TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_aoi_geom ON aoi USING GIST (geom);
```

### 8. Start it

```bash
docker compose up -d
docker compose ps          # ndvi_db should be "Up"
```

Verify PostGIS:

```bash
docker exec -it ndvi_db psql -U ndvi_user -d ndvi -c "SELECT PostGIS_Version();"
```

---

## Part C — Environment Config

### 9. `.env`

```
DATABASE_URL=postgresql://ndvi_user:ndvi_pass@127.0.0.1:5434/ndvi
GEE_PROJECT=rmtumon
```

Use `127.0.0.1` (not `localhost`) to force IPv4 and avoid hitting a different Postgres on
IPv6 — the same lesson from the WebGIS project.

### 10. `.env.example` (safe to commit)

```
DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5434/ndvi
```

### 11. `.gitignore`

```
.env
venv/
__pycache__/
*.pyc
.streamlit/secrets.toml
```

### 12. `app/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    gee_project: str
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
```

> If you didn't install `pydantic-settings`, either add it to requirements or read the env var
> with `os.getenv("DATABASE_URL")` and `python-dotenv` instead.

---

## Part D — Bare Streamlit App

### 13. `app/main.py`

```python
import streamlit as st

st.set_page_config(page_title="NDVI Explorer", layout="wide")

st.title("🌱 NDVI Explorer")
st.write("Upload an area, pick a date range, and analyze vegetation over time.")

# Sidebar placeholders (we'll fill these in later steps)
with st.sidebar:
    st.header("Controls")
    st.file_uploader("Upload shapefile (.zip)", type=["zip"])
    st.date_input("From")
    st.date_input("To")
    st.button("Run Analysis")

st.info("Setup complete. NDVI logic comes in the next steps.")
```

### 14. Run it

```bash
streamlit run app/main.py
```

Streamlit opens http://localhost:8501 automatically. You should see the title, sidebar
controls, and the info box.

---

## Part E — Google Earth Engine Authentication

GEE needs a one-time authentication so Python can talk to it.

### 15. Authenticate (one-time)

With the venv active:

```bash
earthengine authenticate
```

This opens a browser, you log in with your Google account (the one approved for Earth Engine),
and it saves a credential token locally. You only do this once per machine.

### 16. Test GEE in Python

Create `app/gee_test.py`:

```python
import ee

# initialize() connects to Earth Engine using the saved credentials.
# The project= argument is your Google Cloud project id linked to Earth Engine.
ee.Initialize(project="rmtumon")

# A trivial computation to prove it works: a number, computed server-side.
print("EE says:", ee.Number(21).multiply(2).getInfo())
```

Run:

```bash
python app/gee_test.py
```

Expected: `EE says: 42`

> **`project=` id:** newer Earth Engine requires a Google Cloud project. This project uses
> **`rmtumon`**. Find or change it at https://console.cloud.google.com. We'll store this in
> `.env` (next step) so it isn't hard-coded everywhere.

---

## What Success Looks Like

- `docker compose ps` → `ndvi_db` is Up; `PostGIS_Version()` returns a version
- `streamlit run app/main.py` → the app opens with title + sidebar
- `python app/gee_test.py` → prints `EE says: 42`

All three foundations verified. Next: **Step 2 — Upload a shapefile and show it on the map.**

---

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `earthengine: command not found` | venv not active / not installed | Activate venv; `pip install earthengine-api` |
| GEE `not signed up` / permission error | Account not approved or wrong project | Check approval; pass the correct `project=` id |
| `ee.Initialize()` asks to authenticate | No saved token | Run `earthengine authenticate` first |
| Port 5434 in use | Another Postgres/container | Change host port in docker-compose |
| geopandas/GDAL install fails on Windows | Compiling GDAL bindings from source | Install in order GDAL → fiona → rasterio → geopandas (Option B), or use conda-forge (Option A) |
| `fiona`/`rasterio` import error after install | GDAL missing or version mismatch | Reinstall with GDAL first; keep all four from the same source (all pip wheels, or all conda) |
| Mixed conda + pip geo libs | ABI mismatch between GDAL builds | Don't mix: install GDAL/fiona/rasterio/geopandas all via conda **or** all via pip wheels |
| Streamlit doesn't open | Port 8501 busy | `streamlit run app/main.py --server.port 8502` |
