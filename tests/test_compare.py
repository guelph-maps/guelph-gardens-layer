"""Unit tests for the Overpass fetch: mirrors, retries, and the cache fallback.

What these pin is the failure that actually happened. On 2026-08-10 and again on
2026-08-17 overpass-api.de answered 504, the single attempt gave up, the run
silently compared against a fortnight-old cache and reported success -- so the
gap page went two weeks without anyone noticing. Every test here is about that
run trying harder, and about saying so when it still could not.
"""

import json
import os
import sys

import pytest
import requests
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addressvault import net  # noqa: E402
from src import compare, config, site  # noqa: E402

# Minutes old, as a healthy instance's reply is; a fixed date would age past
# OSM_MAX_AGE_DAYS and be refused.
OSM_BASE = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
GOOD = {"osm3s": {"timestamp_osm_base": OSM_BASE},
        "elements": [{"type": "way", "id": i, "tags": {}, "geometry": []}
                     for i in range(config.OSM_MIN_ELEMENTS + 1)]}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        return self.payload


def _post(by_host):
    """A requests.post that answers per hostname from ``by_host``."""
    calls = []

    def post(url, data=None, headers=None, timeout=None):
        calls.append(url)
        for host, reply in by_host.items():
            if host in url:
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise requests.ConnectionError("no route")

    post.calls = calls
    return post


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point the cache + sidecar at a temp dir, and never really sleep."""
    monkeypatch.setattr(config, "OSM_CACHE_PATH", str(tmp_path / "osm-gardens.json"))
    monkeypatch.setattr(config, "OSM_FETCH_PATH", str(tmp_path / ".osm-fetch.json"))
    monkeypatch.setattr(compare.time, "sleep", lambda _s: None)
    return tmp_path


def test_a_dead_primary_falls_through_to_the_next_mirror(paths, monkeypatch):
    # The whole point: one sick instance is not an outage.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://a.example/api", "https://b.example/api"))
    post = _post({"a.example": FakeResponse(status=504),
                  "b.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)

    data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert len(data["elements"]) == len(GOOD["elements"])
    assert [u.split("/")[2] for u in post.calls] == ["a.example", "b.example"]


def test_the_mirror_list_is_retried_before_giving_up(paths, monkeypatch):
    # A 504 is load shedding, and load sheds. Trying the list once was what
    # turned a transient failure into a fortnight of stale data.
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 3)
    replies = [FakeResponse(status=504), FakeResponse(status=504),
               FakeResponse(GOOD)]

    def post(url, data=None, headers=None, timeout=None):
        return replies.pop(0)

    monkeypatch.setattr(compare.requests, "post", post)
    _data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert replies == [], "every round should have been used"


def test_an_implausibly_small_reply_is_not_accepted(paths, monkeypatch):
    # overpass.osm.ch serves a Switzerland extract and answers a Guelph bbox
    # with HTTP 200 and zero elements. Believing it would report every City
    # garden as missing from OSM.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://regional.example/api", "https://good.example/api"))
    post = _post({"regional.example": FakeResponse({"elements": []}),
                  "good.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)

    data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert len(data["elements"]) == len(GOOD["elements"])


def test_a_reply_from_months_old_data_is_not_accepted(paths, monkeypatch):
    # overpass.private.coffee answered the Toronto sibling on 2026-09-29 in
    # full, with OSM as of 2026-05-06; its page showed May as this week.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://lagging.example/api", "https://good.example/api"))
    stale = {**GOOD, "osm3s": {"timestamp_osm_base": "2026-05-06T03:25:00Z"}}
    post = _post({"lagging.example": FakeResponse(stale),
                  "good.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)

    _data, osm_date, from_cache = compare._load_osm()
    assert from_cache is False
    assert osm_date.startswith(OSM_BASE[:10])
    assert [u.split("/")[2] for u in post.calls] == ["lagging.example", "good.example"]


def test_a_good_fetch_records_when_and_where_it_came_from(paths, monkeypatch):
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://good.example/api",))
    monkeypatch.setattr(compare.requests, "post",
                        _post({"good.example": FakeResponse(GOOD)}))

    _data, osm_date, _from_cache = compare._load_osm()
    with open(config.OSM_FETCH_PATH, encoding="utf-8") as f:
        sidecar = json.load(f)
    # The date the page prints is the OSM database timestamp the mirror states
    # about its own reply, NOT the day the fetch happened: a mirror can answer
    # in two seconds with data from last week, and "today" would hide that.
    assert osm_date == f"{OSM_BASE[:10]} {OSM_BASE[11:16]}Z"
    assert sidecar["mirror"] == "good.example"
    assert sidecar["timestamp_osm_base"] == OSM_BASE
    assert sidecar["osm_base"] == osm_date


def test_the_cache_is_used_only_after_every_mirror_fails(paths, monkeypatch):
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    with open(config.OSM_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched": "2026-08-03", "mirror": "old.example"}, f)

    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://a.example/api", "https://b.example/api"))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 2)
    post = _post({"a.example": FakeResponse(status=504),
                  "b.example": FakeResponse(status=504)})
    monkeypatch.setattr(compare.requests, "post", post)
    monkeypatch.setattr(net, "wait_for_link", lambda wait=True: None)

    _data, fetched, from_cache = compare._load_osm()
    assert len(post.calls) == 4, "both mirrors, both rounds"
    # The date carried out is the cache's own, not today's -- that value is what
    # the gap page prints, and printing today's would be the original lie.
    assert (fetched, from_cache) == ("2026-08-03", True)


def test_with_no_cache_and_no_mirror_the_run_is_told_to_fail(paths, monkeypatch):
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 1)
    monkeypatch.setattr(compare.requests, "post",
                        _post({"a.example": FakeResponse(status=504)}))
    monkeypatch.setattr(net, "wait_for_link", lambda wait=True: None)

    with pytest.raises(compare.OsmUnavailable):
        compare._load_osm()


def test_being_offline_is_not_reported_as_an_overpass_outage(paths, monkeypatch):
    # No link means the fetch never happened; that is a 75 elsewhere in the
    # pipeline, not a broken Overpass, and it must not be confused with one.
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 1)
    monkeypatch.setattr(compare.requests, "post",
                        _post({"a.example": requests.ConnectionError("offline")}))

    def no_link(wait=True):
        raise net.LinkUnavailable("no usable link")

    monkeypatch.setattr(net, "wait_for_link", no_link)
    _data, _fetched, from_cache = compare._load_osm()
    assert from_cache is True


def test_a_reply_that_does_not_say_how_old_it_is_is_not_accepted(paths, monkeypatch):
    # The template dated such a reply "today". A mirror that will not state its
    # OSM base cannot be shown to be fresh, so it counts as no answer.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://terse.example/api", "https://good.example/api"))
    terse = {"elements": GOOD["elements"]}
    post = _post({"terse.example": FakeResponse(terse),
                  "good.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)
    _data, osm_date, from_cache = compare._load_osm()
    assert from_cache is False
    assert osm_date == f"{OSM_BASE[:10]} {OSM_BASE[11:16]}Z"
    assert [u.split("/")[2] for u in post.calls] == ["terse.example", "good.example"]


def test_the_cache_date_falls_back_to_the_file_mtime(paths, monkeypatch):
    # A cache written before the sidecar existed still has to date itself.
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    os.utime(config.OSM_CACHE_PATH, (1754247600, 1754247600))  # 2026-08-03 local
    assert compare._cache_date().startswith("20")


# --- what the reader sees ---------------------------------------------------

def test_a_stale_comparison_says_so_on_the_page():
    note = site._osm_note({"osm_stale": True, "osm_date": "2026-08-03"})
    assert "2026-08-03" in note and "class=\"stale\"" in note


def test_a_fresh_comparison_adds_nothing():
    assert site._osm_note({"osm_stale": False, "osm_date": "2026-08-17"}) == ""


# --- matching ---------------------------------------------------------------
#
# Coordinates are lon/lat near Guelph; at this latitude 0.0001 deg of longitude
# is ~8 m and of latitude ~11 m.

X, Y = -80.25, 43.54
COMMUNITY = {"leisure": "garden", "garden:type": "community"}


def _box(x, y, dx=0.0002, dy=0.0002):
    return [[x, y], [x + dx, y], [x + dx, y + dy], [x, y + dy], [x, y]]


def _garden(name, x, y, kind="food", footprint="polygon"):
    geom = ({"type": "Polygon", "coordinates": [_box(x, y)]}
            if footprint == "polygon" else {"type": "Point", "coordinates": [x, y]})
    return {"type": "Feature", "geometry": geom, "properties": {
        "name": name.title(), "city_name": name, "kind": kind,
        "footprint": footprint}}


def _osm_way(oid, x, y, **tags):
    return {"type": "way", "id": oid, "tags": tags,
            "geometry": [{"lon": a, "lat": b} for a, b in _box(x, y)]}


def _run(monkeypatch, tmp_path, gardens, elements):
    slim = tmp_path / "gardens-slim.geojsonl"
    slim.write_text("".join(json.dumps(g) + "\n" for g in gardens), encoding="utf-8")
    monkeypatch.setattr(config, "SLIM_PATH", str(slim))
    city = list(compare._city_features())
    gaps, counts = compare._match(city, compare._osm_gardens({"elements": elements}))
    return {g["properties"]["city_name"]: g["properties"] for g in gaps}, counts


def test_one_osm_garden_cannot_stand_for_two_city_gardens(monkeypatch, tmp_path):
    # Parkwood and West Village Co-op Youth Farm, side by side at 170 Stephanie
    # Drive, both lie within reach of OSM way 1136007863. Counting it twice
    # hid one garden from the worklist.
    gaps, counts = _run(monkeypatch, tmp_path, [
        _garden("PARKWOOD COMMUNITY GARDEN", X, Y),
        _garden("WEST VILLAGE CO-OP YOUTH FARM", X + 0.0003, Y),
    ], [_osm_way(1136007863, X, Y, name="Stephanie Drive Community Garden", **COMMUNITY)])
    assert counts["missing"] == 1
    assert gaps["PARKWOOD COMMUNITY GARDEN"]["status"] == "name_mismatch"
    assert gaps["WEST VILLAGE CO-OP YOUTH FARM"]["status"] == "missing"


def test_a_name_that_agrees_wins_the_contested_osm_garden(monkeypatch, tmp_path):
    gaps, counts = _run(monkeypatch, tmp_path, [
        _garden("NEARER COMMUNITY GARDEN", X, Y),
        _garden("SKOV PARK COMMUNITY GARDEN", X + 0.0003, Y),
    ], [_osm_way(1, X, Y, name="Skov Park Garden", **COMMUNITY)])
    assert counts["matched"] == 1
    assert gaps["NEARER COMMUNITY GARDEN"]["status"] == "missing"
    assert "SKOV PARK COMMUNITY GARDEN" not in gaps


def test_the_radius_is_measured_from_the_edge(monkeypatch, tmp_path):
    # ~16 m east of the footprint's edge: matched. ~40 m: not.
    near = _osm_way(1, X + 0.0002 + 0.0002, Y, name="Near", **COMMUNITY)
    gaps, _ = _run(monkeypatch, tmp_path, [_garden("NEAR", X, Y)], [near])
    assert "NEAR" not in gaps
    far = _osm_way(2, X + 0.0002 + 0.0005, Y, name="Far", **COMMUNITY)
    gaps, _ = _run(monkeypatch, tmp_path, [_garden("FAR", X, Y)], [far])
    assert gaps["FAR"]["status"] == "missing"


def test_a_garden_mapped_as_a_node_counts(monkeypatch, tmp_path):
    node = {"type": "node", "id": 5, "lon": X + 0.0001, "lat": Y + 0.0001,
            "tags": {"name": "Eramosa Food Forest", **COMMUNITY}}
    gaps, counts = _run(monkeypatch, tmp_path,
                        [_garden("ERAMOSA FOOD FOREST", X, Y)], [node])
    assert counts["matched"] == 1 and not gaps


def test_statuses_of_a_match(monkeypatch, tmp_path):
    gardens = [_garden("A GARDEN", X, Y), _garden("B GARDEN", X, Y + 0.01),
               _garden("C GARDEN", X, Y + 0.02), _garden("D GARDEN", X, Y + 0.03)]
    osm = [_osm_way(1, X, Y, **COMMUNITY),                                  # no name
           _osm_way(2, X, Y + 0.01, name="Other", **COMMUNITY),             # other name
           _osm_way(3, X, Y + 0.02, name="C Garden", leisure="garden"),     # bare garden
           _osm_way(4, X, Y + 0.03, name="D", landuse="allotments")]        # fine
    gaps, counts = _run(monkeypatch, tmp_path, gardens, osm)
    assert gaps["A GARDEN"]["status"] == "unnamed"
    assert gaps["B GARDEN"]["status"] == "name_mismatch"
    assert gaps["C GARDEN"]["status"] == "untyped"
    assert gaps["C GARDEN"]["osm_tag"] == "leisure=garden"
    assert "D GARDEN" not in gaps and counts["matched"] == 1


def test_a_garden_with_no_footprint_is_point_only(monkeypatch, tmp_path):
    gaps, counts = _run(monkeypatch, tmp_path,
                        [_garden("GOLFVIEW GARDEN GUILD", X, Y, footprint="point")], [])
    assert gaps["GOLFVIEW GARDEN GUILD"]["status"] == "point_only"
    assert counts["point_only"] == 1 and counts["missing"] == 0


def test_pollinator_patches_are_listed_never_counted(monkeypatch, tmp_path):
    # And they only get the OSM gardens the food gardens left over.
    gaps, counts = _run(monkeypatch, tmp_path, [
        _garden("BEE PATCH", X, Y, kind="pollinator", footprint="point"),
        _garden("FOOD", X, Y),
    ], [_osm_way(1, X, Y, name="Food", **COMMUNITY)])
    assert gaps["BEE PATCH"]["status"] == "pollinator"
    assert "osm_url" not in gaps["BEE PATCH"]
    assert counts["pollinator"] == 1 and counts["missing"] == 0
    assert sum(counts[s] for s in compare.GAP_STATUSES) == 0


def test_an_open_way_is_not_a_garden(monkeypatch, tmp_path):
    line = {"type": "way", "id": 9, "tags": COMMUNITY,
            "geometry": [{"lon": X, "lat": Y}, {"lon": X + 0.0002, "lat": Y}]}
    gaps, _ = _run(monkeypatch, tmp_path, [_garden("G", X, Y)], [line])
    assert gaps["G"]["status"] == "missing"


def test_names_agree():
    assert compare.names_agree("BRANT AVENUE COMMUNITY GARDEN", "Brant Avenue Garden")
    assert compare.names_agree("STEPHANIE DRIVE PARK COMMUNITY ORCHARD",
                               "Stephanie Drive Park Orchard")
    assert compare.names_agree("ST. GEORGE'S PARK COMMUNITY GARDEN",
                               "St. George's Park Community Garden")
    assert not compare.names_agree("PARKWOOD COMMUNITY GARDEN",
                                   "Stephanie Drive Community Garden")
    assert not compare.names_agree("COMMUNITY GARDEN", "Community Garden")
    assert not compare.names_agree("A GARDEN", None)


def test_distance_overlapping_shapes_is_zero():
    a = [compare._proj(x, y) for x, y in _box(X, Y)]
    b = [compare._proj(x, y) for x, y in _box(X + 0.0001, Y + 0.0001)]
    assert compare._distance([a], [b]) == 0
    inner = [compare._proj(X + 0.0001, Y + 0.0001)]
    assert compare._distance([a], [inner]) == 0
