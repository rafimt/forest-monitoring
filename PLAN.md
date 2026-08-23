# NDVI Time-Series Analysis — Project Plan

A Streamlit web app to compute and visualize NDVI (vegetation greenness) for a user-supplied
area over a chosen date range, with an interactive map and a time-series line chart.

---

## Project Name: NDVI Explorer

**Goal:** Let a user upload a shapefile (their area of interest), pick a start and end month,
and get:
1. NDVI computed for that area over the period
2. An NDVI map (colored raster / choropleth) shown on an interactive map
3. An NDVI **change** time-series as a line chart (median NDVI per month)

**Context:** Vegetation/crop/forest monitoring — the kind of analysis agriculture agencies,
NGOs, and environmental consultants pay for.

---

## The Core Question: Where Does NDVI Come From?

NDVI = (NIR − Red) / (NIR + Red), computed from satellite bands. We need an imagery source.

**Chosen approach: Google Earth Engine (GEE).**
GEE hosts the full Sentinel-2 and Landsat archive and computes NDVI *cloud-side* — we send it
an area and a date range, it returns NDVI values. No downloading gigabytes of imagery.

| Alternative | Why not (for now) |
|-------------|-------------------|
| Download Sentinel-2 tiles + rasterio | Huge downloads, slow, storage-heavy |
| Sentinel Hub API | Good, but paid beyond a small free tier |
| Microsoft Planetary Computer | Viable free alternative; more setup than GEE |

> Requires a free Google Earth Engine account (sign up at https://earthengine.google.com).
> First-time auth is a one-time browser login.

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| UI / frontend | **Streamlit** | Pure Python, fast to build, no JS needed |
| Map in UI | **geemap** / **folium** | Leaflet-based maps that embed in Streamlit |
| NDVI compute | **Google Earth Engine** (`earthengine-api`) | Cloud imagery + band math over date ranges |
| Charts | **Plotly** / Streamlit native | Interactive NDVI time-series line chart |
| Database | **PostgreSQL + PostGIS** | Store uploaded AOIs + cache NDVI results |
| Shapefile handling | **geopandas** | Read uploaded shapefile → geometry |
| Container | **Docker + Docker Compose** | Reproducible PostGIS + app |

---

## What PostGIS Is For (important)

PostGIS does **not** compute NDVI. Its jobs here:
1. **Store uploaded AOIs** — save each shapefile's geometry + a name, so users can reuse them.
2. **Cache NDVI time series** — once computed for (AOI, date range), store the results so
   re-opening is instant and we don't hit GEE again.
3. **History** — keep a record of past analyses.

Schema sketch:

```
aoi
  id            serial PK
  name          text
  geom          geometry(MultiPolygon, 4326)
  uploaded_at   timestamp

ndvi_series
  id            serial PK
  aoi_id        int FK -> aoi.id
  image_date    date
  median_ndvi   double precision
  n_images      int
  source        text        -- e.g. 'COPERNICUS/S2_SR_HARMONIZED'
  computed_at   timestamp
```

---

## Application Features

### Core (Phase 1)
- [ ] Upload a shapefile (zipped `.shp/.shx/.dbf/.prj`) as the area of interest
- [ ] Pick **from-month** and **to-month** (date range selectors)
- [ ] Compute NDVI over the AOI for that range via GEE
- [ ] Show the NDVI map (mean composite) on an interactive map
- [ ] Show NDVI time series (median NDVI per month) as a line chart

### Analytical (Phase 2)
- [ ] Cloud filtering (mask clouds before NDVI)
- [ ] Choose satellite (Sentinel-2 10m vs Landsat 30m)
- [ ] NDVI change map: (end period NDVI − start period NDVI)
- [ ] Download results (CSV of the time series, GeoTIFF of the NDVI map)
- [ ] Cache to PostGIS so repeated runs are instant

### Nice-to-have (Phase 3)
- [ ] Save named AOIs and reload them from PostGIS
- [ ] Compare multiple AOIs on one chart
- [ ] Draw AOI on the map instead of uploading
- [ ] Anomaly detection (NDVI vs historical average)

---

## Project Structure

```
ndvi-analysis/
├── PLAN.md                  ← this file
├── docker-compose.yml       ← PostGIS (+ optional app container)
├── .env.example
├── requirements.txt
│
├── app/
│   ├── main.py              ← Streamlit entry point (UI layout)
│   ├── gee.py              ← Earth Engine: auth, NDVI compute, time series
│   ├── shapefile_io.py     ← read uploaded shapefile -> geometry (geopandas)
│   ├── mapping.py          ← build the geemap/folium map
│   ├── charts.py           ← NDVI time-series line chart (Plotly)
│   ├── db.py               ← PostGIS connection + save/load AOIs & results
│   └── config.py           ← settings from .env
│
├── db/
│   └── init.sql            ← PostGIS extension + schema
│
└── data/
    └── sample_aoi/         ← a sample shapefile for testing
```

---

## Streamlit UI Layout (sketch)

```
┌───────────────────────────────────────────────────────────┐
│  NDVI Explorer                                             │
├────────────────┬──────────────────────────────────────────┤
│  SIDEBAR        │   MAIN AREA                              │
│                 │                                          │
│  Upload shapefile   ┌──────────────────────────────┐      │
│  [Browse .zip]      │                              │      │
│                 │   │      NDVI MAP (geemap)       │      │
│  From: [2023-01]│   │                              │      │
│  To:   [2023-12]│   └──────────────────────────────┘      │
│                 │                                          │
│  Satellite:     │   ┌──────────────────────────────┐      │
│  [Sentinel-2 ▾] │   │   NDVI TIME SERIES (line)    │      │
│                 │   │      /\      /\               │      │
│  [Run Analysis] │   │  ___/  \__/     \___         │      │
│                 │   └──────────────────────────────┘      │
└────────────────┴──────────────────────────────────────────┘
```

Streamlit widgets map directly to your requirements:
- **Upload shapefile** → `st.file_uploader`
- **From/To month** → `st.date_input` or `st.select_slider`
- **Run** → `st.button`
- **Map** → `geemap`/`folium` embedded via `st_folium`
- **Line chart** → `st.plotly_chart`

---

## The NDVI Compute Flow (how it works)

```
1. User uploads shapefile
      → geopandas reads it → geometry → ee.Geometry (GEE format)

2. User picks from-month .. to-month
      → date range

3. gee.py:
      a. Load image collection (Sentinel-2) filtered by AOI + date range
      b. Mask clouds
      c. Compute NDVI band: (B8 - B4) / (B8 + B4)
      d. For the MAP: make a median composite -> NDVI image
      e. For the CHART: group images by month, median-composite each month,
                        then median over the AOI
                        -> list of {date (YYYY-MM), median_ndvi, n_images}

4. mapping.py    → show NDVI composite on the map (green ramp)
   charts.py     → plot {date, median_ndvi} as a line chart

5. db.py (optional) → cache the {date, median_ndvi} series in PostGIS
```

### Key GEE concepts
- **ImageCollection** — a stack of satellite scenes; filter by date + area.
- **NDVI band** — Sentinel-2: `(B8 − B4) / (B8 + B4)` (`normalizedDifference(['B8','B4'])`).
- **Cloud mask** — use the `SCL` / QA band to drop cloudy pixels.
- **Reducer** — `reduceRegion(ee.Reducer.mean())` collapses an image to one number over the AOI
  (this is what builds each time-series point).

---

## Learning Milestones

| Step | What you build | What you learn |
|------|----------------|----------------|
| 1 | Streamlit "hello world" + PostGIS in Docker | Streamlit basics, Docker |
| 2 | GEE auth working in Python | Earth Engine setup, one-time auth |
| 3 | Upload shapefile → show its outline on a map | geopandas, file upload, geemap |
| 4 | Compute NDVI composite for AOI + date range | GEE ImageCollection, NDVI, cloud mask |
| 5 | Show NDVI map with a legend | geemap visualization, color ramps |
| 6 | Build the mean-NDVI time series | reduceRegion, mapping over a collection |
| 7 | Plot the time series as a line chart | Plotly in Streamlit |
| 8 | Cache AOIs + series in PostGIS | geoalchemy2, save/load geometry |
| 9 | Add cloud filtering + satellite choice | QA bands, robustness |
| 10 | Polish, Dockerize, README, deploy | Streamlit deploy, portfolio |

---

## Development Phases

### Phase 0 — Setup
- Docker Compose with PostGIS
- Streamlit app runs, shows a title
- GEE account created, `earthengine authenticate` works

### Phase 1 — Shapefile → Map
- `st.file_uploader` accepts a zipped shapefile
- geopandas reads it, reprojects to EPSG:4326
- The AOI outline shows on a geemap map

### Phase 2 — NDVI Compute
- From/To month selectors
- GEE computes NDVI composite over AOI + range
- NDVI map rendered with a green color ramp + legend

### Phase 3 — Time Series
- Median NDVI per month over the AOI
- Plotly line chart of NDVI over time
- CSV download of the series

### Phase 4 — PostGIS Cache + Polish
- Save AOIs and NDVI series to PostGIS
- Reload named AOIs
- README, screenshots, deploy

---

## Requirements (initial)

```
streamlit
earthengine-api
geemap
geopandas
folium
streamlit-folium
plotly
pandas
sqlalchemy
geoalchemy2
psycopg2-binary
python-dotenv
```

---

## Freelancing Context

NDVI/vegetation monitoring is one of the most in-demand geospatial freelance niches:
- **Agriculture** — crop health, yield estimation, irrigation planning
- **Forestry / environment** — deforestation, restoration monitoring
- **Insurance / finance** — drought and crop-loss assessment
- **NGOs / development** — land degradation, food security

Typical requests this app matches:
- "Show NDVI change for my farm/region over the season"
- "Build a dashboard to monitor vegetation from satellite"
- "Compute a vegetation index time series for these polygons"

---

## Inspecting the Database (pgAdmin web)

If a pgAdmin container is running (e.g. on http://localhost:8081), register the NDVI DB:

**Connection tab:**

| Field | Value |
|-------|-------|
| Host name/address | `host.docker.internal` |
| Port | `5435` |
| Maintenance database | `ndvi` |
| Username | `ndvi_user` |
| Password | `ndvi_pass` |

> `host.docker.internal` because pgAdmin runs in a container — its own `localhost` isn't the
> host. Port `5435` is where this project's PostGIS is published (5432/5433/5434 were taken by
> other local Postgres instances).

Browse: **Servers → ndvi → Databases → ndvi → Schemas → public → Tables → `aoi` / `ndvi_series`**.

Quick check query:

```sql
SELECT a.name, s.image_date, ROUND(s.median_ndvi::numeric, 3) AS ndvi, s.n_images
FROM aoi a JOIN ndvi_series s ON s.aoi_id = a.id
ORDER BY s.image_date;
```

Or via psql (use a real id, not the SQLAlchemy `:id` placeholder):

```sql
SELECT ST_AsGeoJSON(geom) FROM aoi WHERE id = 3;
```

---

## Viewing Data in QGIS

QGIS runs on your machine (not a container), so connect directly to `localhost`.

### 1. Create the PostGIS connection

**Browser panel → right-click PostGIS → New Connection:**

| Field | Value |
|-------|-------|
| Name | `ndvi` |
| Host | `127.0.0.1` |
| Port | `5435` |
| Database | `ndvi` |
| SSL mode | `disable` |

**Authentication → Basic tab** (not "No Authentication"):
- User name: `ndvi_user` → tick **Store**
- Password: `ndvi_pass` → tick **Store**

Tick **Also list tables with no geometry** so `ndvi_series` is visible too. Then
**Test Connection → OK**.

> Common mistakes: leaving the port at the default `5432` (must be `5435`), and leaving
> Authentication on "No Authentication" instead of the **Basic** tab.

### 2. The two tables

- **`aoi`** — has geometry; drag it onto the canvas to see the AOI polygon.
- **`ndvi_series`** — attribute only (the monthly NDVI values); no geometry, so it can't be
  drawn directly. To visualize NDVI, **join it to `aoi.geom`**.

### 3. Show one date's NDVI on the map

Open **Database → DB Manager → (ndvi connection) → SQL Window** and run:

```sql
SELECT s.id, a.name, s.image_date, s.median_ndvi, a.geom
FROM aoi a
JOIN ndvi_series s ON s.aoi_id = a.id
WHERE s.image_date = '2023-09-01';
```

At the bottom of the SQL Window:
- Tick **Load as new layer**
- **Geometry column:** `geom`
- **Column with unique values:** `id`
- Click **Load**

The AOI polygon loads carrying that month's `median_ndvi`. Style it via
**Layer Properties → Symbology → Graduated → Value: `median_ndvi`** with a green ramp.

> Dates are stored as the **first of the month** (`2023-09-01`). List all available dates with:
> `SELECT DISTINCT image_date FROM ndvi_series ORDER BY image_date;`

---

## Deployment Options

| Option | Notes |
|--------|-------|
| **Streamlit Community Cloud** | Free; easiest for Streamlit; store GEE service-account key as a secret |
| **Hugging Face Spaces** | Free Streamlit hosting |
| **VPS + Docker** | Full control; run `docker compose up` |

> For deployment, use a **GEE service account** (not interactive auth) so the app authenticates
> without a browser.

---

## Next Steps

1. Phase 0 — set up Docker + PostGIS + a bare Streamlit app
2. Create a free Google Earth Engine account and get auth working
3. Then build up one milestone at a time (like the WebGIS project's doc/ steps)

Once approved, we'll create the `doc/` folder and write step-by-step guides (`01-...`, `02-...`)
exactly like the bangladesh-webgis project.
