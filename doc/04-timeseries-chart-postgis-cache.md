# Step 4: NDVI Time-Series Line Chart + PostGIS Caching

## Goal

Turn the `{date, median_ndvi, n_images}` monthly list from Step 3 into an interactive Plotly
line chart, and cache results in PostGIS so re-running the same AOI + range is instant (no
repeat GEE call).

---

## Prerequisites

- Step 3 done: `ndvi_monthly_series()` returns `[{date, median_ndvi, n_images}, ...]`
- PostGIS running with the `aoi` and `ndvi_series` tables

---

## Part A — The Line Chart

### 1. `app/charts.py`

```python
import pandas as pd
import plotly.express as px


def ndvi_line_chart(series: list[dict]):
    """Build an interactive NDVI-over-time line chart from
    [{date: 'YYYY-MM', median_ndvi, n_images}, ...] (monthly)."""
    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"])   # 'YYYY-MM' -> first of month
    df = df.sort_values("date")

    fig = px.line(
        df,
        x="date",
        y="median_ndvi",
        markers=True,                          # dot at each month
        title="NDVI over time",
        hover_data=["n_images"],               # show how many scenes fed each month
    )
    fig.update_traces(line_color="#1a9850")    # vegetation green
    fig.update_layout(
        yaxis_title="NDVI",
        xaxis_title="Month",
        yaxis_range=[0, 1],                    # NDVI vegetation range
        hovermode="x unified",
    )
    # Show month names on the x-axis (e.g. "Jun 2023"), not raw dates.
    fig.update_xaxes(dtick="M1", tickformat="%b %Y")
    return fig
```

**Why these choices:**
- **`pd.to_datetime`** — turns `"2023-06"` into a real date so the x-axis spaces months
  correctly by time (not evenly).
- **`tickformat="%b %Y"`** — labels each tick as a **month name + year** (`Jun 2023`), and
  `dtick="M1"` puts one tick per month.
- **`markers=True`** — each dot is one monthly composite; gaps show months with no clear data.
- **`yaxis_range=[0, 1]`** — fixes the scale so charts are comparable between runs.
- **`hovermode="x unified"`** — hovering shows the value for that month cleanly.

The chart is already wired in `main.py` from Step 3:

```python
st.plotly_chart(ndvi_line_chart(series), use_container_width=True)
```

### 2. Reading the Chart

- **Rising line** = greening (crop growth, monsoon vegetation).
- **Falling line** = senescence, harvest, drought, or dry season.
- **Seasonal wave** = a full crop cycle — the classic NDVI signature.
- **A month with low `n_images`** (hover to see it) = fewer clear scenes that month, so trust
  that point a little less. `0` images means the month is dropped entirely.

This line *is* the "NDVI change / time-series analysis" your project set out to show.

---

## Part B — Add a Data Table + CSV Download

Small, high-value additions under the chart:

```python
import pandas as pd

# after st.plotly_chart(...)
df = pd.DataFrame(series)
st.download_button(
    "Download NDVI series (CSV)",
    df.to_csv(index=False).encode(),
    file_name="ndvi_series.csv",
    mime="text/csv",
)
with st.expander("Show data table"):
    st.dataframe(df)
```

Clients love a CSV export — it's often what they actually take away.

---

## Part C — Cache Results in PostGIS

Recomputing NDVI on every rerun is slow and wastes GEE quota. Cache the series keyed by the AOI
and date range.

### 3. Extend `app/db.py`

```python
from sqlalchemy import create_engine, text
from shapely.geometry import MultiPolygon

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)


def save_aoi(name: str, gdf) -> int:
    """Insert the AOI geometry, return its new id."""
    merged = gdf.unary_union
    if merged.geom_type == "Polygon":
        merged = MultiPolygon([merged])
    with engine.begin() as conn:
        return conn.execute(
            text("""
                INSERT INTO aoi (name, geom)
                VALUES (:name, ST_GeomFromText(:wkt, 4326))
                RETURNING id;
            """),
            {"name": name, "wkt": merged.wkt},
        ).scalar()


def save_series(aoi_id: int, series: list[dict],
                source="COPERNICUS/S2_SR_HARMONIZED"):
    """Store each monthly {date, median_ndvi} row for an AOI.
    Monthly dates are 'YYYY-MM'; the image_date column is a DATE, so we
    store the first of the month ('YYYY-MM-01')."""
    with engine.begin() as conn:
        for row in series:
            d = row["date"]
            if len(d) == 7:              # 'YYYY-MM' -> 'YYYY-MM-01'
                d = d + "-01"
            conn.execute(
                text("""
                    INSERT INTO ndvi_series
                        (aoi_id, image_date, median_ndvi, n_images, source)
                    VALUES (:aoi_id, :d, :v, :n, :src);
                """),
                {"aoi_id": aoi_id, "d": d, "v": row["median_ndvi"],
                 "n": row.get("n_images"), "src": source},
            )


def load_series(aoi_id: int) -> list[dict]:
    """Load a previously computed series for an AOI, ordered by date."""
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT image_date, median_ndvi FROM ndvi_series
                WHERE aoi_id = :aoi_id
                ORDER BY image_date;
            """),
            {"aoi_id": aoi_id},
        ).all()
    return [{"date": str(r.image_date), "median_ndvi": r.median_ndvi} for r in rows]
```

### 4. Wire caching into `main.py`

A simple "Save" button after a run:

```python
if run and gdf is not None:
    # ... compute comp + series (from Step 3) ...

    st.session_state["series"] = series      # keep across reruns
    st.session_state["gdf"] = gdf

# Save block
if st.session_state.get("series"):
    name = st.text_input("AOI name to save", value="my_aoi")
    if st.button("💾 Save to database"):
        aoi_id = save_aoi(name, st.session_state["gdf"])
        save_series(aoi_id, st.session_state["series"])
        st.success(f"Saved as AOI #{aoi_id} ({len(st.session_state['series'])} points).")
```

> **`st.session_state`** is Streamlit's way to keep values across reruns. Without it, the series
> would vanish the moment you click another widget (because the script re-runs top to bottom).

### 5. Load a Saved AOI

Add a sidebar selector to reload past analyses without touching GEE:

```python
def list_aois():
    with engine.begin() as conn:
        return conn.execute(text("SELECT id, name FROM aoi ORDER BY id DESC;")).all()

# in the sidebar:
saved = list_aois()
if saved:
    choice = st.selectbox("Load saved AOI",
                          options=[f"{r.id} — {r.name}" for r in saved])
    if st.button("Load"):
        aoi_id = int(choice.split(" — ")[0])
        series = load_series(aoi_id)
        st.plotly_chart(ndvi_line_chart(series), use_container_width=True)
```

---

## Part D — Optional: Cache the GEE Call Itself

Even before saving to the DB, cache the expensive GEE compute within a session so reruns don't
recompute:

```python
@st.cache_data(show_spinner=False)
def compute_series_cached(geojson_str: str, start: str, end: str):
    import json, ee
    from app.gee import ndvi_monthly_series
    aoi = ee.Geometry(json.loads(geojson_str))
    return ndvi_monthly_series(aoi, start, end)
```

`@st.cache_data` memoizes by arguments — same AOI + dates returns instantly on rerun. Pass the
AOI as a JSON string (cache keys must be hashable).

---

## Verify

1. Run an analysis → line chart appears, trending with the season.
2. Download the CSV → opens with `date, median_ndvi` columns.
3. Save to database → check it landed:

```bash
docker exec -it ndvi_db psql -U ndvi_user -d ndvi -c \
  "SELECT a.name, COUNT(*) FROM aoi a JOIN ndvi_series s ON s.aoi_id=a.id GROUP BY a.name;"
```

4. Reload the saved AOI → chart redraws with **no GEE call**.

---

## What Success Looks Like

- Interactive NDVI line chart with a seasonal trend
- CSV download works
- Series saves to PostGIS and reloads instantly
- `st.session_state` keeps data across reruns

Once this works, the core app is complete. Next: **Step 5 — polish, Dockerize, deploy.**

---

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| Chart data vanishes on click | Not using `session_state` | Store `series`/`gdf` in `st.session_state` |
| x-axis evenly spaced (wrong) | Dates left as strings | `pd.to_datetime(df["date"])` |
| Duplicate rows in DB | Saved same run twice | Add a UNIQUE(aoi_id, image_date) or clear first |
| Recomputes every interaction | No caching | Use `@st.cache_data` and/or DB cache |
| `ST_GeomFromText` error | Geometry not WKT / wrong SRID | Ensure `merged.wkt` and SRID 4326 |
