# Step 2: Upload a Shapefile and Show It on the Map

## Goal

Let the user upload a zipped shapefile, read it into a geometry, and display its outline on an
interactive map inside Streamlit. No NDVI yet — just: **file in → shape on map**.

---

## Prerequisites

- Step 1 done: Streamlit runs, PostGIS up, GEE prints `42`

---

## Why a Zipped Shapefile?

A shapefile is not one file — it's a set (`.shp`, `.shx`, `.dbf`, `.prj`, ...). A browser upload
handles a single file, so the user zips the set into one `.zip`. We unzip it server-side and
let geopandas read the `.shp`.

---

## 1. Read the Shapefile — `app/shapefile_io.py`

```python
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd


def read_uploaded_shapefile(uploaded_file) -> gpd.GeoDataFrame:
    """Take a Streamlit UploadedFile (a .zip), extract it, read the .shp,
    and return a GeoDataFrame in EPSG:4326 (lat/lon)."""

    # Work in a temp folder so nothing is left on disk.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Save the uploaded zip to disk
        zip_path = tmp / "upload.zip"
        zip_path.write_bytes(uploaded_file.getbuffer())

        # Extract it
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)

        # Find the .shp file (it may be in a subfolder)
        shp_files = list(tmp.rglob("*.shp"))
        if not shp_files:
            raise ValueError("No .shp file found in the zip.")

        gdf = gpd.read_file(shp_files[0])

    # Reproject to WGS84 (lat/lon) — the standard for web maps and GEE.
    if gdf.crs is None:
        raise ValueError("Shapefile has no CRS (.prj missing).")
    gdf = gdf.to_crs(epsg=4326)

    return gdf
```

**Key points:**
- `tempfile.TemporaryDirectory()` auto-cleans when the block ends — no leftover files.
- `rglob("*.shp")` searches recursively (zips sometimes contain a subfolder).
- **`.to_crs(epsg=4326)`** is essential: shapefiles are often in a projected CRS (UTM, etc.),
  but maps and Earth Engine expect lat/lon degrees (EPSG:4326).

---

## 2. Build the Map — `app/mapping.py`

We'll use `geemap.foliumap` — a Folium-based map that embeds cleanly in Streamlit and later
shows Earth Engine layers too.

```python
import geemap.foliumap as geemap


def make_map(center=(23.7, 90.4), zoom=6):
    """Create a base map centered on Bangladesh by default."""
    m = geemap.Map(center=center, zoom=zoom)
    m.add_basemap("OpenStreetMap")
    return m


def add_aoi(m, gdf):
    """Add the uploaded AOI outline to the map and zoom to it."""
    # Convert the GeoDataFrame to GeoJSON and add as a styled layer.
    m.add_gdf(
        gdf,
        layer_name="AOI",
        style={"color": "#c1272d", "weight": 2, "fillOpacity": 0.1},
    )
    # Zoom the map to the AOI's bounds.
    bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
    m.zoom_to_bounds([bounds[0], bounds[1], bounds[2], bounds[3]])
    return m
```

---

## 3. Wire It Into Streamlit — update `app/main.py`

```python
import streamlit as st
from streamlit_folium import st_folium

from app.shapefile_io import read_uploaded_shapefile
from app.mapping import make_map, add_aoi

st.set_page_config(page_title="NDVI Explorer", layout="wide")
st.title("🌱 NDVI Explorer")

# --- Sidebar: upload ---
with st.sidebar:
    st.header("Controls")
    uploaded = st.file_uploader("Upload shapefile (.zip)", type=["zip"])

# --- Main: read + show the AOI ---
gdf = None
if uploaded is not None:
    try:
        gdf = read_uploaded_shapefile(uploaded)
        st.success(f"Loaded {len(gdf)} feature(s).")
    except Exception as e:
        st.error(f"Could not read shapefile: {e}")

# Build the map (with the AOI if we have one)
m = make_map()
if gdf is not None:
    m = add_aoi(m, gdf)

# Render the map in Streamlit
st_folium(m, width=900, height=550)

# Show the attribute table for reference
if gdf is not None:
    st.subheader("Attributes")
    st.dataframe(gdf.drop(columns="geometry"))
```

---

## 4. How Streamlit Reruns (important mental model)

Streamlit **re-runs the whole script top to bottom on every interaction** (upload, button
click, widget change). There's no event loop like in JavaScript.

- When you upload a file, the script runs again; `uploaded` is now the file.
- Variables don't persist between runs unless you use `st.session_state`.
- This is why the logic reads "linear": upload → read → map → table, all top to bottom.

For now the linear flow is fine. Later, to avoid recomputing NDVI on every rerun, we'll cache
results with `@st.cache_data` and `st.session_state`.

---

## 5. Test It

You need a test shapefile. Options:
- Export any polygon from QGIS as a shapefile, then zip the `.shp/.shx/.dbf/.prj`.
- Or download a small admin boundary (e.g. one district) and zip it.
- Put a sample in `data/sample_aoi/` for repeated testing.

Run:

```bash
streamlit run app/main.py
```

Upload the zip. You should see:
- A success message with the feature count
- The AOI outline (red) on the map, zoomed to fit
- The attribute table below

---

## 6. Save the AOI to PostGIS (optional now, useful later)

Add to `app/db.py`:

```python
from geoalchemy2 import Geometry
from sqlalchemy import create_engine, text
from shapely.geometry import MultiPolygon

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)


def save_aoi(name: str, gdf) -> int:
    """Save the AOI's dissolved geometry to the aoi table, return its id."""
    # Merge all features into one geometry, ensure MultiPolygon.
    merged = gdf.unary_union
    if merged.geom_type == "Polygon":
        merged = MultiPolygon([merged])

    with engine.begin() as conn:
        result = conn.execute(
            text("""
                INSERT INTO aoi (name, geom)
                VALUES (:name, ST_GeomFromText(:wkt, 4326))
                RETURNING id;
            """),
            {"name": name, "wkt": merged.wkt},
        )
        return result.scalar()
```

`merged.wkt` is Well-Known Text (e.g. `MULTIPOLYGON(((...)))`), which PostGIS reads with
`ST_GeomFromText`. You can call `save_aoi` behind a "Save AOI" button later.

---

## What Success Looks Like

- Uploading a zipped shapefile shows its outline on the map
- The map zooms to the AOI
- The attribute table displays
- (Optional) The AOI can be saved to PostGIS

Once this works, move to **Step 3: Compute NDVI for the AOI over a date range.**

---

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `No .shp file found` | Zipped the folder, not the files, oddly | Ensure the `.shp` is inside the zip (subfolder is OK) |
| `Shapefile has no CRS` | Missing `.prj` in the zip | Include the `.prj` file when zipping |
| Map shows but no AOI | Reprojection or bounds issue | Confirm `to_crs(4326)`; check `gdf.total_bounds` |
| Map doesn't render | `st_folium` not called / wrong object | Pass the geemap `m` to `st_folium(m, ...)` |
| Everything recomputes on click | Streamlit reruns whole script | Expected; we'll add caching in a later step |
