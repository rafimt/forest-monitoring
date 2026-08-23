# Step 3: Compute NDVI for the AOI over a Date Range

## Goal

The heart of the app: take the uploaded AOI and a from-month → to-month range, and use Google
Earth Engine to compute NDVI. Produce two things:
1. An **NDVI composite image** (for the map)
2. A **mean-NDVI-per-date series** (for the time-series chart)

---

## Prerequisites

- Step 2 done: AOI uploads and shows on the map
- GEE authenticated; `ee.Initialize(project="rmtumon")` works

---

## What Is NDVI?

**NDVI = (NIR − Red) / (NIR + Red)** — the Normalized Difference Vegetation Index.

- Healthy vegetation reflects a lot of near-infrared (NIR) and absorbs red light → high NDVI.
- Water, bare soil, and buildings → low or negative NDVI.
- Range: **−1 to +1**. Dense green vegetation is typically **0.6–0.9**.

For **Sentinel-2**, the bands are:
- NIR = band **B8**
- Red = band **B4**

So NDVI = `(B8 − B4) / (B8 + B4)`.

---

## Sentinel-2 in Earth Engine

The collection we use: **`COPERNICUS/S2_SR_HARMONIZED`** (Sentinel-2 Surface Reflectance,
harmonized). Each image has:
- Spectral bands (`B2`, `B4`, `B8`, ...)
- An `SCL` band (Scene Classification) used to mask clouds
- A `CLOUDY_PIXEL_PERCENTAGE` property for pre-filtering

---

## 1. Earth Engine Module — `app/gee.py`

```python
import ee

from app.config import settings

_initialized = False


def init_ee():
    """Initialize Earth Engine once. Safe to call repeatedly (Streamlit reruns)."""
    global _initialized
    if not _initialized:
        ee.Initialize(project=settings.gee_project)
        _initialized = True


def gdf_to_ee_geometry(gdf) -> ee.Geometry:
    """Convert a geopandas GeoDataFrame (EPSG:4326) to an ee.Geometry."""
    # Merge all features into one geometry, then to GeoJSON, then to ee.
    merged = gdf.unary_union
    return ee.Geometry(merged.__geo_interface__)


def mask_s2_clouds(image):
    """Mask clouds/cirrus using the SCL band.
    SCL classes 3 (cloud shadow), 8/9 (clouds), 10 (cirrus) are removed."""
    scl = image.select("SCL")
    mask = (
        scl.neq(3)
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
    )
    return image.updateMask(mask)


def add_ndvi(image):
    """Add an 'NDVI' band computed from B8 (NIR) and B4 (Red)."""
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    return image.addBands(ndvi)


def build_ndvi_collection(aoi: ee.Geometry, start: str, end: str,
                          max_cloud=40) -> ee.ImageCollection:
    """Return a Sentinel-2 collection over the AOI + date range,
    cloud-masked, with an NDVI band added to each image."""
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
        .map(mask_s2_clouds)
        .map(add_ndvi)
    )
```

**Line by line:**
- **`filterBounds(aoi)`** — keep only scenes overlapping the AOI.
- **`filterDate(start, end)`** — keep only scenes in the date range (`"2023-01-01"` format).
- **`filter(...CLOUDY_PIXEL_PERCENTAGE < 40)`** — drop very cloudy scenes early (fast).
- **`.map(mask_s2_clouds)`** — remove cloudy *pixels* within each remaining scene.
- **`.map(add_ndvi)`** — compute the NDVI band for every image.

Everything here is **lazy**: nothing runs until you ask for a result (`.getInfo()`,
`getMapId`, etc.). GEE builds a computation graph and runs it server-side on demand.

---

## 2. The NDVI Composite (for the map)

```python
def ndvi_composite(collection: ee.ImageCollection) -> ee.Image:
    """Median NDVI over the whole period — one clean image for the map."""
    return collection.select("NDVI").median()
```

**Why median?** Over many dates, the median NDVI per pixel is robust to leftover clouds and
outliers — a cleaner map than any single date.

---

## 3. The Time Series — MONTHLY MEDIAN (for the chart)

This is the key part for your "NDVI change over time" requirement.

**Why monthly, not per-image:** Sentinel-2 passes every ~5 days, so a per-image series means
20–70 `reduceRegion` calls over a range — heavy compute, noisy line, and gaps on cloudy days.
Instead we aggregate **one value per month**:

```
For each month in the range:
   1. take that month's NDVI images
   2. median-composite them        → one clean NDVI image for the month
   3. spatial mean over the AOI     → one number for the month
```

Two reductions stacked, **both median**: **median across the month's dates** (kills
clouds/outliers) then **median across the AOI's pixels** (one representative value, resistant
to a few odd pixels).

```python
def ndvi_monthly_series(aoi: ee.Geometry, start: str, end: str,
                        max_cloud=40, scale=10) -> list[dict]:
    """Return [{date: 'YYYY-MM', median_ndvi, n_images}, ...] — one point per month.
    Monthly = median composite of the month, then spatial MEDIAN over the AOI."""

    start_date = ee.Date(start)
    end_date = ee.Date(end)

    # The cloud-masked NDVI collection for the whole range (from section 1).
    base = build_ndvi_collection(aoi, start, end, max_cloud).select("NDVI")

    # How many whole months the range spans, as a server-side list [0,1,2,...].
    n_months = end_date.difference(start_date, "month").ceil()
    months = ee.List.sequence(0, n_months.subtract(1))

    def one_month(m):
        m = ee.Number(m)
        s = start_date.advance(m, "month")          # month start
        e = s.advance(1, "month")                    # next month start
        month_imgs = base.filterDate(s, e)           # images in this month

        composite = month_imgs.median()              # 1) median across the month
        median = composite.reduceRegion(             # 2) median across the AOI pixels
            reducer=ee.Reducer.median(),
            geometry=aoi,
            scale=scale,                             # 10 m for Sentinel-2
            maxPixels=1e9,
        ).get("NDVI")

        return ee.Feature(None, {
            "date": s.format("YYYY-MM"),
            "median_ndvi": median,
            "n_images": month_imgs.size(),           # how many scenes fed the month
        })

    # Build a FeatureCollection of monthly features, pull to Python in ONE call.
    fc = ee.FeatureCollection(months.map(one_month))
    features = fc.getInfo()["features"]

    rows = []
    for f in features:
        p = f["properties"]
        if p.get("median_ndvi") is not None:         # skip months with no clear data
            rows.append({
                "date": p["date"],
                "median_ndvi": p["median_ndvi"],
                "n_images": p.get("n_images", 0),
            })

    rows.sort(key=lambda r: r["date"])
    return rows
```

**Two critical concepts:**
- **`reduceRegion`** — takes an image band + an area, returns one statistic over that area.
  Here it gives the AOI's **median** NDVI for each month's composite. This is the core
  analytics op.
- **`.getInfo()` once** — we map over months *server-side* and pull the whole FeatureCollection
  in a single round trip. Never call `getInfo()` in a loop — each call hits Google's servers.

**Compute saved:** a 12-month range = **12** `reduceRegion` calls (one per monthly composite),
vs ~70 for per-image. Much faster, much smoother line.

> **Want per-image instead later?** Map `reduceRegion` over `collection` directly (one feature
> per image). The monthly version is the recommended default for vegetation monitoring.

---

## 4. Wire Into Streamlit — update `app/main.py`

```python
import streamlit as st
from streamlit_folium import st_folium

from app.shapefile_io import read_uploaded_shapefile
from app.mapping import make_map, add_aoi, add_ndvi_layer
from app.gee import (
    init_ee, gdf_to_ee_geometry, build_ndvi_collection,
    ndvi_composite, ndvi_monthly_series,
)
from app.charts import ndvi_line_chart

st.set_page_config(page_title="NDVI Explorer", layout="wide")
st.title("🌱 NDVI Explorer")

init_ee()   # connect to Earth Engine

with st.sidebar:
    st.header("Controls")
    uploaded = st.file_uploader("Upload shapefile (.zip)", type=["zip"])
    start = st.date_input("From")
    end = st.date_input("To")
    run = st.button("Run Analysis")

gdf = None
if uploaded is not None:
    gdf = read_uploaded_shapefile(uploaded)
    st.success(f"Loaded {len(gdf)} feature(s).")

if run and gdf is not None:
    with st.spinner("Computing NDVI on Earth Engine…"):
        aoi = gdf_to_ee_geometry(gdf)
        coll = build_ndvi_collection(aoi, str(start), str(end))

        # For the map
        comp = ndvi_composite(coll)

        # For the chart — one median point per month
        series = ndvi_monthly_series(aoi, str(start), str(end))

    # Map with the NDVI layer
    m = make_map()
    m = add_aoi(m, gdf)
    m = add_ndvi_layer(m, comp, aoi)
    st_folium(m, width=900, height=500)

    # Time-series chart
    st.subheader("NDVI over time")
    if series:
        st.plotly_chart(ndvi_line_chart(series), use_container_width=True)
    else:
        st.warning("No cloud-free NDVI values found in this range. Try a wider range.")
else:
    # Just show the AOI (or an empty map) before running
    m = make_map()
    if gdf is not None:
        m = add_aoi(m, gdf)
    st_folium(m, width=900, height=500)
```

---

## 5. Add the NDVI Map Layer — extend `app/mapping.py`

```python
def add_ndvi_layer(m, ndvi_image, aoi):
    """Add the NDVI composite to the map, clipped to the AOI, green ramp."""
    vis = {
        "min": 0.0,
        "max": 0.8,
        "palette": ["#d73027", "#fee08b", "#1a9850"],  # red -> yellow -> green
    }
    m.addLayer(ndvi_image.clip(aoi), vis, "NDVI")
    m.add_colorbar(vis, label="NDVI")
    return m
```

`ndvi_image.clip(aoi)` limits rendering to the AOI. The palette maps low NDVI (red/bare) to
high NDVI (green/vegetated).

---

## 6. Verify

Upload an AOI (ideally an agricultural or vegetated area), pick a range of a few months, click
**Run Analysis**. You should see:

- A spinner while GEE computes
- The NDVI composite on the map, green where vegetation is dense
- A colorbar legend
- (Chart comes fully alive in Step 4)

Test with a range like **2023-06-01 → 2023-10-01** over a green region for clear results.

---

## Performance & Gotchas

- **First run is slow** — GEE compiles and runs server-side; later runs on the same area are
  faster (GEE caches).
- **`scale=10`** for Sentinel-2. Larger scale = coarser but faster; smaller than 10 wastes time.
- **`maxPixels=1e9`** prevents "too many pixels" errors on big AOIs.
- **Empty series?** Your range may be too short or too cloudy — widen the dates or raise
  `max_cloud`.
- **Streamlit reruns** — `init_ee()` guards against re-initializing every rerun.

---

## What Success Looks Like

- NDVI composite renders on the map for the AOI + range
- `ndvi_monthly_series()` returns a list of `{date, median_ndvi, n_images}` points (one per month)
- Vegetated areas are green, bare/water areas red

Once this works, move to **Step 4: NDVI time-series line chart (and caching to PostGIS).**

---

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `ee.Initialize` permission error | Wrong project / not approved | Use `project="rmtumon"`; confirm EE access |
| Map layer blank | AOI outside data, or all cloudy | Check AOI location; widen range; raise `max_cloud` |
| `Too many pixels` | AOI large + small scale | Keep `maxPixels=1e9`; increase `scale` |
| Series all `None` | Every scene fully cloud-masked | Widen date range; raise cloud threshold |
| Very slow | Huge AOI or long range | Start with a small AOI + a few months |
