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


def vi_line_chart(series, index="ndvi", roll=3):
    """Line chart of one vegetation index over time: raw monthly (faint) +
    a bold rolling-mean trend. `index` is one of INDICES keys."""
    label = INDICES[index][0]
    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    df["trend"] = df[index].rolling(roll, min_periods=1, center=True).mean()

    # Auto y-range with padding, so negative values (water / bare soil) show.
    lo = min(df[index].min(), 0.0)
    hi = max(df[index].max(), 0.0)
    pad = max((hi - lo) * 0.08, 0.05)
    y_range = [lo - pad, hi + pad]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df[index],
        name=f"Monthly {label}",
        mode="lines+markers",
        line=dict(color="#8fd19e", width=1),
        marker=dict(size=5),
        opacity=0.6,
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["trend"],
        name=f"{roll}-mo trend",
        line=dict(color="#1a9850", width=3),
    ))
    fig.update_layout(
        title=f"{label} over time",
        xaxis_title="Month",
        yaxis_title=label,
        yaxis_range=y_range,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=60, r=20, b=40, l=50),
    )
    fig.update_xaxes(tickformat="%b %Y")
    # Zero line (only visible when the data actually dips below 0).
    if y_range[0] < 0:
        fig.add_hline(y=0, line_dash="dot", line_color="#999", opacity=0.7)
    return fig
