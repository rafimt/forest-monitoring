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
    # (id, plot_name, range_name, beat_name)
    return [(r.id, r.plot_name, r.range_name, r.beat_name)
            for r in list_plots(aoi_name)]


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

idx_labels = {v[0]: k for k, v in INDICES.items()}   # "NDVI" -> "ndvi"

labels = {DISPLAY.get(r["name"], r["name"]): r.id for _, r in aois.iterrows()}
aoi_choice = st.selectbox("Area of interest", list(labels.keys()))
aoi_id = labels[aoi_choice]

st.session_state["aoi_id"] = aoi_id

# ── Plot mode: if this AOI has individual plots, let the user pick one ──
aoi_name = aois.set_index("id").loc[aoi_id, "name"]
plots = get_plots(aoi_name)
plot_id = None
plots_fc = None
if plots:
    # Cascading filters: Range -> Beat -> Plot.
    ranges = sorted({r for _, _, r, _ in plots if r})
    r1, r2, r3 = st.columns(3)
    with r1:
        sel_range = st.selectbox("Range", ranges)
    in_range = [p for p in plots if p[2] == sel_range]

    beats = sorted({b for _, _, _, b in in_range if b})
    with r2:
        sel_beat = st.selectbox("Beat", beats)
    in_beat = [p for p in in_range if p[3] == sel_beat]

    plot_labels = {name: pid for pid, name, _, _ in in_beat}
    with r3:
        plot_choice = st.selectbox(f"Plot ({len(in_beat)})", list(plot_labels.keys()))
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

# ── Plot attributes (depends on plot, not index) ─────────────
if attrs:
    st.subheader("Plot details")
    area = f"{attrs.get('area_ha'):.2f}" if attrs.get("area_ha") else "—"
    # Markdown (not st.metric) so long text like "Rajapalong Beat" wraps
    # instead of being truncated with an ellipsis.
    a1, a2, a3, a4 = st.columns(4)
    a1.markdown(f"**Area (ha)**<br>{area}", unsafe_allow_html=True)
    a2.markdown(f"**Plant year**<br>{attrs.get('plant_year') or '—'}", unsafe_allow_html=True)
    a3.markdown(f"**Beat**<br>{attrs.get('beat_name') or '—'}", unsafe_allow_html=True)
    a4.markdown(f"**Village**<br>{attrs.get('village') or '—'}", unsafe_allow_html=True)
    st.caption(f"Type: {attrs.get('plant_type') or '—'}  ·  "
               f"Range: {attrs.get('range_name') or '—'}  ·  "
               f"Division: {attrs.get('division') or '—'}")

st.divider()


def _month(d):  # "2023-09" or "2023-09-01" -> "Sep 2023"
    return pd.to_datetime(d).strftime("%b %Y")


# ── Map + index panel side by side ───────────────────────────
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
        # Fit to ALL plots (whole plantation), not the selected one, so the map
        # stays framed and doesn't jump/zoom when you switch plots.
        from shapely.geometry import shape as _shape
        from shapely.ops import unary_union
        allb = unary_union([_shape(f["geometry"]) for f in fc["features"]]).bounds
        m.fit_bounds([[allb[1], allb[0]], [allb[3], allb[2]]])
    else:
        geom = shape(json.loads(geojson_str))
        folium.GeoJson(
            geojson_str, name="AOI",
            style_function=lambda _: {"color": "#c1272d", "weight": 4,
                                      "fill": False, "fillOpacity": 0},
        ).add_to(m)
        minx, miny, maxx, maxy = geom.bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])

    # Stable key -> the map updates in place instead of remounting (no blink).
    st_folium(m, use_container_width=True, height=520,
              returned_objects=[], key="aoimap")

with right:
    # Fragment: changing the index reruns ONLY this block, never the map.
    @st.fragment
    def index_panel():
        idx_choice = st.selectbox("Vegetation index", list(idx_labels.keys()))
        index = idx_labels[idx_choice]
        st.caption(INDICES[index][1])

        if not series:
            st.info("No series stored for this selection.")
            return

        pts = [(r["date"], r[index]) for r in series if r[index] is not None]
        vals = [v for _, v in pts]
        peak_date, peak_val = max(pts, key=lambda p: p[1])
        min_date, min_val = min(pts, key=lambda p: p[1])

        k1, k2, k3 = st.columns(3)
        k1.metric(f"Avg {idx_choice}", f"{sum(vals)/len(vals):.3f}")
        k2.metric("Peak", f"{peak_val:.3f}")
        k2.caption(f"▲ {_month(peak_date)}")
        k3.metric("Min", f"{min_val:.3f}")
        k3.caption(f"▼ {_month(min_date)}")

        st.plotly_chart(vi_line_chart(series, index=index), use_container_width=True)

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

    index_panel()
