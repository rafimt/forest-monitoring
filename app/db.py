import pandas as pd
from shapely.geometry import MultiPolygon
from sqlalchemy import create_engine, text

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)


def query(sql: str, params=None) -> pd.DataFrame:
    """Run a read-only SQL query and return a pandas DataFrame.
    Use named params, e.g. query('... WHERE id = :id', {'id': 3})."""
    with engine.begin() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def save_aoi(name: str, gdf) -> int:
    """Insert the AOI geometry, return its id. If an AOI with the same name
    already exists, it (and its cascaded ndvi_series) is replaced."""
    merged = gdf.unary_union
    if merged.geom_type == "Polygon":
        merged = MultiPolygon([merged])
    with engine.begin() as conn:
        # Drop any existing AOI of this name (ON DELETE CASCADE clears its series).
        conn.execute(text("DELETE FROM aoi WHERE name = :name;"), {"name": name})
        return conn.execute(
            text("""
                INSERT INTO aoi (name, geom)
                VALUES (:name, ST_GeomFromText(:wkt, 4326))
                RETURNING id;
            """),
            {"name": name, "wkt": merged.wkt},
        ).scalar()


def save_series(aoi_id: int, series, source="COPERNICUS/S2_SR_HARMONIZED"):
    """Store each monthly row {date, ndvi, evi, savi, ndre, gndvi, n_images}.
    Monthly dates are 'YYYY-MM'; image_date is a DATE, so store 'YYYY-MM-01'."""
    with engine.begin() as conn:
        for row in series:
            d = row["date"]
            if len(d) == 7:
                d = d + "-01"
            conn.execute(
                text("""
                    INSERT INTO ndvi_series
                        (aoi_id, image_date, median_ndvi, evi, savi, ndre, gndvi,
                         n_images, source)
                    VALUES (:aoi_id, :d, :ndvi, :evi, :savi, :ndre, :gndvi, :n, :src);
                """),
                {"aoi_id": aoi_id, "d": d,
                 "ndvi": row.get("ndvi"), "evi": row.get("evi"),
                 "savi": row.get("savi"), "ndre": row.get("ndre"),
                 "gndvi": row.get("gndvi"),
                 "n": row.get("n_images"), "src": source},
            )


def load_series(aoi_id: int):
    """Load a previously computed multi-index series for an AOI, by date."""
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT image_date, median_ndvi, evi, savi, ndre, gndvi, n_images
                FROM ndvi_series
                WHERE aoi_id = :aoi_id
                ORDER BY image_date;
            """),
            {"aoi_id": aoi_id},
        ).all()
    return [
        {"date": str(r.image_date), "ndvi": r.median_ndvi, "evi": r.evi,
         "savi": r.savi, "ndre": r.ndre, "gndvi": r.gndvi, "n_images": r.n_images}
        for r in rows
    ]


def list_aois():
    with engine.begin() as conn:
        return conn.execute(text("SELECT id, name FROM aoi ORDER BY id DESC;")).all()
    
def load_aoi_geojson(aoi_id):
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT ST_AsGeoJSON(geom) FROM aoi WHERE id = :id;"),
            {"id": aoi_id},
        ).scalar()
