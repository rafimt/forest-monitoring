import folium

# Selectable basemaps: label -> (tiles url/name, attribution)
BASEMAPS = {
    "OpenStreetMap": ("OpenStreetMap", None),
    "Carto Light": ("CartoDB positron", None),
    "Carto Dark": ("CartoDB dark_matter", None),
    "Esri Satellite": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "Tiles © Esri",
    ),
    "Esri Topo": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "Tiles © Esri",
    ),
}


def make_map(center=(23.7, 90.4), zoom=6, basemap="OpenStreetMap"):
    """Create a Folium map with the chosen basemap (see BASEMAPS keys)."""
    tiles, attr = BASEMAPS.get(basemap, BASEMAPS["OpenStreetMap"])
    if attr:
        m = folium.Map(location=list(center), zoom_start=zoom, tiles=None)
        folium.TileLayer(tiles=tiles, attr=attr, name=basemap).add_to(m)
    else:
        m = folium.Map(location=list(center), zoom_start=zoom, tiles=tiles)
    return m


def add_aoi(m, gdf):
    """Add the uploaded AOI outline to the map and zoom to it."""
    folium.GeoJson(
        gdf.__geo_interface__,
        name="AOI",
        style_function=lambda _: {
            "color": "#c1272d",
            "weight": 2,
            "fillOpacity": 0.1,
        },
    ).add_to(m)

    # Zoom to the AOI bounds: folium wants [[south, west], [north, east]].
    minx, miny, maxx, maxy = gdf.total_bounds
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    return m


def add_ndvi_layer(m, ndvi_image, aoi):
    """Add an Earth Engine NDVI image to the Folium map as a tile layer."""
    vis = {
        "min": 0.0,
        "max": 0.8,
        "palette": ["#d73027", "#fee08b", "#1a9850"],  # red -> yellow -> green
    }
    # getMapId turns the EE image into an XYZ tile URL Folium can display.
    mapid = ndvi_image.clip(aoi).getMapId(vis)
    folium.TileLayer(
        tiles=mapid["tile_fetcher"].url_format,
        attr="Google Earth Engine",
        name="NDVI",
        overlay=True,
        control=True,
    ).add_to(m)
    folium.LayerControl().add_to(m)
    return m

