"""Tests for the raster renderer: every garden visible, labels never stacked."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageFont  # noqa: E402

from src import config, raster  # noqa: E402


def _boxes_overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _garden(name, xy, kind="food", bbox=None):
    bbox = bbox or (xy[0], xy[1], xy[0], xy[1])
    return {"name": name, "kind": kind, "polys": [[[]]] if bbox[0] != bbox[2] else [],
            "xy": xy, "bbox": bbox, "radius": 6, "dot": True}


def test_neighbouring_labels_do_not_overlap():
    # Parkwood and West Village Co-op Youth Farm share an address: their dots
    # sit a few pixels apart, and the second label must go the other way.
    font = ImageFont.truetype(raster.FONT_PATH, raster.FONT_SIZE)
    gardens = [_garden("Parkwood Community Garden", (1000, 1000)),
               _garden("West Village Co-op Youth Farm", (1004, 1003))]
    labels = raster._place_labels(gardens, font, 16)
    assert len(labels) == 2
    assert not _boxes_overlap(labels[0]["box"], labels[1]["box"])


def test_pollinator_names_wait_for_the_top_zoom_and_print_once():
    font = ImageFont.truetype(raster.FONT_PATH, raster.FONT_SIZE)
    gardens = [_garden("John Galt Pollinator Gardens", (1000, 1000), "pollinator"),
               _garden("John Galt Pollinator Gardens", (1000, 1100), "pollinator")]
    assert raster._place_labels(gardens, font, 16) == []
    assert len(raster._place_labels(gardens, font, 17)) == 1


def test_every_garden_is_drawn_at_the_lowest_zoom(tmp_path, monkeypatch):
    # A 230 m2 bed is under a pixel at z13; without its dot it would vanish,
    # and so would every garden with no footprint at all.
    monkeypatch.setattr(config, "RASTER_TILE_DIR", str(tmp_path / "raster"))
    monkeypatch.setattr(config, "RASTER_ZOOMS", [13])
    x, y = -80.25, 43.54
    ring = [[x, y], [x + 0.0002, y], [x + 0.0002, y + 0.0001], [x, y + 0.0001], [x, y]]
    feats = [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
         "properties": {"name": "Bed", "kind": "food"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-80.2, 43.5]},
         "properties": {"name": "Patch", "kind": "pollinator"}},
    ]
    slim = tmp_path / "slim.geojsonl"
    slim.write_text("".join(json.dumps(f) + "\n" for f in feats), encoding="utf-8")
    counts = raster.build_raster(str(slim))
    assert counts[13] >= 2
