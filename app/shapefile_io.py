import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd


def read_uploaded_shapefile(uploaded_file) -> gpd.GeoDataFrame:
    """Take a Streamlit UploadedFile (.zip), extract it, read the .shp,
    and return a GeoDataFrame in EPSG:4326 (lat/lon)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        zip_path = tmp / "upload.zip"
        zip_path.write_bytes(uploaded_file.getbuffer())

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)

        shp_files = list(tmp.rglob("*.shp"))
        if not shp_files:
            raise ValueError("No .shp file found in the zip.")

        gdf = gpd.read_file(shp_files[0])

    if gdf.crs is None:
        raise ValueError("Shapefile has no CRS (.prj missing).")
    return gdf.to_crs(epsg=4326)
