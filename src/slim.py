"""Join the gardens roster to its footprints, into one slim GeoJSONL.

The roster (points) decides which gardens exist and what they are called; the
footprint layer (polygons) only lends a garden its shape. Each in-use roster
row becomes one line of data/gardens-slim.geojsonl:

  * geometry -- its in-use footprint polygon, joined on CommGardenID, or its
    roster point when the City has drawn no footprint (``footprint`` says
    which);
  * name     -- the City's ALL CAPS name, title-cased for the map
    (``city_name`` keeps the City's text verbatim);
  * kind     -- "food" or "pollinator" (config.POLLINATOR_TYPE).

The join key is CommGardenID and nothing else. Two of the newest roster rows
carry no id, and the footprint layer's two FUTURE polygons carry none either;
joining on a missing key would hand the two new gardens a planned garden's
outline. A name join would be no better: the footprints still carry
"THE SEED YOUTH FARM ..." where the roster now says "f.u.n. Commons Westmount
Garden".
"""

import json
import os
import re
from collections import defaultdict

from src import config

# Sanity bounds for the kept roster (70 in-use rows today).
MIN_EXPECTED = 40
MAX_EXPECTED = 150

# Words title-casing would mangle: the City's acronyms (two collegiate
# institutes and a project code), a hyphenated word and a Mc.
_KEEP = {"CVI": "CVI", "GCVI": "GCVI", "FFH": "FFH", "CO-OP": "Co-op",
         "MCCRAE": "McCrae"}


def slim(points_path, polygons_path):
    """Write data/gardens-slim.geojsonl from the two downloads.

    Returns the slim file path. Raises if the kept count is implausible.
    """
    print(f"Slimming {points_path}\n     with {polygons_path} ...")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    footprints = _footprints(polygons_path)

    with open(points_path, encoding="utf-8") as f:
        roster = json.load(f)["features"]

    kept = []
    skipped = 0
    joined = set()
    for feat in roster:
        p = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        if p.get(config.STATUS_KEY) not in config.INCLUDE_STATUS \
                or geom.get("type") != "Point":
            skipped += 1
            continue
        gid = p.get(config.GARDEN_ID_KEY)
        footprint = footprints.get(gid) if gid is not None else None
        if footprint:
            joined.add(gid)
        kind = "pollinator" if p.get(config.TYPE_KEY) == config.POLLINATOR_TYPE \
            else "food"
        props = {
            "name": title_case(p.get(config.NAME_KEY)),
            "city_name": _clean(p.get(config.NAME_KEY)),
            "type": title_case(p.get(config.TYPE_KEY)),
            "kind": kind,
            "address": title_case(p.get(config.ADDRESS_KEY)),
            "footprint": "polygon" if footprint else "point",
            "garden_id": gid,
            "objectid": p.get(config.OBJECT_ID_KEY),
        }
        kept.append({
            "type": "Feature",
            "geometry": footprint or {
                "type": "Point",
                "coordinates": [float(c) for c in geom["coordinates"][:2]],
            },
            "properties": {k: v for k, v in props.items() if v is not None},
        })

    orphans = sorted(set(footprints) - joined)
    if orphans:
        # A footprint whose garden left the roster: the roster is the authority,
        # so it is not drawn -- but it is worth a line in the log.
        print(f"  footprints with no in-use roster row: {orphans}")

    with open(config.SLIM_PATH, "w", encoding="utf-8") as out:
        for feat in kept:
            out.write(json.dumps(feat) + "\n")
    with open(config.COUNT_PATH, "w", encoding="utf-8") as f:
        f.write(str(len(kept)))

    food = sum(1 for k in kept if k["properties"]["kind"] == "food")
    point_only = sum(1 for k in kept if k["properties"]["kind"] == "food"
                     and k["properties"]["footprint"] == "point")
    print(f"Done: {config.SLIM_PATH} ({len(kept):,} gardens: {food:,} food, "
          f"{len(kept) - food:,} pollinator; {point_only:,} food gardens "
          f"with no footprint; {skipped:,} rows skipped)")
    if not MIN_EXPECTED <= len(kept) <= MAX_EXPECTED:
        raise RuntimeError(
            f"Slim garden count {len(kept):,} is outside the expected range "
            f"{MIN_EXPECTED:,}-{MAX_EXPECTED:,} -- aborting."
        )
    return config.SLIM_PATH


def _footprints(path):
    """{CommGardenID: Polygon/MultiPolygon geometry} for in-use footprints.

    Rows without an id are left out: there is nothing to join them on. Two rows
    sharing an id are merged into one MultiPolygon.
    """
    with open(path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    parts = defaultdict(list)
    for feat in feats:
        p = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        gid = p.get(config.GARDEN_ID_KEY)
        if gid is None or p.get(config.STATUS_KEY) not in config.INCLUDE_STATUS:
            continue
        if geom.get("type") == "Polygon":
            parts[gid].append(geom["coordinates"])
        elif geom.get("type") == "MultiPolygon":
            parts[gid].extend(geom["coordinates"])
    out = {}
    for gid, polys in parts.items():
        polys = _plain(polys)
        out[gid] = ({"type": "Polygon", "coordinates": polys[0]}
                    if len(polys) == 1
                    else {"type": "MultiPolygon", "coordinates": polys})
    return out


def title_case(text):
    """Title-case an ALL CAPS City string; leave mixed-case text alone.

    Capitalizes after a space, hyphen, period, slash or opening parenthesis,
    but not after an apostrophe ("ST. GEORGE'S" -> "St. George's"), and keeps
    the handful of acronyms in _KEEP. A name the City already typed in mixed
    case ("f.u.n. Commons Westmount Garden") is someone's chosen spelling and
    is returned as it is.
    """
    text = _clean(text)
    if not text or text != text.upper():
        return text
    words = []
    for word in text.split(" "):
        bare = word.strip("().,:;")
        if bare in _KEEP:
            words.append(word.replace(bare, _KEEP[bare]))
            continue
        out = []
        capitalize = True
        for ch in word:
            out.append(ch.upper() if capitalize else ch.lower())
            capitalize = ch in "-./("
        words.append("".join(out))
    return " ".join(words)


def _clean(text):
    if text is None:
        return None
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text or None


def _plain(coords):
    """Round-trip-safe floats for compact json output."""
    if isinstance(coords, list):
        return [_plain(c) for c in coords]
    return float(coords)
