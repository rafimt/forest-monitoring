# Standalone NDVI ingest: compute monthly median NDVI for an AOI
# over a date range and store it (AOI + series) in PostGIS. No Streamlit.
#
# Edit the CONFIG block below, then run:
#   python -m app.ingest_ndvi
#
# Accepts: .shp | .gpkg (GeoPackage) | .geojson | .zip of a shapefile set.

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd

from app.gee import init_ee, gdf_to_ee_geometry, vi_monthly_series
from app.db import save_aoi, save_series

# ── CONFIG — one dict per AOI to ingest ──────────────────────
# input: .shp | .gpkg | .geojson | .zip (looked up under data/input/)
# layer: GeoPackage layer name, or None for single-layer
JOBS = [
    {"input": "dipto_cashew.gpkg", "layer": None, "name": "dipto_cashew",
     "start": "2017-03-28", "end": "2026-01-01"},
    {"input": "Coxbazar.gpkg", "layer": None, "name": "Coxbazar",
     "start": "2017-03-28", "end": "2026-01-01"},
    {"input": "Mangrove.gpkg", "layer": None, "name": "Mangrove",
     "start": "2017-03-28", "end": "2026-01-01"},
    {"input": "Woodlot.gpkg", "layer": None, "name": "Woodlot",
     "start": "2017-03-28", "end": "2026-01-01"},
]
MAX_CLOUD = 40              # max cloud % per scene
BUFFER_M = 500             # point/line AOIs are buffered to this radius (meters)
# ─────────────────────────────────────────────────────────────

# Default folder to look in for input files.
INPUT_DIR = Path("data/input")


def read_vector(path: str, layer: str | None = None) -> gpd.GeoDataFrame:
    """Read a vector AOI file, return a GeoDataFrame in EPSG:4326.

    Supports .shp, .gpkg (GeoPackage), .geojson/.json, and .zip of a shapefile.
    If the given path isn't found as-is, it is also looked up under data/input/.
    """
    p = Path(path)
    if not p.exists():
        candidate = INPUT_DIR / path
        if candidate.exists():
            p = candidate
        else:
            raise FileNotFoundError(f"Not found: {path} (also checked {candidate})")

    suffix = p.suffix.lower()

    if suffix == ".zip":
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(p) as zf:
                zf.extractall(tmp)
            shp = list(Path(tmp).rglob("*.shp"))
            if not shp:
                raise ValueError("No .shp inside the zip.")
            gdf = gpd.read_file(shp[0])
    elif suffix == ".gpkg":
        # GeoPackage can hold several layers; set LAYER to pick one.
        if layer:
            gdf = gpd.read_file(p, layer=layer)
        else:
            import fiona
            layers = fiona.listlayers(p)
            if len(layers) > 1:
                raise ValueError(
                    f"GeoPackage has multiple layers {layers}; set LAYER = <name>."
                )
            gdf = gpd.read_file(p, layer=layers[0])
    else:
        # .shp, .geojson, .json, etc.
        gdf = gpd.read_file(p)

    if gdf.crs is None:
        raise ValueError("Input has no CRS (.prj missing for shapefile).")
    return gdf.to_crs(epsg=4326)


def to_area_gdf(gdf, buffer_m):
    """Return a polygon GeoDataFrame in EPSG:4326.
    - Strips any Z coordinate (Earth Engine rejects 3D).
    - Buffers point/line geometries into polygons (radius = buffer_m meters).
    Buffering is done in a metric UTM CRS so the radius is in real meters."""
    from shapely import force_2d

    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.apply(force_2d)   # drop Z

    types = set(gdf.geom_type)
    if types & {"Point", "MultiPoint", "LineString", "MultiLineString"}:
        metric = gdf.estimate_utm_crs()              # local UTM zone (meters)
        buffered = gdf.to_crs(metric).buffer(buffer_m)
        gdf = gpd.GeoDataFrame(geometry=buffered, crs=metric).to_crs(epsg=4326)
    return gdf


def ingest_one(job):
    print(f"\n=== {job['name']} ({job['input']}) ===")
    print("Reading input…")
    gdf = read_vector(job["input"], layer=job.get("layer"))
    print(f"  {len(gdf)} feature(s), types: {sorted(set(gdf.geom_type))}")

    gdf = to_area_gdf(gdf, BUFFER_M)
    aoi = gdf_to_ee_geometry(gdf)

    print(f"Computing monthly indices {job['start']} -> {job['end']}…")
    series = vi_monthly_series(aoi, job["start"], job["end"], max_cloud=MAX_CLOUD)
    if not series:
        print("  No cloud-free NDVI found. Skipped.")
        return
    print(f"  {len(series)} monthly points")

    aoi_id = save_aoi(job["name"], gdf)
    save_series(aoi_id, series)
    print(f"  Stored as AOI #{aoi_id} ({len(series)} rows).")


def main():
    print("Initializing Earth Engine…")
    init_ee()
    for job in JOBS:
        try:
            ingest_one(job)
        except Exception as e:
            print(f"  ERROR on {job.get('name')}: {e}")
    print("\nAll jobs done.")


if __name__ == "__main__":
    main()
