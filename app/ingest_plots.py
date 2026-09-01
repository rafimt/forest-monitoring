# Ingest a multi-polygon shapefile as INDIVIDUAL plots (one row + one NDVI/
# index series per polygon), plus the polygon attributes.
#
# Run:  python -m app.ingest_plots
#
# Uses reduceRegions (all plots at once per month) so 69 plots stay efficient.

import glob

import ee
import geopandas as gpd
from shapely import force_2d
from sqlalchemy import text

from app.gee import init_ee, build_index_collection, INDEX_BANDS
from app.db import engine

# ── CONFIG ───────────────────────────────────────────────────
SHP = "data/Plantation_CoxSouth_2019_2022/Plantation_CoxSouth_2019_2022.shp"
AOI_NAME = "coxbazar_south_plantation"   # parent group (already stored)
START, END, MAX_CLOUD, SCALE = "2017-03-28", "2026-09-01", 40, 10

# shapefile column -> plot table column
COLS = {
    "Area_Ha": "area_ha", "Year": "plant_year", "plant_type": "plant_type",
    "ecozone": "ecozone", "div_name": "division", "range_name": "range_name",
    "beat_name": "beat_name", "village": "village", "union": "union_name",
    "Patches": "patches", "JournalID": "journal_id", "Remarks": "remarks",
}


def labels_from_range(gdf):
    """Label each plot by range_name with a running number for duplicates:
    'Whykong Range 1', 'Whykong Range 2', ..."""
    counts, out = {}, []
    for rn in gdf["range_name"].fillna("Unknown"):
        counts[rn] = counts.get(rn, 0) + 1
        out.append(f"{rn} {counts[rn]}")
    return out


def get_parent_aoi_id(conn):
    row = conn.execute(text("SELECT id FROM aoi WHERE name = :n"),
                       {"n": AOI_NAME}).first()
    if row:
        return row.id
    raise SystemExit(f"Parent AOI '{AOI_NAME}' not found — ingest it first.")


def main():
    init_ee()

    gdf = gpd.read_file(SHP).to_crs(4326)
    gdf["geometry"] = gdf.geometry.apply(force_2d)
    gdf["__label"] = labels_from_range(gdf)
    print(f"{len(gdf)} plots read")

    with engine.begin() as conn:
        aoi_id = get_parent_aoi_id(conn)
        # Clear any previous plots for this AOI (cascade clears their series).
        conn.execute(text("DELETE FROM plot WHERE aoi_id = :a"), {"a": aoi_id})

        # Insert plots, keep db id per row index.
        pid_by_idx = {}
        for i, row in gdf.iterrows():
            geom = row.geometry
            if geom.geom_type == "Polygon":
                from shapely.geometry import MultiPolygon
                geom = MultiPolygon([geom])
            vals = {dst: (None if row.get(src) is None else str(row.get(src)))
                    for src, dst in COLS.items()}
            vals["area_ha"] = float(row.get("Area_Ha")) if row.get("Area_Ha") is not None else None
            res = conn.execute(text(f"""
                INSERT INTO plot (aoi_id, plot_name, geom, {", ".join(COLS.values())})
                VALUES (:aoi_id, :name, ST_GeomFromText(:wkt, 4326),
                        {", ".join(":" + c for c in COLS.values())})
                RETURNING id;
            """), {"aoi_id": aoi_id, "name": row["__label"], "wkt": geom.wkt, **vals})
            pid_by_idx[i] = res.scalar()
        print(f"inserted {len(pid_by_idx)} plot rows")

    # Build an EE FeatureCollection of the plots, tagged with their db id.
    feats = []
    for i, row in gdf.iterrows():
        feats.append(ee.Feature(ee.Geometry(row.geometry.__geo_interface__),
                                {"pid": pid_by_idx[i]}))
    plots_fc = ee.FeatureCollection(feats)

    # Whole-AOI collection (bounds cover all plots).
    whole = ee.Geometry(gdf.unary_union.__geo_interface__)
    base = build_index_collection(whole, START, END, MAX_CLOUD).select(INDEX_BANDS)

    start_d, end_d = ee.Date(START), ee.Date(END)
    n_months = int(end_d.difference(start_d, "month").ceil().getInfo())
    print(f"computing {n_months} months over {len(feats)} plots…")

    inserted = 0
    with engine.begin() as conn:
        for m in range(n_months):
            s = start_d.advance(m, "month")
            e = s.advance(1, "month")
            month_imgs = base.filterDate(s, e)
            composite = month_imgs.median()
            date_str = s.format("YYYY-MM").getInfo()
            try:
                # median per plot for every index band, in one call.
                fc = composite.reduceRegions(
                    collection=plots_fc, reducer=ee.Reducer.median(),
                    scale=SCALE, tileScale=4,
                )
                data = fc.getInfo()["features"]
            except Exception:
                continue  # empty/cloudy month -> skip
            for f in data:
                p = f["properties"]
                if p.get("NDVI") is None:
                    continue
                conn.execute(text("""
                    INSERT INTO ndvi_series
                        (aoi_id, plot_id, image_date, median_ndvi, evi, savi,
                         ndre, gndvi, n_images, source)
                    VALUES (:a, :pid, :d, :ndvi, :evi, :savi, :ndre, :gndvi,
                            :n, 'COPERNICUS/S2_SR_HARMONIZED');
                """), {"a": aoi_id, "pid": p["pid"], "d": date_str + "-01",
                       "ndvi": p.get("NDVI"), "evi": p.get("EVI"),
                       "savi": p.get("SAVI"), "ndre": p.get("NDRE"),
                       "gndvi": p.get("GNDVI"), "n": None})
                inserted += 1
            if m % 12 == 0:
                print(f"  ...{date_str} ({inserted} rows)")
    print(f"done: {inserted} plot-month rows stored")


if __name__ == "__main__":
    main()
