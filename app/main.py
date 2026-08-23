import sys
from pathlib import Path

# Streamlit runs this file as a script, so the project root isn't on the
# import path. Add it so `from app.x import ...` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from streamlit_folium import st_folium

from app.shapefile_io import read_uploaded_shapefile
from app.mapping import make_map, add_aoi, add_ndvi_layer
from app.gee import init_ee, gdf_to_ee_geometry, ndvi_composite, ndvi_monthly_series
from app.charts import ndvi_line_chart
from app.db import save_aoi, save_series

st.set_page_config(page_title="NDVI Explorer", layout="wide")
st.title("🌱 NDVI Explorer")

init_ee()

with st.sidebar:
    st.header("Controls")
    uploaded = st.file_uploader("Upload shapefile (.zip)", type=["zip"])
    start = st.date_input("From")
    end = st.date_input("To")
    run = st.button("Run Analysis")

gdf = None
if uploaded is not None:
    try:
        gdf = read_uploaded_shapefile(uploaded)
        st.success(f"Loaded {len(gdf)} feature(s).")
    except Exception as e:
        st.error(f"Could not read shapefile: {e}")

if run and gdf is not None:
    with st.spinner("Computing NDVI on Earth Engine…"):
        aoi = gdf_to_ee_geometry(gdf)
        comp = ndvi_composite(aoi, str(start), str(end))
        series = ndvi_monthly_series(aoi, str(start), str(end))

    m = make_map()
    m = add_aoi(m, gdf)
    m = add_ndvi_layer(m, comp, aoi)
    st_folium(m, width=900, height=500)

    st.subheader("NDVI over time")
    if series:
        st.plotly_chart(ndvi_line_chart(series), use_container_width=True)
        # Keep results across reruns so the Save button can use them.
        st.session_state["series"] = series
        st.session_state["gdf"] = gdf
    else:
        st.warning("No cloud-free NDVI found in this range. Try a wider range.")
else:
    m = make_map()
    if gdf is not None:
        m = add_aoi(m, gdf)
    st_folium(m, width=900, height=500)

# --- Save to PostGIS ---
if st.session_state.get("series"):
    st.subheader("Save to database")
    name = st.text_input("AOI name", value="my_aoi")
    if st.button("💾 Save AOI + NDVI"):
        aoi_id = save_aoi(name, st.session_state["gdf"])
        save_series(aoi_id, st.session_state["series"])
        st.success(f"Saved AOI #{aoi_id} with {len(st.session_state['series'])} monthly points.")

