# Pixel-wise NDVI change GIF for one plot, to visualize encroachment.
#
# For each year it computes an annual median NDVI, then the DIFFERENCE from a
# baseline year (default: the first year). Red = NDVI loss (possible
# encroachment / clearing), green = gain. Frames are stitched into a GIF.
#
# Run:  python -m app.ndvi_change_gif

import io
import json
import os

import ee
import imageio.v2 as imageio
import requests
from PIL import Image, ImageDraw
from sqlalchemy import text

from app.gee import init_ee, build_index_collection
from app.db import engine

# ── CONFIG ───────────────────────────────────────────────────
BEAT = "Link Road Beat cum Check Station"
PLOT_INDEX = 2               # "Plot_2" within the beat (1-based, by plot_name)
START, END = 2017, 2026      # inclusive years
MODE = "baseline"            # "baseline" (vs first year) or "consecutive"
MAX_CLOUD = 40
DIM = 420                    # output frame size (px)
OUT = "data/gifs/plot_change.gif"

VIS = {
    "min": -0.3, "max": 0.3,
    "palette": ["#b2182b", "#ef8a62", "#f7f7f7", "#91cf60", "#1a9850"],
}


def get_plot_geom():
    with engine.begin() as c:
        rows = c.execute(text("""
            SELECT plot_name, ST_AsGeoJSON(geom) AS g
            FROM plot WHERE beat_name = :b ORDER BY plot_name;
        """), {"b": BEAT}).all()
    if not rows:
        raise SystemExit(f"No plots in beat '{BEAT}'.")
    if PLOT_INDEX > len(rows):
        raise SystemExit(f"Beat has {len(rows)} plot(s); PLOT_INDEX={PLOT_INDEX}.")
    r = rows[PLOT_INDEX - 1]
    return r.plot_name, ee.Geometry(json.loads(r.g))


def annual_ndvi(aoi, year):
    """Annual median NDVI image (None if the year has no cloud-free data)."""
    coll = build_index_collection(aoi, f"{year}-01-01", f"{year + 1}-01-01",
                                  MAX_CLOUD).select("NDVI")
    if coll.size().getInfo() == 0:
        return None
    return coll.median()


def frame_png(diff_img, aoi, label):
    """Render a difference image to a labeled PIL frame."""
    url = diff_img.clip(aoi).getThumbURL(
        {**VIS, "region": aoi, "dimensions": DIM, "format": "png"})
    img = Image.open(io.BytesIO(requests.get(url, timeout=60).content)).convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, 20], fill=(0, 0, 0))
    d.text((6, 4), label, fill=(255, 255, 255))
    return img


def main():
    init_ee()
    name, aoi = get_plot_geom()
    print(f"Plot: {name}")

    years = list(range(START, END + 1))
    ndvi = {}
    for y in years:
        img = annual_ndvi(aoi, y)
        if img is not None:
            ndvi[y] = img
    have = sorted(ndvi)
    print(f"Years with data: {have}")
    if len(have) < 2:
        raise SystemExit("Need at least 2 years of data.")

    frames = []
    if MODE == "baseline":
        base_y = have[0]
        for y in have[1:]:
            diff = ndvi[y].subtract(ndvi[base_y])
            frames.append(frame_png(diff, aoi, f"NDVI change {base_y} -> {y}"))
    else:  # consecutive
        for prev, y in zip(have, have[1:]):
            diff = ndvi[y].subtract(ndvi[prev])
            frames.append(frame_png(diff, aoi, f"NDVI change {prev} -> {y}"))
        print(f"  {y}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    imageio.mimsave(OUT, frames, duration=1.0, loop=0)
    print(f"Saved {len(frames)} frames -> {OUT}")


if __name__ == "__main__":
    main()
