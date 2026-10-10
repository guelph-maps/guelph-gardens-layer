"""Tests for the slim step: the roster-to-footprint join and the name casing.

The join is where this layer can lie quietly. Two of the newest roster rows
carry no garden id, and so do the footprint layer's two FUTURE polygons --
joining on a missing key would draw a planned garden's outline around a new
one. And the footprints still carry a renamed garden under its old name, so the
roster's name has to win.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config  # noqa: E402
import src.slim as slim_mod  # noqa: E402
from src.slim import slim, title_case  # noqa: E402


@pytest.mark.parametrize("raw, expected", [
    ("BRANT AVENUE COMMUNITY GARDEN", "Brant Avenue Community Garden"),
    ("ST. GEORGE'S PARK COMMUNITY GARDEN", "St. George's Park Community Garden"),
    ("CENTENNIAL CVI GARDEN", "Centennial CVI Garden"),
    ("WEST VILLAGE CO-OP YOUTH FARM", "West Village Co-op Youth Farm"),
    ("JOHN MCCRAE COMMUNITY GARDEN", "John McCrae Community Garden"),
    ("FARM FRESH: PAY ON YOUR WAY", "Farm Fresh: Pay On Your Way"),
    ("THE SEED (FFH) PROJECT", "The Seed (FFH) Project"),
    ("GUELPH COMMUNITY ORCHARD PROJECT - 1", "Guelph Community Orchard Project - 1"),
    # Someone typed this one in mixed case on purpose; it is left alone.
    ("f.u.n. Commons Westmount Garden", "f.u.n. Commons Westmount Garden"),
    ("64 BRANT AVE ", "64 Brant Ave"),
    (None, None),
    ("", None),
])
def test_title_case(raw, expected):
    assert title_case(raw) == expected


def _point(name, gid, gtype="TRADITIONAL COMMUNITY GARDEN", status="IN-USE", oid=1):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-80.25, 43.54]},
            "properties": {config.NAME_KEY: name, config.TYPE_KEY: gtype,
                           config.ADDRESS_KEY: "1 TEST ST", config.STATUS_KEY: status,
                           config.GARDEN_ID_KEY: gid, config.OBJECT_ID_KEY: oid}}


def _polygon(name, gid, status="IN-USE"):
    x, y = -80.25, 43.54
    ring = [[x, y], [x + 0.0002, y], [x + 0.0002, y + 0.0002], [x, y + 0.0002], [x, y]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {config.NAME_KEY: name, config.STATUS_KEY: status,
                           config.GARDEN_ID_KEY: gid}}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SLIM_PATH", str(tmp_path / "gardens-slim.geojsonl"))
    monkeypatch.setattr(config, "COUNT_PATH", str(tmp_path / "gardens.count"))
    monkeypatch.setattr(slim_mod, "MIN_EXPECTED", 1)

    def go(points, polygons):
        pts = tmp_path / "gardens-points-2026-10-09.geojson"
        pol = tmp_path / "gardens-polygons-2026-10-09.geojson"
        pts.write_text(json.dumps({"type": "FeatureCollection", "features": points}))
        pol.write_text(json.dumps({"type": "FeatureCollection", "features": polygons}))
        slim(str(pts), str(pol))
        with open(config.SLIM_PATH, encoding="utf-8") as f:
            feats = [json.loads(line) for line in f]
        return {g["properties"]["city_name"]: g for g in feats}
    return go


def test_the_roster_joins_its_footprint_on_the_garden_id(run):
    kept = run([_point("BRANT AVENUE COMMUNITY GARDEN", 1)],
               [_polygon("BRANT AVENUE COMMUNITY GARDEN", 1)])
    g = kept["BRANT AVENUE COMMUNITY GARDEN"]
    assert g["geometry"]["type"] == "Polygon"
    assert g["properties"]["footprint"] == "polygon"
    assert g["properties"]["name"] == "Brant Avenue Community Garden"
    assert g["properties"]["kind"] == "food"


def test_a_missing_id_never_joins_a_missing_id(run):
    # Courtney/Goines/Mallott and Exhibition Park have no id; nor do the two
    # FUTURE footprints. None == None must not be a join.
    kept = run([_point("EXHIBITION PARK GARDEN", None)],
               [_polygon(None, None), _polygon("GOLFVIEW COMMUNITY GARDEN", None)])
    g = kept["EXHIBITION PARK GARDEN"]
    assert g["geometry"]["type"] == "Point"
    assert g["properties"]["footprint"] == "point"


def test_a_future_footprint_is_not_a_footprint(run):
    kept = run([_point("GOLFVIEW GARDEN GUILD", 41)],
               [_polygon("GOLFVIEW COMMUNITY GARDEN", 41, status="FUTURE")])
    assert kept["GOLFVIEW GARDEN GUILD"]["properties"]["footprint"] == "point"


def test_the_roster_name_wins_over_the_footprint_name(run):
    kept = run([_point("f.u.n. Commons Westmount Garden", 22)],
               [_polygon("THE SEED YOUTH FARM - FOOD FROM HOME", 22)])
    assert "f.u.n. Commons Westmount Garden" in kept
    assert kept["f.u.n. Commons Westmount Garden"]["properties"]["footprint"] == "polygon"


def test_future_rows_are_dropped_and_pollinators_kept_apart(run):
    kept = run([_point("A FOOD FOREST", 42, gtype="FOOD FOREST", status="FUTURE"),
                _point("BEE PATCH", None, gtype=config.POLLINATOR_TYPE),
                _point("FOOD", 1)], [])
    assert "A FOOD FOREST" not in kept
    assert kept["BEE PATCH"]["properties"]["kind"] == "pollinator"
    assert kept["FOOD"]["properties"]["kind"] == "food"
    with open(config.COUNT_PATH, encoding="utf-8") as f:
        assert int(f.read()) == 2


def test_two_footprints_under_one_id_become_one_multipolygon(run):
    kept = run([_point("SPLIT GARDEN", 7)],
               [_polygon("SPLIT GARDEN", 7), _polygon("SPLIT GARDEN", 7)])
    assert kept["SPLIT GARDEN"]["geometry"]["type"] == "MultiPolygon"
    assert len(kept["SPLIT GARDEN"]["geometry"]["coordinates"]) == 2


def test_an_implausible_count_stops_the_run(run, monkeypatch):
    monkeypatch.setattr(slim_mod, "MIN_EXPECTED", 5)
    with pytest.raises(RuntimeError, match="outside the expected range"):
        run([_point("ONLY ONE", 1)], [])
