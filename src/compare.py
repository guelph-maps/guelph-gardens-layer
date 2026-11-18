"""Compare the City's community gardens roster against gardens in OSM.

Pulls garden-like features from OpenStreetMap (Overpass) within Guelph, then
pairs each in-use roster garden with at most one OSM garden lying within
config.MATCH_RADIUS_M of it -- of its footprint's edge, or of its roster point
when the City has drawn no footprint. Pairing is ONE-TO-ONE: Parkwood
Community Garden and West Village Co-op Youth Farm sit side by side at 170
Stephanie Drive and both lie within reach of the same OSM way, and one OSM
garden cannot stand for two of the City's. Pairs are taken best first: a name
that agrees, then an OSM garden tagged as a community garden, then distance.

Each food-growing garden gets one status, written to data/gaps.geojson:

  * "missing"       -- no OSM garden near its footprint (add it to OSM);
  * "point_only"    -- no OSM garden near its roster point, and the City has
                       drawn no footprint either: find it on the ground;
  * "untyped"       -- matched to a leisure=garden that is not tagged
                       garden:type=community (nor allotments or orchard);
                       checked before the name, since it is the weakest match;
  * "unnamed"       -- matched, but the OSM garden has no name;
  * "name_mismatch" -- matched, but the OSM name is a different name.

A matched garden with none of those problems is not a gap and is not written.
Pollinator patches are paired afterwards, against the OSM gardens left over,
and written with status "pollinator" whatever the outcome: OSM has no settled
tag for a pollinator patch, so they are shown and never counted.

Geometry is pure Python in a local metric projection -- at ~70 gardens against
~75 OSM features nothing heavier earns its install.
"""

import json
import math
import re
import time

import requests
from layerkit.geom import point_in_ring as _point_in_ring
from layerkit.geom import relation_outer_loops as _relation_outer_loops
from layerkit import overpass
# Raised by overpass.load_osm; callers and tests name it as compare's.
from layerkit.overpass import OsmUnavailable  # noqa: F401

from src import config, history

GAP_STATUSES = ("missing", "point_only", "unnamed", "name_mismatch", "untyped")

# Local equirectangular projection, metres. Guelph spans 0.14 degrees of
# latitude; the scale error across it is far below a garden bed.
_LAT0 = 43.53
_KX = 111320 * math.cos(math.radians(_LAT0))
_KY = 110574


def compare():
    """Build data/gaps.geojson + summary from City vs OSM. Returns the summary."""
    data, osm_date, from_cache = _load_osm()
    osm = _osm_gardens(data)
    print(f"OSM gardens:  {len(osm):,}")
    city = list(_city_features())
    food = sum(1 for c in city if c["kind"] == "food")
    print(f"City gardens: {len(city):,} ({food:,} food, "
          f"{len(city) - food:,} pollinator)")

    gaps, counts = _match(city, osm)
    _write_gaps(gaps)

    summary = {"osm": len(osm), "city": food, "osm_date": osm_date,
               "osm_stale": from_cache, **counts}
    with open(config.GAPS_COUNT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(
        f"Gaps: {counts['missing']:,} missing, {counts['point_only']:,} "
        f"point-only, {counts['unnamed']:,} unnamed, "
        f"{counts['name_mismatch']:,} name mismatch, {counts['untyped']:,} "
        f"untyped; {counts['matched']:,} matched cleanly; "
        f"{counts['pollinator']:,} pollinator ({counts['pollinator_osm']:,} "
        f"with an OSM garden near)"
    )
    if from_cache:
        print(f"NOTE: compared against cached OSM data from {osm_date}, "
              f"not a live Overpass fetch.")
    history.record(summary)
    return summary


# --- OSM source -------------------------------------------------------------

def _overpass_query(at=None):
    """The Overpass QL for garden-like features; ``at`` (ISO instant) asks for
    OSM as it stood then -- an attic query, used by the history backfill."""
    s, w, n, e = config.GUELPH_BBOX
    bbox = f"{s},{w},{n},{e}"
    parts = []
    for key, values in config.OSM_GARDEN_TAGS.items():
        rx = "|".join(values)
        parts.append(f'  nwr["{key}"~"^({rx})$"]({bbox});')
    # "out geom" (body verbosity) so RELATIONS carry their members + geometry.
    settings = "[out:json][timeout:180]"
    if at:
        settings += f'[date:"{at}"]'
    return settings + ";\n(\n" + "\n".join(parts) + "\n);\nout geom;"


def _load_osm():
    """Return (data, osm_date, from_cache) for OSM gardens.

    The fetch -- every mirror, the list retried, then the cache -- is
    layerkit.overpass.load_osm; the reasons for each rule are written there.
    """
    return overpass.load_osm(
        _overpass_query(), what="gardens",
        urls=config.OVERPASS_URLS, rounds=config.OVERPASS_ROUNDS,
        round_wait=config.OVERPASS_ROUND_WAIT,
        cache_path=config.OSM_CACHE_PATH, fetch_path=config.OSM_FETCH_PATH,
        try_one=_try_overpass, undated=None)


def _try_overpass(url, query):
    """One attempt at one mirror; None if it failed or answered implausibly."""
    return overpass.try_overpass(
        url, query, user_agent=config.USER_AGENT,
        timeout=config.OVERPASS_TIMEOUT,
        min_elements=config.OSM_MIN_ELEMENTS,
        max_age_days=config.OSM_MAX_AGE_DAYS)


def _load_cache():
    """(data, osm_date) for the cached Overpass reply, or None."""
    return overpass.load_cache(config.OSM_CACHE_PATH, config.OSM_FETCH_PATH)


def _osm_base(data):
    """How current the OSM half of the diff is: the reply's own
    osm3s.timestamp_osm_base, trimmed to the minute for display."""
    return overpass.osm_base(data, undated=None)


def _osm_base_time(data):
    """The same timestamp as an aware datetime, or None if absent or garbled."""
    return overpass.osm_base_time(data)


def _cache_date():
    """How current the cached reply is: the sidecar, else the file's mtime."""
    return overpass.cache_date(config.OSM_CACHE_PATH, config.OSM_FETCH_PATH)


def _save_fetch(fetched, url, osm_base, data):
    overpass.save_fetch(config.OSM_FETCH_PATH, fetched, url, osm_base, data)


def _osm_gardens(data):
    """OSM garden features as matchable shapes (open ways are dropped)."""
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if el.get("type") == "node":
            if "lon" not in el:
                continue
            parts = [[_proj(el["lon"], el["lat"])]]
        elif el.get("type") == "way":
            ring = _ring(el.get("geometry"))
            if not ring:
                continue  # an open way (a hedge line, a garden path) is no area
            parts = [ring]
        elif el.get("type") == "relation":
            parts = [r for r in (_ring(loop) for loop in _relation_outer_loops(el)) if r]
            if not parts:
                continue
        else:
            continue
        out.append({
            "otype": el["type"], "oid": el["id"], "tags": tags,
            "name": tags.get("name"), "typed": _typed(tags),
            "parts": parts, "bbox": _bbox(parts),
        })
    return out


def _typed(tags):
    """Tagged as the kind of garden the roster lists, not a generic garden."""
    return (tags.get("garden:type") == "community"
            or tags.get("landuse") in ("allotments", "orchard"))


def _tag_label(tags):
    """The one tag a reviewer needs to see: what the OSM feature says it is."""
    if tags.get("leisure") == "garden":
        gt = tags.get("garden:type")
        return f"leisure=garden + garden:type={gt}" if gt else "leisure=garden"
    return f"landuse={tags.get('landuse')}"


def _ring(geom):
    """A closed way's geometry as a projected ring, or None if it is open."""
    pts = [_proj(p["lon"], p["lat"]) for p in geom or () if "lon" in p]
    if len(pts) < 4 or pts[0] != pts[-1]:
        return None
    return pts


# --- City source ------------------------------------------------------------

def _city_features():
    with open(config.SLIM_PATH, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            geom = feat["geometry"]
            if geom["type"] == "Point":
                parts = [[_proj(*geom["coordinates"][:2])]]
            else:
                polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                         else [geom["coordinates"]])
                parts = [[_proj(x, y) for x, y in poly[0]] for poly in polys]
            yield {**feat["properties"], "geom": geom, "parts": parts,
                   "bbox": _bbox(parts)}


# --- Matching ---------------------------------------------------------------

def _match(city, osm):
    """Pair gardens to OSM one-to-one and classify. Returns (gaps, counts)."""
    counts = {s: 0 for s in GAP_STATUSES}
    counts.update(matched=0, pollinator=0, pollinator_osm=0)
    taken = set()
    food = [c for c in city if c["kind"] == "food"]
    pollinators = [c for c in city if c["kind"] != "food"]

    gaps = []
    pairs = _pair(food, osm, taken)
    for i, c in enumerate(food):
        m = pairs.get(i)
        status = _status(c, m)
        if status is None:
            counts["matched"] += 1
            continue
        counts[status] += 1
        gaps.append(_gap_feature(c, status, m))

    pairs = _pair(pollinators, osm, taken)
    for i, c in enumerate(pollinators):
        m = pairs.get(i)
        counts["pollinator"] += 1
        counts["pollinator_osm"] += m is not None
        gaps.append(_gap_feature(c, "pollinator", m))
    return gaps, counts


def _pair(gardens, osm, taken):
    """{garden index: (osm feature, distance)}, one-to-one, best pairs first.

    Every garden/OSM pair within the radius is ranked -- names agreeing first,
    then a community-typed OSM garden, then the nearer -- and taken greedily
    while both sides are free. ``taken`` (OSM ids) is updated, so a later call
    only sees what is left.
    """
    r = config.MATCH_RADIUS_M
    cands = []
    for i, c in enumerate(gardens):
        for o in osm:
            if (o["otype"], o["oid"]) in taken \
                    or not _bbox_near(c["bbox"], o["bbox"], r):
                continue
            d = _distance(c["parts"], o["parts"])
            if d <= r:
                rank = (not names_agree(c.get("city_name"), o["name"]),
                        not o["typed"], d)
                cands.append((rank, i, o, d))
    cands.sort(key=lambda t: (t[0], t[1]))
    pairs = {}
    for _rank, i, o, d in cands:
        key = (o["otype"], o["oid"])
        if i in pairs or key in taken:
            continue
        pairs[i] = (o, d)
        taken.add(key)
    return pairs


def _status(c, m):
    if m is None:
        return "missing" if c["footprint"] == "polygon" else "point_only"
    o = m[0]
    # Untyped first: a bare leisure=garden is the weakest evidence that the
    # OSM feature IS the City's garden, so "check it, then tag it" comes before
    # any advice about its name.
    if not o["typed"]:
        return "untyped"
    if not o["name"]:
        return "unnamed"
    if not names_agree(c.get("city_name"), o["name"]):
        return "name_mismatch"
    return None


# Words the City and OSM disagree on including -- "BRANT AVENUE COMMUNITY
# GARDEN" is "Brant Avenue Community Garden" or "Brant Avenue Garden" alike.
_FILLER = re.compile(r"\b(?:COMMUNITY|COMMUNAL|GARDENS?|VEGETABLE|THE|PROJECT)\b")


def _norm(name):
    s = re.sub(r"[^A-Z0-9 ]", "", (name or "").upper())
    return " ".join(_FILLER.sub("", s).split())


def names_agree(city_name, osm_name):
    """The recalibration's rule: equal after dropping filler words, or one
    contained in the other ("STEPHANIE DRIVE PARK COMMUNITY ORCHARD" against
    "Stephanie Drive Park Orchard")."""
    a, b = _norm(city_name), _norm(osm_name)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _gap_feature(c, status, m):
    props = {
        "name": c.get("name"),
        "city_name": c.get("city_name"),
        "address": c.get("address"),
        "type": c.get("type"),
        "footprint": c.get("footprint"),
        "status": status,
        "garden_id": c.get("garden_id"),
    }
    if m:
        o, d = m
        props["osm_name"] = o["name"]
        props["osm_tag"] = _tag_label(o["tags"])
        props["osm_m"] = round(d)
        props["osm_url"] = f"https://www.openstreetmap.org/{o['otype']}/{o['oid']}"
    return {
        "type": "Feature",
        "properties": {k: v for k, v in props.items() if v is not None},
        "geometry": _round_geom(c["geom"]),
    }


def _write_gaps(gaps):
    with open(config.GAPS_GEOJSON_PATH, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": gaps}, f)


# --- Geometry (local metres) ------------------------------------------------
#
# A shape is a list of parts; a part is either a closed ring of (x, y) points
# (first == last) or a single point.

def _proj(lon, lat):
    return (lon * _KX, lat * _KY)


def _bbox(parts):
    xs = [p[0] for part in parts for p in part]
    ys = [p[1] for part in parts for p in part]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_near(a, b, r):
    return not (a[2] + r < b[0] or b[2] + r < a[0]
                or a[3] + r < b[1] or b[3] + r < a[1])


def _segments(part):
    return list(zip(part, part[1:])) if len(part) > 1 else []


def _distance(a_parts, b_parts):
    """Shortest distance between two shapes; 0 if they touch or overlap."""
    best = math.inf
    for a in a_parts:
        for b in b_parts:
            best = min(best, _part_distance(a, b))
            if best == 0:
                return 0.0
    return best


def _part_distance(a, b):
    # One inside the other.
    if len(a) > 1 and _point_in_ring(b[0], a):
        return 0.0
    if len(b) > 1 and _point_in_ring(a[0], b):
        return 0.0
    sa, sb = _segments(a), _segments(b)
    for p, q in sa:
        for r, s in sb:
            if _segments_cross(p, q, r, s):
                return 0.0
    best = math.inf
    if not sa and not sb:
        return math.dist(a[0], b[0])
    for v in a:
        for r, s in sb:
            best = min(best, _point_segment(v, r, s))
    for v in b:
        for p, q in sa:
            best = min(best, _point_segment(v, p, q))
    return best


def _point_segment(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    len2 = dx * dx + dy * dy
    t = 0.0 if len2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / len2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_cross(p, q, r, s):
    d1, d2 = _cross(r, s, p), _cross(r, s, q)
    d3, d4 = _cross(p, q, r), _cross(p, q, s)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) \
        and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


def _round_geom(geom):
    return {"type": geom["type"], "coordinates": _round(geom["coordinates"])}


def _round(c):
    if isinstance(c, (int, float)):
        return round(c, 6)  # ~10 cm: a garden bed is a few metres across
    return [_round(x) for x in c]
