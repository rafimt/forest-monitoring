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

from app.db import (
    query, load_series, load_aoi_geojson,
    list_plots, load_plot_series, load_plot_attrs, load_all_plots_geojson,
)
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


@st.cache_data(ttl=600, show_spinner=False)
def get_plots(aoi_name):
    return [(r.id, r.plot_name) for r in list_plots(aoi_name)]


@st.cache_data(ttl=600, show_spinner=False)
def get_plots_geojson(aoi_name):
    return load_all_plots_geojson(aoi_name)


@st.cache_data(ttl=600, show_spinner=False)
def get_plot_series(plot_id):
    return load_plot_series(plot_id)


@st.cache_data(ttl=600, show_spinner=False)
def get_plot_attrs(plot_id):
    return load_plot_attrs(plot_id)

st.set_page_config(page_title="Vegetation Index Viewer", page_icon="🌱", layout="wide")
st.title("🌱 Vegetation Index Viewer")
st.markdown("Multi-index vegetation monitoring — **Sentinel-2** via Earth Engine, cached in **PostGIS**.")

# Friendly display names for stored AOIs.
DISPLAY = {
    "dipto_cashew": "Cashew field",
    "Coxbazar": "Cox's Bazar",
    "coxbazar_south_plantation": "Cox's Bazar South Plantation",
}

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

# ── Plot mode: if this AOI has individual plots, let the user pick one ──
aoi_name = aois.set_index("id").loc[aoi_id, "name"]
plots = get_plots(aoi_name)
plot_id = None
plots_fc = None
if plots:
    plot_labels = {name: pid for pid, name in plots}
    plot_choice = st.selectbox(f"Plot ({len(plots)} total)", list(plot_labels.keys()))
    plot_id = plot_labels[plot_choice]
    plots_fc = get_plots_geojson(aoi_name)

# ── Load data from PostGIS (plot series if a plot is selected) ──
if plot_id:
    geojson_str = None                       # map drawn from plots_fc below
    series = get_plot_series(plot_id)
    attrs = get_plot_attrs(plot_id)
else:
    geojson_str = get_geojson(aoi_id)
    series = get_series(aoi_id)
    attrs = None

st.divider()

# ── Plot attributes ──────────────────────────────────────────
if attrs:
    st.subheader("Plot details")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Area (ha)", f"{attrs.get('area_ha'):.2f}" if attrs.get("area_ha") else "—")
    a2.metric("Plant year", attrs.get("plant_year") or "—")
    a3.metric("Beat", attrs.get("beat_name") or "—")
    a4.metric("Village", attrs.get("village") or "—")
    st.caption(f"Type: {attrs.get('plant_type') or '—'}  ·  "
               f"Range: {attrs.get('range_name') or '—'}  ·  "
               f"Division: {attrs.get('division') or '—'}")
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

# ── Map + chart side by side ─────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Area")
    basemap = st.selectbox("Basemap", list(BASEMAPS.keys()))
    m = make_map(basemap=basemap)

    if plots_fc:
        # Draw all plots; highlight the selected one in red, others gray.
        fc = plots_fc if isinstance(plots_fc, dict) else json.loads(plots_fc)

        def _style(feat):
            sel = feat["properties"]["id"] == plot_id
            return {"color": "#c1272d" if sel else "#666",
                    "weight": 2 if sel else 1,
                    "fillColor": "#ff6b6b" if sel else "#999",
                    "fillOpacity": 0.5 if sel else 0.15}

        folium.GeoJson(
            fc, name="Plots", style_function=_style,
            tooltip=folium.GeoJsonTooltip(fields=["name"], aliases=[""]),
        ).add_to(m)
        # Fit to the selected plot.
        sel = [f for f in fc["features"] if f["properties"]["id"] == plot_id][0]
        b = shape(sel["geometry"]).bounds
        m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
    else:
        geom = shape(json.loads(geojson_str))
        folium.GeoJson(
            geojson_str, name="AOI",
            style_function=lambda _: {"color": "#c1272d", "weight": 2, "fillOpacity": 0.1},
        ).add_to(m)
        minx, miny, maxx, maxy = geom.bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])

    # Stable key -> the map component updates in place instead of remounting
    # (remounting on every rerun is what causes the blink). returned_objects=[]
    # -> pan/zoom don't rerun the script.
    st_folium(m, use_container_width=True, height=520,
              returned_objects=[], key="aoimap")

with right:
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
