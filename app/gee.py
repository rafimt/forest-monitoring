import ee

from app.config import settings

_initialized = False

# The vegetation indices we compute, in band-name form.
INDEX_BANDS = ["NDVI", "EVI", "SAVI", "NDRE", "GNDVI"]


def init_ee():
    """Initialize Earth Engine once. Safe to call on every Streamlit rerun."""
    global _initialized
    if not _initialized:
        ee.Initialize(project=settings.gee_project)
        _initialized = True


def gdf_to_ee_geometry(gdf) -> ee.Geometry:
    """Convert a geopandas GeoDataFrame (EPSG:4326) to an ee.Geometry."""
    merged = gdf.unary_union
    return ee.Geometry(merged.__geo_interface__)


def mask_s2_clouds(image):
    """Mask cloud/shadow/cirrus pixels using the SCL band."""
    scl = image.select("SCL")
    mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
    return image.updateMask(mask)


def add_indices(image):
    """Add NDVI, EVI, SAVI, NDRE, GNDVI bands.

    Sentinel-2 SR reflectance is scaled by 10000. Ratio indices (NDVI, NDRE,
    GNDVI) are scale-invariant, but EVI and SAVI have additive constants, so
    we compute those from reflectance scaled back to 0-1.
    Bands: B2 blue, B3 green, B4 red, B5 red-edge, B8 NIR.
    """
    r = image.divide(10000)  # reflectance 0-1 (used for EVI/SAVI)
    nir, red, green = r.select("B8"), r.select("B4"), r.select("B3")
    blue, rededge = r.select("B2"), r.select("B5")

    ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")
    gndvi = nir.subtract(green).divide(nir.add(green)).rename("GNDVI")
    ndre = nir.subtract(rededge).divide(nir.add(rededge)).rename("NDRE")
    evi = image.expression(
        "2.5 * ((N - R) / (N + 6*R - 7.5*B + 1))",
        {"N": nir, "R": red, "B": blue},
    ).rename("EVI")
    savi = image.expression(
        "1.5 * ((N - R) / (N + R + 0.5))",
        {"N": nir, "R": red},
    ).rename("SAVI")

    return image.addBands([ndvi, evi, savi, ndre, gndvi])


def build_index_collection(aoi, start, end, max_cloud=40):
    """Cloud-masked Sentinel-2 collection over AOI + range, all indices added."""
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
        .map(mask_s2_clouds)
        .map(add_indices)
    )


def vi_monthly_series(aoi, start, end, max_cloud=40, scale=10):
    """[{date:'YYYY-MM', n_images, ndvi, evi, savi, ndre, gndvi}, ...] — one
    point per month. Monthly = median composite of the month, then spatial
    median over the AOI, for every index."""
    start_date = ee.Date(start)
    end_date = ee.Date(end)

    base = build_index_collection(aoi, start, end, max_cloud).select(INDEX_BANDS)

    n_months = end_date.difference(start_date, "month").ceil()
    months = ee.List.sequence(0, n_months.subtract(1))

    def one_month(m):
        m = ee.Number(m)
        s = start_date.advance(m, "month")
        e = s.advance(1, "month")
        month_imgs = base.filterDate(s, e)
        count = month_imgs.size()

        # Empty months have no bands and would crash reduceRegion; fall back
        # to a zero 5-band image. Dropped later by n_images == 0.
        composite = ee.Image(
            ee.Algorithms.If(
                count.gt(0),
                month_imgs.median(),
                ee.Image.constant([0, 0, 0, 0, 0]).rename(INDEX_BANDS),
            )
        )

        stats = composite.reduceRegion(
            reducer=ee.Reducer.median(),
            geometry=aoi,
            scale=scale,
            maxPixels=1e9,
        )

        props = {"date": s.format("YYYY-MM"), "n_images": count}
        for b in INDEX_BANDS:
            props[b] = stats.get(b)
        return ee.Feature(None, props)

    fc = ee.FeatureCollection(months.map(one_month))
    features = fc.getInfo()["features"]

    rows = []
    for f in features:
        p = f["properties"]
        if p.get("n_images", 0) > 0 and p.get("NDVI") is not None:
            rows.append({
                "date": p["date"],
                "n_images": p["n_images"],
                "ndvi": p.get("NDVI"),
                "evi": p.get("EVI"),
                "savi": p.get("SAVI"),
                "ndre": p.get("NDRE"),
                "gndvi": p.get("GNDVI"),
            })

    rows.sort(key=lambda r: r["date"])
    return rows
