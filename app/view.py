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

# Trim Streamlit's large default top padding so the header sits near the top
# (but leave room so it isn't clipped by the top toolbar).
st.markdown(
    "<style>.block-container{padding-top:2.5rem;padding-left:1.5rem;"
    "padding-right:1.5rem;}</style>",
    unsafe_allow_html=True,
)


def dash(v):
    """Show an em dash for missing/NULL values."""
    if v is None or str(v).strip() in ("", "NULL", "None", "nan"):
        return "—"
    return v


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

        # If the user changed a dropdown, drop any map-click override.
        dd_sig = (aoi_id, sel_range, sel_beat, plot_id)
        if st.session_state.get("_dd_sig") != dd_sig:
            st.session_state["_dd_sig"] = dd_sig
            st.session_state.pop("_click_plot", None)
        # Apply a map-click selection (set on a previous run) if still valid.
        cp = st.session_state.get("_click_plot")
        if cp is not None:
            match = next((p for p in plots if p[0] == cp), None)
            if match:
                sel_row, plot_id = match, match[0]

    idx_choice = st.selectbox("Vegetation index", list(idx_labels.keys()))
    index = idx_labels[idx_choice]

    st.markdown("**Seasons**")
    seasons = []
    if st.checkbox("Monsoon", value=True):
        seasons.append("Monsoon")
    if st.checkbox("Dry-summer", value=True):
        seasons.append("Dry-summer")
    if st.checkbox("Cool-dry", value=True):
        seasons.append("Cool-dry")
    st.caption("Monsoon: Jun–Oct · Dry-summer: Mar–May · Cool-dry: Nov–Feb")

    _bm = list(BASEMAPS.keys())
    _default_bm = _bm.index("Esri Satellite") if "Esri Satellite" in _bm else 0
    basemap = st.selectbox("Basemap", _bm, index=_default_bm)

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

# ── Compact header: AOI name + one-line description of the selected index ──
st.subheader(f"🌱 {aoi_choice}")
st.caption(f"**{idx_choice}** — {INDICES[index][1]}")
with st.expander("About the indices"):
    st.markdown(
        "- **NDVI** — Normalized Difference Vegetation Index: overall greenness "
        "`(NIR − Red) / (NIR + Red)`.\n"
        "- **EVI** — Enhanced Vegetation Index: like NDVI but corrects for "
        "atmosphere and canopy saturation in dense vegetation.\n"
        "- **SAVI** — Soil Adjusted Vegetation Index: reduces bare-soil influence, "
        "good for sparse or young plantations.\n"
        "- **NDRE** — Normalized Difference Red Edge: uses the red-edge band to "
        "spot early stress and monitor dense canopies where NDVI saturates.\n"
        "- **GNDVI** — Green NDVI: uses green instead of red to track chlorophyll "
        "and early water/fertilizer stress."
    )

# ── Map + index panel side by side (map gets more space) ─────
left, right = st.columns([1.4, 1])

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
        # Label each plot as "<beat>_Plot N" (N numbered within its beat).
        label_by_id = {}
        _by_beat = {}
        for feat in sorted(fc["features"], key=lambda f: f["properties"]["name"]):
            bn = feat["properties"].get("beat_name") or "?"
            _by_beat.setdefault(bn, []).append(feat)
        for bn, feats in _by_beat.items():
            for i, feat in enumerate(feats, 1):
                label_by_id[feat["properties"]["id"]] = f"{bn}_Plot {i}"
        id_by_label = {v: k for k, v in label_by_id.items()}

        # Add each plot separately: outline + centre label + hover + popup.
        for feat in fc["features"]:
            fid = feat["properties"]["id"]
            sel = fid in sel_ids
            label = label_by_id[fid]
            folium.GeoJson(
                feat,
                style_function=lambda _f, sel=sel: {
                    "color": "#c1272d" if sel else "#000000",
                    "weight": 3,
                    "fill": False, "fillOpacity": 0},
                tooltip=label,   # hover shows the same beat_Plot label
                popup=folium.Popup(_popup_table(feat["properties"]), max_width=280),
            ).add_to(m)
            # Label in the middle of the polygon.
            c = _shape(feat["geometry"]).centroid
            folium.Marker(
                [c.y, c.x],
                icon=folium.DivIcon(html=(
                    "<div style='font-size:10px;font-weight:600;color:#111;"
                    "white-space:nowrap;text-shadow:0 0 2px #fff,0 0 2px #fff'>"
                    f"{label}</div>")),
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
    # Capture polygon clicks (tooltip = plot name) so clicking selects a plot.
    map_out = st_folium(
        m, use_container_width=True, height=560, key="aoimap",
        returned_objects=["last_object_clicked_tooltip"],
    )
    if plots_fc and map_out:
        clicked_label = map_out.get("last_object_clicked_tooltip")
        clicked_id = id_by_label.get((clicked_label or "").strip())
        if clicked_id and clicked_id != st.session_state.get("_click_plot"):
            st.session_state["_click_plot"] = clicked_id
            st.rerun()

    # Plot info table, underneath the map.
    if attrs:
        info = pd.DataFrame(
            [
                ("Area (ha)", f"{attrs.get('area_ha'):.2f}" if attrs.get("area_ha") else "—"),
                ("Plant year", dash(attrs.get("plant_year"))),
                ("Plant type", dash(attrs.get("plant_type"))),
                ("Range", dash(attrs.get("range_name"))),
                ("Beat", dash(attrs.get("beat_name"))),
                ("Village", dash(attrs.get("village"))),
                ("Division", dash(attrs.get("division"))),
            ],
            columns=["Attribute", "Value"],
        )
        with st.expander("Plot info", expanded=False):
            st.dataframe(info, use_container_width=True, hide_index=True)

with right:
    if not series:
        st.info("No series stored for this selection.")
    else:
        pts = [(r["date"], r[index]) for r in series if r[index] is not None]
        vals = [v for _, v in pts]
        peak_date, peak_val = max(pts, key=lambda p: p[1])
        min_date, min_val = min(pts, key=lambda p: p[1])

        # Compact one-line summary, centered over the chart.
        st.markdown(
            f"<div style='font-size:0.9rem;line-height:1.4;text-align:center'>"
            f"<b>Avg</b> {sum(vals)/len(vals):.3f} &nbsp;&nbsp;"
            f"<b>Peak</b> {peak_val:.3f} "
            f"<span style='color:#8a8a8a'>▲ {_month(peak_date)}</span> &nbsp;&nbsp;"
            f"<b>Min</b> {min_val:.3f} "
            f"<span style='color:#8a8a8a'>▼ {_month(min_date)}</span></div>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(vi_line_chart(series, index=index, seasons=seasons),
                        use_container_width=True)

        # Indices table, underneath the chart.
        tbl = pd.DataFrame(series)
        tbl["date"] = pd.to_datetime(tbl["date"]).dt.strftime("%b %Y")
        for col in ["ndvi", "evi", "savi", "ndre", "gndvi"]:
            tbl[col] = tbl[col].round(3)
        tbl = tbl.drop(columns=["n_images"], errors="ignore")
        tbl = tbl.rename(columns={
            "date": "Month", "ndvi": "NDVI", "evi": "EVI", "savi": "SAVI",
            "ndre": "NDRE", "gndvi": "GNDVI",
        })
        with st.expander("Indices table", expanded=False):
            st.dataframe(tbl, use_container_width=True, hide_index=True)
