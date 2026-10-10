"""Configuration constants for the Guelph community gardens tile layer build.

Single source of truth. No logic here.

Sibling of guelph-parks-layer: the same pipeline (download -> slim -> compare
-> vector + raster -> site -> publish), pointed at the City's two Community
Gardens layers instead of Park Boundary. The structural differences are that
there are two sources -- a point roster and a polygon footprint layer -- and
that slim joins them, so every garden on the roster carries its footprint
where the City has drawn one.
"""

import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
SITE_DIR = os.path.join(BUILD_DIR, "site")
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")

MBTILES_PATH = os.path.join(BUILD_DIR, "gardens.mbtiles")
# One line per in-use roster garden: its footprint polygon where the City has
# one, else its roster point. The tile builders and the gap tool all read it.
SLIM_PATH = os.path.join(DATA_DIR, "gardens-slim.geojsonl")
COUNT_PATH = os.path.join(DATA_DIR, "gardens.count")
LAST_DOWNLOAD_PATH = os.path.join(DATA_DIR, ".last-download.json")

VECTOR_TILE_DIR = os.path.join(SITE_DIR, "tiles", "vector")
RASTER_TILE_DIR = os.path.join(SITE_DIR, "tiles", "raster")

# Data sources: the City of Guelph's two Community Gardens layers.
#
# The POINTS (OpenData1 layer 18) are the live roster: 71 rows, two new on
# 2026-06-11 and edits through 2026-07. The POLYGONS (layer 28) are the
# footprints, frozen since 2025-06: they lack the three newest gardens and
# carry a renamed one under its old name. So the roster decides which gardens
# exist and what they are called; a polygon only supplies a garden's shape.
#
# The service stores geometry in EPSG:26917, so outSR=4326 is not optional.
FEATURE_SERVER = (
    "https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData1"
    "/FeatureServer"
)
# key -> (layer id, dated-file prefix)
SOURCES = {
    "points": (18, "gardens-points"),
    "polygons": (28, "gardens-polygons"),
}


def dataset_url(layer):
    return (f"{FEATURE_SERVER}/{layer}/query?where=1%3D1&outFields=*"
            f"&outSR=4326&f=geojson")


# The service's own pages. Guelph's open-data catalogue has no stable item page
# for these layers, so the FeatureServer URLs are what a reader is pointed at.
POINTS_PAGE = f"{FEATURE_SERVER}/18"
POLYGONS_PAGE = f"{FEATURE_SERVER}/28"
# This layer REDISTRIBUTES City data as published tiles, and the licence
# attaches a required attribution to that. It is carried on every page. See
# the README section "Licence"; it is a condition, not a courtesy.
LICENSE_URL = "https://gismaps.guelph.ca/Images/OpenDataLicenceVersion2.pdf"
LICENSE_NOTICE = (
    "Contains information licensed under the Open Government Licence "
    "– City of Guelph."
)
# Plain-ASCII attribution embedded in tile metadata (it is passed through the
# WSL shell, where the en dash in LICENSE_NOTICE is not safe).
ATTRIBUTION = (
    "Contains information licensed under the Open Government Licence "
    "- City of Guelph"
)

# GitHub Pages target. PAGES_URL carries NO trailing slash: every tile URL on
# the site is built as f"{PAGES_URL}/tiles/...".
GITHUB_REPO = "guelph-maps/guelph-gardens-layer"
PAGES_URL = "https://guelph-maps.github.io/guelph-gardens-layer"

# WSL distro that has tippecanoe installed (see wsl-setup.md).
WSL_DISTRO = "Ubuntu"

# Vector tiles. iD requests tiles at (map zoom - 1) and does NOT overzoom, so
# tiles must be generated natively through the zooms used for mapping. A
# garden is a few beds in a park; nobody looks for one from city overview.
VECTOR_MINZOOM = 12
VECTOR_MAXZOOM = 19
VECTOR_LAYER_NAME = "gardens"

# Raster tiles. Editors overzoom z17 -> z18+.
RASTER_ZOOMS = [13, 14, 15, 16, 17]

# Status values to KEEP, on both layers. The roster has one FUTURE row (a food
# forest with no name or address), the footprints two; a planned garden is not
# something to map.
INCLUDE_STATUS = frozenset({"IN-USE"})

# Source property keys (the same on both layers).
NAME_KEY = "Name"               # ALL CAPS, e.g. "BRANT AVENUE COMMUNITY GARDEN"
TYPE_KEY = "GardenType"         # "TRADITIONAL COMMUNITY GARDEN", "POLLINATOR HABITAT", ...
ADDRESS_KEY = "Address"
STATUS_KEY = "Status"
GARDEN_ID_KEY = "CommGardenID"  # the join key between roster and footprints
OBJECT_ID_KEY = "OBJECTID"

# The roster's one non-food type. A pollinator patch is drawn on the layer and
# listed on the gap page, but not counted as a gap: OSM has no settled tag
# for it.
POLLINATOR_TYPE = "POLLINATOR HABITAT"

# --- OSM comparison (gap-review page) ---
# Garden-like features are pulled from OSM via Overpass and matched against the
# roster by distance, one-to-one; the gaps feed build/site/gaps/.
#
# overpass.kumi.systems and overpass.private.coffee are deliberately absent:
# both have been caught serving months-stale data with HTTP 200, which looks
# exactly like success. That leaves overpass-api.de alone; OSM_MAX_AGE_DAYS
# refuses a stale reply from any mirror.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
)
OVERPASS_TIMEOUT = 300
OVERPASS_ROUNDS = 3
OVERPASS_ROUND_WAIT = 60
# Floor on a reply's element count. The first live reply (2026-10-09, OSM base
# 23:52Z) carried 74 elements: 67 leisure=garden ways, 4 community-garden
# nodes, 2 allotments, 1 flowerbed. Half that is a wrong-region or truncated
# answer, not a week's mapping -- and taken at face value it would report every
# City garden as missing from OSM.
OSM_MIN_ELEMENTS = 35
# Oldest OSM data a reply may carry (its osm3s.timestamp_osm_base) and still be
# compared against. A reply that does not say how old it is is refused too.
OSM_MAX_AGE_DAYS = 3
# Overpass rejects the default requests User-Agent (HTTP 406); identify the tool.
USER_AGENT = "guelph-gardens-layer/0.1 (toronto@comentality.com)"
# Guelph bounding box (S, W, N, E), as the sibling layers use it.
GUELPH_BBOX = (43.46, -80.34, 43.60, -80.14)
# Guelph city centre; where the preview and gap maps open.
GUELPH_CENTER = (43.5448, -80.2482)
# OSM tags that count as "a garden is mapped here". Orchards because five of
# the roster's food gardens are food forests; allotments because that is the
# other common tag for a plot garden. Nodes, ways and relations all count: four
# of Guelph's community gardens are mapped as a node.
OSM_GARDEN_TAGS = {
    "leisure": ("garden",),
    "landuse": ("allotments", "orchard"),
}
# A garden is matched when an OSM garden lies within this many metres of its
# footprint's edge (or of its roster point, when it has no footprint). The
# recalibration found the same 22 unmatched footprints at 10, 25, 50 and 100 m,
# so the radius is not what the count hangs on.
MATCH_RADIUS_M = 25
OSM_CACHE_PATH = os.path.join(DATA_DIR, "osm-gardens.json")
OSM_FETCH_PATH = os.path.join(DATA_DIR, ".osm-fetch.json")
GAPS_GEOJSON_PATH = os.path.join(DATA_DIR, "gaps.geojson")
GAPS_COUNT_PATH = os.path.join(DATA_DIR, "gaps.count.json")

# --- Gap history (trend page) ---
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
HISTORY_URL = f"{PAGES_URL}/gaps/history.jsonl"
# Backfill. overpass-api.de keeps OSM's full history and answers the same
# query for a past instant ([date:...]). Weekly points, one attempt per date,
# and a pause between dates -- attic queries are heavier than live ones.
ATTIC_URL = "https://overpass-api.de/api/interpreter"
BACKFILL_SINCE = "2026-06-01"   # a Monday; the parks sibling's start, so the charts line up
BACKFILL_STEP_DAYS = 7
BACKFILL_PAUSE = 30
