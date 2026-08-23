import sys
import json
from pathlib import Path

# Streamlit runs this file as a script; add project root to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import folium
import pandas as pd
import streamlit as st
from shapely.geometry import shape
from streamlit_folium import st_folium

from app.db import query, load_series, load_aoi_geojson
from app.mapping import make_map, BASEMAPS
from app.charts import vi_line_chart, INDICES


# Cache DB reads so panning/zooming the map doesn't re-query Supabase.
@st.cache_data(ttl=600, show_spinner=False)
def get_aois():
    return query("SELECT id, name FROM aoi ORDER BY name")


@st.cache_data(ttl=600, show_spinner=False)
def get_series(aoi_id):
    return load_series(aoi_id)


@st.cache_data(ttl=600, show_spinner=False)
def get_geojson(aoi_id):
    return load_aoi_geojson(aoi_id)

st.set_page_config(page_title="Vegetation Index Viewer", page_icon="🌱", layout="wide")
st.title("🌱 Vegetation Index Viewer")
st.markdown("Multi-index vegetation monitoring — **Sentinel-2** via Earth Engine, cached in **PostGIS**.")

# Friendly display names for stored AOIs.
DISPLAY = {"dipto_cashew": "Cashew field"}

# ── Controls ─────────────────────────────────────────────────
aois = get_aois()
if aois.empty:
    st.warning("No AOIs stored yet. Run the ingest script first.")
    st.stop()

c_aoi, c_idx = st.columns([2, 2])
with c_aoi:
    labels = {DISPLAY.get(r["name"], r["name"]): r.id for _, r in aois.iterrows()}
    aoi_choice = st.selectbox("Area of interest", list(labels.keys()))
    aoi_id = labels[aoi_choice]
with c_idx:
    idx_labels = {v[0]: k for k, v in INDICES.items()}   # "NDVI" -> "ndvi"
    idx_choice = st.selectbox("Vegetation index", list(idx_labels.keys()))
    index = idx_labels[idx_choice]

st.caption(INDICES[index][1])   # description of the chosen index
st.session_state["aoi_id"] = aoi_id

# ── Load data from PostGIS ───────────────────────────────────
geojson_str = get_geojson(aoi_id)
series = get_series(aoi_id)

st.divider()

# ── KPI cards (for the selected index) ───────────────────────
if series:
    pts = [(r["date"], r[index]) for r in series if r[index] is not None]
    vals = [v for _, v in pts]
    peak_date, peak_val = max(pts, key=lambda p: p[1])
    min_date, min_val = min(pts, key=lambda p: p[1])

    def _month(d):  # "2023-09" or "2023-09-01" -> "Sep 2023"
        return pd.to_datetime(d).strftime("%b %Y")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Months", len(vals))
    c2.metric(f"Avg {idx_choice}", f"{sum(vals)/len(vals):.3f}")
    # Date shown as a caption (no delta -> no extra Streamlit arrow).
    c3.metric(f"Peak {idx_choice}", f"{peak_val:.3f}")
    c3.caption(f"▲ {_month(peak_date)}")
    c4.metric(f"Min {idx_choice}", f"{min_val:.3f}")
    c4.caption(f"▼ {_month(min_date)}")

st.divider()

# ── Map (full width) ─────────────────────────────────────────
st.subheader("Area")
basemap = st.selectbox("Basemap", list(BASEMAPS.keys()))
geom = shape(json.loads(geojson_str))
m = make_map(basemap=basemap)
folium.GeoJson(
    geojson_str, name="AOI",
    style_function=lambda _: {"color": "#c1272d", "weight": 2, "fillOpacity": 0.1},
).add_to(m)
minx, miny, maxx, maxy = geom.bounds
m.fit_bounds([[miny, minx], [maxy, maxx]])
# returned_objects=[] -> map interactions (pan/zoom) don't rerun the script.
st_folium(m, use_container_width=True, height=560, returned_objects=[])

st.divider()

# ── Chart (full width, under the map) ────────────────────────
st.subheader(f"{idx_choice} over time")
if series:
    st.plotly_chart(vi_line_chart(series, index=index), use_container_width=True)
else:
    st.info("No series stored for this AOI.")

# ── Raw data ─────────────────────────────────────────────────
if series:
    tbl = pd.DataFrame(series)
    tbl["date"] = pd.to_datetime(tbl["date"]).dt.strftime("%b %Y")
    for col in ["ndvi", "evi", "savi", "ndre", "gndvi"]:
        tbl[col] = tbl[col].round(3)
    tbl = tbl.rename(columns={
        "date": "Month", "ndvi": "NDVI", "evi": "EVI", "savi": "SAVI",
        "ndre": "NDRE", "gndvi": "GNDVI", "n_images": "Images",
    })
    with st.expander("Show data table"):
        st.dataframe(tbl, use_container_width=True, hide_index=True)
