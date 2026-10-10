"""Render the gardens into raster (PNG) map tiles using Pillow.

Pure Python -- no native dependencies, runs the same on Windows and Linux.

A garden is small: the median footprint is ~230 m2, a dozen pixels across at
z17 and a speck below it. So every roster garden gets a dot as well as its
shape, or most of the layer would be invisible at the zooms a mapper scans at:

* a footprint polygon (food gardens the City has drawn) is filled translucent
  green with a dark green outline;
* every food garden gets a green dot -- at its footprint's centre, or at its
  roster point when it has no footprint -- drawn only while the footprint is
  too small on screen to read as a shape;
* every pollinator patch gets a smaller amber dot. They are on the roster but
  OSM has no settled tag for them, so they are drawn apart.

Labels are placed once per zoom, globally, against a spatial hash, so a label
straddling a tile seam is drawn identically on both sides: right of the dot
(or of the footprint) else left, wherever it collides with nothing. Food
gardens are labelled from LABEL_MIN_ZOOM; pollinator patches only at
POLLINATOR_LABEL_ZOOM, and only where they fit. At the top zoom every food
garden keeps its name even if it overlaps -- a missing name there is worse
than a crowded one.
"""

import json
import os
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont

from src import config
from src.tilemath import TILE_SIZE, lonlat_to_pixel

FILL_COLOR = (76, 175, 80, 90)          # translucent green
OUTLINE_COLOR = (27, 94, 32, 255)       # dark green
FOOD_COLOR = (46, 125, 50, 255)         # green dot
POLLINATOR_COLOR = (230, 145, 0, 255)   # amber dot
EDGE_COLOR = (255, 255, 255, 255)
HALO_COLOR = (255, 255, 255, 235)
FOOD_LABEL_COLOR = (27, 94, 32, 255)
POLLINATOR_LABEL_COLOR = (150, 85, 0, 255)
OUTLINE_WIDTH = 2
FONT_PATH = os.path.join(config.ASSETS_DIR, "font", "DejaVuSans-Bold.ttf")
FONT_SIZE = 11
STROKE_WIDTH = 1                        # white halo width, in pixels

# Dot radius per zoom, in pixels (white edge included); pollinators one less.
DOT_RADIUS = {13: 3, 14: 3, 15: 4, 16: 5, 17: 6}
# A footprint at least this wide on screen reads as a shape; no dot on it.
SHAPE_MIN_PX = 14

LABEL_MIN_ZOOM = 15
POLLINATOR_LABEL_ZOOM = 17
LABEL_GAP_PX = 3                        # dot/shape edge -> label text
_GRID_CELL = 128                        # spatial-hash cell for collision lookups


def build_raster(slim_path=None):
    """Render PNG tiles for every zoom in config.RASTER_ZOOMS.

    Returns a dict {zoom: tile_count}.
    """
    slim_path = slim_path or config.SLIM_PATH
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    return {z: _render_zoom(slim_path, z, font) for z in config.RASTER_ZOOMS}


def _render_zoom(slim_path, zoom, font):
    gardens = _read_gardens(slim_path, zoom)
    radius = DOT_RADIUS.get(zoom, DOT_RADIUS[max(DOT_RADIUS)])
    for g in gardens:
        g["radius"] = radius if g["kind"] == "food" else radius - 1
        g["dot"] = not g["polys"] or max(
            g["bbox"][2] - g["bbox"][0], g["bbox"][3] - g["bbox"][1]) < SHAPE_MIN_PX
    labels = _place_labels(gardens, font, zoom) if zoom >= LABEL_MIN_ZOOM else []
    print(f"Raster z{zoom}: {len(gardens):,} gardens, {len(labels):,} labels placed")

    shape_tiles = defaultdict(list)
    for g in gardens:
        for key in _tiles_touching(_extent(g)):
            shape_tiles[key].append(g)

    label_tiles = defaultdict(list)
    for lab in labels:
        for key in _tiles_touching(lab["box"]):
            label_tiles[key].append(lab)

    out_dir = os.path.join(config.RASTER_TILE_DIR, str(zoom))
    keys = set(shape_tiles) | set(label_tiles)
    made_dirs = set()
    written = 0
    for tx, ty in keys:
        img = _render_tile(tx, ty, shape_tiles.get((tx, ty), ()),
                           label_tiles.get((tx, ty), ()), font)
        if img.getbbox() is None:
            continue
        tdir = os.path.join(out_dir, str(tx))
        if tdir not in made_dirs:
            os.makedirs(tdir, exist_ok=True)
            made_dirs.add(tdir)
        img.save(os.path.join(tdir, f"{ty}.png"), optimize=True)
        written += 1
    return written


def _read_gardens(slim_path, zoom):
    """[{name, kind, polys: [[ring, ...], ...], xy, bbox}, ...] in zoom pixels."""
    gardens = []
    with open(slim_path, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            geom = feat["geometry"]
            p = feat["properties"]
            if geom["type"] == "Point":
                xy = lonlat_to_pixel(*geom["coordinates"][:2], zoom)
                polys, bbox = [], (xy[0], xy[1], xy[0], xy[1])
            else:
                coords = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                          else [geom["coordinates"]])
                polys = [[[lonlat_to_pixel(lon, lat, zoom) for lon, lat in ring]
                          for ring in poly] for poly in coords]
                xs = [x for poly in polys for x, _ in poly[0]]
                ys = [y for poly in polys for _, y in poly[0]]
                bbox = (min(xs), min(ys), max(xs), max(ys))
                xy = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            gardens.append({"name": p.get("name") or "", "kind": p["kind"],
                            "polys": polys, "xy": xy, "bbox": bbox})
    return gardens


def _extent(g):
    """Pixel box covering everything drawn for a garden (shape and dot)."""
    x0, y0, x1, y1 = g["bbox"]
    if g["dot"]:
        x, y = g["xy"]
        r = g["radius"]
        x0, y0, x1, y1 = min(x0, x - r), min(y0, y - r), max(x1, x + r), max(y1, y + r)
    pad = OUTLINE_WIDTH
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def _place_labels(gardens, font, zoom):
    """Greedy, collision-checked label placement for one zoom.

    Food gardens before pollinator patches, then by name, so the result is the
    same on every run. Every garden's own dot or shape is an obstacle for the
    labels. Returns [{x, y, text, anchor, kind, box}, ...] in global pixels.
    """
    pad = STROKE_WIDTH
    grid = defaultdict(list)

    def cells(x0, y0, x1, y1):
        for cx in range(int(x0 // _GRID_CELL), int(x1 // _GRID_CELL) + 1):
            for cy in range(int(y0 // _GRID_CELL), int(y1 // _GRID_CELL) + 1):
                yield (cx, cy)

    def collides(box):
        x0, y0, x1, y1 = box
        for key in cells(*box):
            for ox0, oy0, ox1, oy1 in grid.get(key, ()):
                if x0 < ox1 and x1 > ox0 and y0 < oy1 and y1 > oy0:
                    return True
        return False

    def add(box):
        for key in cells(*box):
            grid[key].append(box)

    for g in gardens:
        add(_extent(g))

    def candidate(g, side):
        x0, _y0, x1, _y1 = _extent(g)
        y = g["xy"][1]
        w = font.getlength(g["name"])
        top, bottom = y - FONT_SIZE / 2 - pad, y + FONT_SIZE / 2 + pad
        if side == "right":
            lx = x1 + LABEL_GAP_PX
            return lx, y, "lm", (lx - pad, top, lx + w + pad, bottom)
        lx = x0 - LABEL_GAP_PX
        return lx, y, "rm", (lx - w - pad, top, lx + pad, bottom)

    order = sorted((g for g in gardens if g["name"]),
                   key=lambda g: (g["kind"] != "food", g["name"], g["xy"]))
    labels = []
    seen = set()
    for g in order:
        if g["kind"] != "food":
            # The roster lists some pollinator patches once per bed under one
            # name; one label per name is plenty.
            if zoom < POLLINATOR_LABEL_ZOOM or g["name"] in seen:
                continue
        placed = None
        for side in ("right", "left"):
            cand = candidate(g, side)
            if not collides(cand[3]):
                placed = cand
                break
        if placed is None and g["kind"] == "food" and zoom == max(config.RASTER_ZOOMS):
            placed = candidate(g, "right")
        if placed is None:
            continue
        x, y, anchor, box = placed
        add(box)
        seen.add(g["name"])
        labels.append({"x": x, "y": y, "text": g["name"], "anchor": anchor,
                       "kind": g["kind"], "box": box})
    return labels


def _tiles_touching(bbox, pad=STROKE_WIDTH + 1):
    x0, y0, x1, y1 = bbox
    for tx in range(int((x0 - pad) // TILE_SIZE), int((x1 + pad) // TILE_SIZE) + 1):
        for ty in range(int((y0 - pad) // TILE_SIZE), int((y1 + pad) // TILE_SIZE) + 1):
            yield (tx, ty)


def _render_tile(tx, ty, gardens, labels, font):
    img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ox, oy = tx * TILE_SIZE, ty * TILE_SIZE

    def local(ring):
        return [(x - ox, y - oy) for x, y in ring]

    # Fills first (via a mask so holes stay clear), then outlines, then dots.
    for g in gardens:
        for poly in g["polys"]:
            mask = Image.new("L", (TILE_SIZE, TILE_SIZE), 0)
            mdraw = ImageDraw.Draw(mask)
            mdraw.polygon(local(poly[0]), fill=255)
            for hole in poly[1:]:
                mdraw.polygon(local(hole), fill=0)
            img.paste(FILL_COLOR, (0, 0), mask)
    for g in gardens:
        for poly in g["polys"]:
            for ring in poly:
                pts = local(ring)
                draw.line(pts + pts[:1], fill=OUTLINE_COLOR, width=OUTLINE_WIDTH)
    for g in gardens:
        if not g["dot"]:
            continue
        x, y, r = g["xy"][0] - ox, g["xy"][1] - oy, g["radius"]
        color = FOOD_COLOR if g["kind"] == "food" else POLLINATOR_COLOR
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color,
                     outline=EDGE_COLOR, width=1)

    for lab in labels:
        color = FOOD_LABEL_COLOR if lab["kind"] == "food" else POLLINATOR_LABEL_COLOR
        draw.text(
            (lab["x"] - ox, lab["y"] - oy), lab["text"], font=font, fill=color,
            stroke_width=STROKE_WIDTH, stroke_fill=HALO_COLOR, anchor=lab["anchor"],
        )
    return img
