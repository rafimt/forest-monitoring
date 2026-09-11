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
    list_plots, load_plot_series, load_all_plots_geojson,
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
    # rows: id, plot_name, range_name, beat_name, area_ha, plant_year,
    #       plant_type, village, division
    return [tuple(r) for r in list_plots(aoi_name)]


@st.cache_data(ttl=600, show_spinner=False)
def get_plots_geojson(aoi_name):
    return load_all_plots_geojson(aoi_name)


@st.cache_data(ttl=600, show_spinner=False)
def get_plot_series(plot_id):
    return load_plot_series(plot_id)

st.set_page_config(page_title="Vegetation Index Viewer", page_icon="🌱", layout="wide")

# Friendly display names for stored AOIs.
DISPLAY = {
    "dipto_cashew": "Cashew field",
    "Coxbazar": "Cox's Bazar",
    "coxbazar_south_plantation": "Cox's Bazar South Plantation",
}

aois = get_aois()
if aois.empty:
    st.warning("No AOIs stored yet. Run the ingest script first.")
    st.stop()

idx_labels = {v[0]: k for k, v in INDICES.items()}   # "NDVI" -> "ndvi"


def _month(d):  # "2023-09" or "2023-09-01" -> "Sep 2023"
    return pd.to_datetime(d).strftime("%b %Y")


# ── All selectors in the sidebar -> compact main area (no scroll to map) ──
with st.sidebar:
    st.header("🌱 Controls")
    labels = {DISPLAY.get(r["name"], r["name"]): r.id for _, r in aois.iterrows()}
    aoi_choice = st.selectbox("Area of interest", list(labels.keys()))
    aoi_id = labels[aoi_choice]
    st.session_state["aoi_id"] = aoi_id

    aoi_name = aois.set_index("id").loc[aoi_id, "name"]
    plots = get_plots(aoi_name)
    plot_id = None
    plots_fc = None
    sel_row = None
    if plots:
        ranges = sorted({p[2] for p in plots if p[2]})
        sel_range = st.selectbox("Range", ranges)
        in_range = [p for p in plots if p[2] == sel_range]
        beats = sorted({p[3] for p in in_range if p[3]})
        sel_beat = st.selectbox("Beat", beats)
        beat_plots = sorted([p for p in in_range if p[3] == sel_beat], key=lambda p: p[1])
        if len(beat_plots) > 1:
            # Label: "Plot_1 · 12.45 ha"
            plabels = {
                f"Plot_{i + 1} · {p[4]:.2f} ha" if p[4] else f"Plot_{i + 1}": p
                for i, p in enumerate(beat_plots)
            }
            sel_row = plabels[st.selectbox(f"Plot ({len(beat_plots)})", list(plabels.keys()))]
        else:
            sel_row = beat_plots[0]
        plot_id = sel_row[0]
        plots_fc = get_plots_geojson(aoi_name)

    idx_choice = st.selectbox("Vegetation index", list(idx_labels.keys()))
    index = idx_labels[idx_choice]
    basemap = st.selectbox("Basemap", list(BASEMAPS.keys()))

# ── Load data from PostGIS ───────────────────────────────────
if plot_id:
    geojson_str = None                       # map drawn from plots_fc below
    series = get_plot_series(plot_id)
    attrs = {
        "area_ha": sel_row[4], "plant_year": sel_row[5],
        "plant_type": sel_row[6], "village": sel_row[7],
        "range_name": sel_row[2], "beat_name": sel_row[3], "division": sel_row[8],
    }
else:
    geojson_str = get_geojson(aoi_id)
    series = get_series(aoi_id)
    attrs = None

# ── Compact header: AOI name + one-line plot details ─────────
st.subheader(f"🌱 {aoi_choice}")
if attrs:
    area = f"{attrs.get('area_ha'):.2f} ha" if attrs.get("area_ha") else "—"
    st.caption(
        f"**Area** {area}  ·  **Year** {attrs.get('plant_year') or '—'}  ·  "
        f"**Beat** {attrs.get('beat_name') or '—'}  ·  "
        f"**Village** {attrs.get('village') or '—'}  ·  "
        f"**Division** {attrs.get('division') or '—'}"
    )
    # Same info as a table (also available by clicking the polygon on the map).
    with st.expander("Plot info (table)"):
        info = pd.DataFrame(
            [
                ("Area (ha)", area),
                ("Plant year", attrs.get("plant_year") or "—"),
                ("Plant type", attrs.get("plant_type") or "—"),
                ("Range", attrs.get("range_name") or "—"),
                ("Beat", attrs.get("beat_name") or "—"),
                ("Village", attrs.get("village") or "—"),
                ("Division", attrs.get("division") or "—"),
            ],
            columns=["Attribute", "Value"],
        )
        st.dataframe(info, use_container_width=True, hide_index=True)

# ── Map + index panel side by side ───────────────────────────
left, right = st.columns([1, 1])

with left:
    m = make_map(basemap=basemap)

    if plots_fc:
        fc = plots_fc if isinstance(plots_fc, dict) else json.loads(plots_fc)
        sel_ids = {plot_id}

        def _popup_table(p):
            """A styled HTML table shown when a plot polygon is clicked."""
            rows = [
                ("Plot", p.get("name")),
                ("Area (ha)", p.get("area_ha")),
                ("Year", p.get("plant_year")),
                ("Type", p.get("plant_type")),
                ("Range", p.get("range_name")),
                ("Beat", p.get("beat_name")),
                ("Village", p.get("village")),
                ("Division", p.get("division")),
            ]
            trs = "".join(
                f"<tr>"
                f"<td style='padding:3px 8px;color:#0b6b3a;font-weight:600;"
                f"border-bottom:1px solid #eee'>{k}</td>"
                f"<td style='padding:3px 8px;border-bottom:1px solid #eee'>"
                f"{v if v not in (None, '') else '—'}</td></tr>"
                for k, v in rows
            )
            return (
                "<div style='font-family:system-ui,sans-serif;font-size:12px'>"
                "<div style='font-weight:700;margin-bottom:4px;color:#0b6b3a'>"
                "Plot details</div>"
                f"<table style='border-collapse:collapse'>{trs}</table></div>"
            )

        from shapely.geometry import shape as _shape
        from shapely.ops import unary_union
        # Add each plot separately so every polygon gets its own table popup.
        for feat in fc["features"]:
            fid = feat["properties"]["id"]
            sel = fid in sel_ids
            folium.GeoJson(
                feat,
                style_function=lambda _f, sel=sel: {
                    "color": "#c1272d" if sel else "#888",
                    "weight": 3 if sel else 1,
                    "fill": False, "fillOpacity": 0},
                tooltip=feat["properties"]["name"],
                popup=folium.Popup(_popup_table(feat["properties"]), max_width=280),
            ).add_to(m)

        selfeats = [f for f in fc["features"] if f["properties"]["id"] in sel_ids]
        if selfeats:
            b = unary_union([_shape(f["geometry"]) for f in selfeats]).bounds
            m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
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
    st_folium(m, use_container_width=True, height=430,
              returned_objects=[], key="aoimap")

with right:
    if not series:
        st.info("No series stored for this selection.")
    else:
        pts = [(r["date"], r[index]) for r in series if r[index] is not None]
        vals = [v for _, v in pts]
        peak_date, peak_val = max(pts, key=lambda p: p[1])
        min_date, min_val = min(pts, key=lambda p: p[1])

        # Compact one-line summary (small font, not big st.metric cards).
        st.markdown(
            f"<div style='font-size:0.9rem;line-height:1.4'>"
            f"<b>Avg</b> {sum(vals)/len(vals):.3f} &nbsp;&nbsp;"
            f"<b>Peak</b> {peak_val:.3f} "
            f"<span style='color:#8a8a8a'>▲ {_month(peak_date)}</span> &nbsp;&nbsp;"
            f"<b>Min</b> {min_val:.3f} "
            f"<span style='color:#8a8a8a'>▼ {_month(min_date)}</span></div>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(vi_line_chart(series, index=index),
                        use_container_width=True)

# ── Data table (full width, centered) ────────────────────────
if series:
    tbl = pd.DataFrame(series)
    tbl["date"] = pd.to_datetime(tbl["date"]).dt.strftime("%b %Y")
    for col in ["ndvi", "evi", "savi", "ndre", "gndvi"]:
        tbl[col] = tbl[col].round(3)
    tbl = tbl.drop(columns=["n_images"], errors="ignore")
    tbl = tbl.rename(columns={
        "date": "Month", "ndvi": "NDVI", "evi": "EVI", "savi": "SAVI",
        "ndre": "NDRE", "gndvi": "GNDVI",
    })
    st.divider()
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.expander("Show data table"):
            st.dataframe(tbl, use_container_width=True, hide_index=True)
