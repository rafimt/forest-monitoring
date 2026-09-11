import pandas as pd
import plotly.graph_objects as go

# Index key -> (display label, description)
INDICES = {
    "ndvi":  ("NDVI",  "Normalized Difference Vegetation Index"),
    "evi":   ("EVI",   "Enhanced Vegetation Index (less atmosphere/saturation)"),
    "savi":  ("SAVI",  "Soil Adjusted VI (for sparse crops / bare soil)"),
    "ndre":  ("NDRE",  "Red-edge index (early stress, dense crops)"),
    "gndvi": ("GNDVI", "Green NDVI (chlorophyll, water/fertilizer stress)"),
}

# Bangladesh seasons (by month) — a per-season yearly median is far easier to
# read than a noisy all-year line.
#   Monsoon (Jun–Oct)  : wet, vegetation peak
#   Dry-summer (Mar–May): hot pre-monsoon
#   Cool-dry (Nov–Feb) : winter / autumn dry
SEASON_OF_MONTH = {
    1: "Cool-dry", 2: "Cool-dry", 3: "Dry-summer", 4: "Dry-summer",
    5: "Dry-summer", 6: "Monsoon", 7: "Monsoon", 8: "Monsoon",
    9: "Monsoon", 10: "Monsoon", 11: "Cool-dry", 12: "Cool-dry",
}
SEASON_COLORS = {
    "Monsoon": "#1a9850",     # green — peak
    "Dry-summer": "#e08214",  # orange — hot dry
    "Cool-dry": "#4575b4",    # blue — cool dry
}


def vi_line_chart(series, index="ndvi"):
    """Seasonal yearly-median chart: one line per season (Monsoon, Dry-summer,
    Cool-dry), each point = median of that season's months in that year."""
    label = INDICES[index][0]
    df = pd.DataFrame(series)
    if df.empty or "date" not in df:
        return go.Figure().update_layout(title=f"{label} — no data")
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    df["season"] = df["date"].dt.month.map(SEASON_OF_MONTH)
    df = df.dropna(subset=[index])

    # Median of the index per (year, season).
    grp = df.groupby(["year", "season"])[index].median().reset_index()

    fig = go.Figure()
    lo, hi = 0.0, 0.0
    for season, color in SEASON_COLORS.items():
        d = grp[grp["season"] == season].sort_values("year")
        if d.empty:
            continue
        lo = min(lo, d[index].min())
        hi = max(hi, d[index].max())
        fig.add_trace(go.Scatter(
            x=d["year"], y=d[index], name=season, mode="lines+markers",
            line=dict(color=color, width=2.5), marker=dict(size=6),
        ))

    pad = max((hi - lo) * 0.08, 0.05)
    fig.update_layout(
        title=f"{label} — seasonal median by year",
        xaxis_title="Year", yaxis_title=label,
        yaxis_range=[lo - pad, hi + pad],
        hovermode="x unified",
        height=430,                    # match the map height
        legend=dict(orientation="v", yanchor="middle", y=0.10,
                    xanchor="right", x=0.99,
                    bgcolor="rgba(0,0,0,0)", borderwidth=0,
                    font=dict(size=10),      # small so all 3 fit in the 0–0.2 band
                    itemsizing="constant"),
        margin=dict(t=50, r=20, b=40, l=50),
    )
    fig.update_xaxes(dtick=1)   # one tick per year
    if lo - pad < 0:
        fig.add_hline(y=0, line_dash="dot", line_color="#999", opacity=0.6)
    return fig
