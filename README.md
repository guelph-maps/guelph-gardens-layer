# Guelph Community Gardens Layer

Turns the City of Guelph's two community-garden layers &mdash; the
[Community Gardens](https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData1/FeatureServer/18)
roster (points) and the
[Community Gardens Polygons](https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData1/FeatureServer/28)
footprints &mdash; into map-tile layers that OpenStreetMap mappers can add to
the **JOSM** and **iD** editors as a reference overlay, plus a weekly page of
the gardens OSM does not have yet.

**Live layer and how to add it: https://guelph-maps.github.io/guelph-gardens-layer/**
&middot; **Gap page: https://guelph-maps.github.io/guelph-gardens-layer/gaps/**

Part of the [guelph-maps](https://github.com/guelph-maps) organisation. It is a
clone of [guelph-parks-layer](https://github.com/guelph-maps/guelph-parks-layer):
the same `download -> slim -> compare -> vector -> raster -> site -> publish`
pipeline. What differs is that there are two sources, and `slim` joins them.

The audit behind it is
[`guelph-osm-import-audit`](https://github.com/guelph-maps/guelph-osm-import-audit)
(private), whose 2026-10-09 recalibration (`findings/recalibration.md`,
"Community gardens") rated it **4 / conflate**: 22 of the City's 40 in-use
garden footprints had no OSM garden within 25 m, and OSM's side was already
being closed by hand &mdash; eight community gardens added or retagged between
2026-06-25 and 09-30. A page is the tool for that.

## First run (2026-10-09, OSM base 2026-10-10 00:10Z)

| | |
|---|--:|
| City food-growing gardens on the roster | **43** (40 with a footprint, 3 without) |
| &nbsp;&nbsp;matched cleanly in OSM | 10 |
| &nbsp;&nbsp;`missing` &mdash; no OSM garden near the footprint | **23** |
| &nbsp;&nbsp;`point_only` &mdash; no footprint, no OSM garden near the point | 3 |
| &nbsp;&nbsp;`untyped` &mdash; matched to a bare `leisure=garden` | 1 |
| &nbsp;&nbsp;`unnamed` &mdash; matched, OSM garden has no name | 3 |
| &nbsp;&nbsp;`name_mismatch` &mdash; matched, OSM has another name | 3 |
| pollinator patches (shown, not counted) | 27 (2 with an OSM garden near) |
| OSM gardens in the bbox | 74 |

That reproduces the recalibration. Its 22 missing footprints become 23 because
matching is one-to-one (below): West Village Co-op Youth Farm loses the OSM
garden it shared with Parkwood, which was one of its "4 named differently".
Its 3 unnamed are the same three (Centennial CVI, Eramosa River Park food
forest, f.u.n. Commons / The Seed), and its 1 untyped is Guelph Community Food
Forest.

## What it produces

- **Vector tiles** (MVT, layer `gardens`, z12&ndash;19) &mdash; one feature per
  in-use roster garden: its footprint polygon, or its roster point when the
  City has drawn none. Tags: `name`, `city_name`, `type`, `kind`
  (`food`/`pollinator`), `address`, `footprint` (`polygon`/`point`),
  `garden_id`, `objectid`.
- **Raster tiles** (PNG, z13&ndash;17) &mdash; footprints in translucent green
  with a dark outline, a green dot for every food garden too small to see as a
  shape (or with no shape), an amber dot for every pollinator patch, and names
  from z15 (pollinator names only at z17).
- A **landing page** with copy-paste "add this layer" instructions.
- A **gap-review page** ([`/gaps/`](https://guelph-maps.github.io/guelph-gardens-layer/gaps/))
  with a map, a filterable table and OSM / iD / JOSM links per garden (the
  JOSM link needs JOSM running with Preferences → Remote Control enabled), and a
  [history page](https://guelph-maps.github.io/guelph-gardens-layer/gaps/history.html)
  charting the counts over time, one point per weekly run.

All of it is published to GitHub Pages and rebuilt weekly.

## The two sources, and which one is the authority

The recalibration's key finding was that **the layer choice flips for a
watcher**. The audit preferred the polygons for an import. But the polygons
have been frozen since 2025-06; the points are the live roster &mdash; two new
gardens on 2026-06-11, edits through 2026-07. So:

- **The roster (points) decides which gardens exist and what they are called.**
  71 rows: 43 food-growing in use (traditional, communal, food forest), 27
  pollinator patches, 1 `FUTURE` food forest with no name, which is dropped.
- **A footprint (polygon) only lends a garden its shape**, joined on
  `CommGardenID` and nothing else. Only `IN-USE` footprints join. Two of the
  newest roster rows (Courtney/Goines/Mallott Park, Exhibition Park) carry no
  id, and so do the footprint layer's two `FUTURE` polygons; joining on a
  missing key would draw a planned garden's outline around a built one, so a
  missing id never joins. Golfview Garden Guild (id 41) has no in-use footprint
  either: its outline is in the layer as a `FUTURE` "Golfview Community
  Garden". These three are drawn as dots and their status is `point_only`.
- A name join would be no better: footprint 22 still says *THE SEED YOUTH FARM
  - FOOD FROM HOME = FOOD FOR HOME (FFH) PROJECT* where the roster now says
  *f.u.n. Commons Westmount Garden*. The roster's name wins.

Names on both layers are ALL CAPS. `name` is title-cased for the map, with a
handful of fixes (`CVI`, `GCVI`, `FFH`, `Co-op`, `McCrae`); `city_name` keeps
the City's text verbatim. A name someone typed in mixed case is left as it is.
Mappers should take the name from the sign.

**Treat the outline as a hint.** Many footprints are a single bed &mdash; the
median is 233 m&sup2;, the smallest 34 m&sup2; &mdash; drawn in 2025 or
earlier. Both pages tell mappers to map what is on the ground, usually
`leisure=garden` + `garden:type=community` around the whole plot area.

## Matching (`src/compare.py`)

OSM candidates are every `leisure=garden`, `landuse=allotments` and
`landuse=orchard` node, closed way and multipolygon in the Guelph bbox (four of
Guelph's community gardens are mapped as a node). A City garden is matched when
a candidate lies within **25 m** of its footprint's edge &mdash; or of its
roster point when it has no footprint. The recalibration found the same 22
unmatched footprints at 10, 25, 50 and 100 m, so the radius is not what the
count hangs on.

Matching is **one-to-one**. Parkwood Community Garden and West Village Co-op
Youth Farm sit side by side at 170 Stephanie Drive, and both are within reach
of OSM way 1136007863, *Stephanie Drive Community Garden*. One OSM garden
cannot stand for two of the City's, so every garden/OSM pair in range is
ranked &mdash; a name that agrees first, then an OSM garden tagged
`garden:type=community` (or allotments/orchard), then the nearer &mdash; and
taken greedily while both sides are free. Pollinator patches are paired
afterwards, against what the food gardens left.

Names agree when they are equal after dropping *community, communal,
garden(s), vegetable, the, project* and punctuation, or one contains the other
(the recalibration's rule). Each food garden gets one status:

| status | meaning |
|---|---|
| `missing` | no OSM garden within 25 m of its footprint |
| `point_only` | no footprint, and no OSM garden within 25 m of its roster point |
| `untyped` | matched to a `leisure=garden` with no `garden:type=community` &mdash; checked first, as the weakest match |
| `unnamed` | matched, but the OSM garden has no `name` |
| `name_mismatch` | matched, but the OSM name is another name |

**Pollinator patches** (27 roster rows) are on the layer and on the gap page,
off by default, and **never counted**: OSM has no settled tag for a pollinator
garden, and a page that counted them would be asking mappers to invent one.

The geometry is pure Python in a local equirectangular projection &mdash; 70
gardens against 74 OSM features needs nothing heavier.

## Setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Set up WSL2 + tippecanoe once &mdash; see [wsl-setup.md](wsl-setup.md).
3. Confirm the GitHub repo in `src/config.py` (`GITHUB_REPO`, `PAGES_URL`).

## Usage

```
python run.py download   # fetch the roster and the footprints (smart-cached)
python run.py slim       # join roster to footprints -> slim GeoJSONL
python run.py compare    # diff City gardens against OSM -> data/gaps.geojson
python run.py backfill   # one-off: reconstruct past weeks' gap counts from OSM history
python run.py vector     # build vector (MVT) tiles via WSL tippecanoe
python run.py raster     # build labelled raster (PNG) tiles
python run.py site       # render the landing page (+ the gap-review page)
python run.py publish    # force-push the site to the gh-pages branch

python run.py build      # download + slim + compare + vector + raster + site
python run.py update     # build + publish  (the scheduled entry point)
```

Build output lands in `build/site/`; that directory is what gets published.

## Download

Each layer is an ArcGIS `/query` with `outSR=4326` (the service stores
EPSG:26917). A `/query` response has no meaningful `Last-Modified`, so each
body is hashed and an unchanged hash keeps the existing dated file
(`data/gardens-points-DATE.geojson`, `data/gardens-polygons-DATE.geojson`).
The two are dated apart on purpose and both dates are printed on the pages:
the roster moves, the footprints do not.

Both layers are fetched and checked before either is written, so a failure
halfway never leaves a new roster beside last week's footprints. A body
carrying an ArcGIS `error` object (the service says so with HTTP 200) or
`exceededTransferLimit` is refused; `maxRecordCount` is 100,000 against ~70
rows.

## Tile endpoints

```
https://guelph-maps.github.io/guelph-gardens-layer/tiles/vector/{z}/{x}/{y}.pbf   (z12-19)
https://guelph-maps.github.io/guelph-gardens-layer/tiles/raster/{z}/{x}/{y}.png   (z13-17)
```

The vector layer name is `gardens`. tippecanoe runs with `-r1
--no-tiny-polygon-reduction`: seventy small features are kept whole at every
zoom.

## Hosting

The tile pyramid is published to an orphan `gh-pages` branch, recreated and
force-pushed on every build so repository history never grows.

## Scheduling (Windows)

Run as Administrator:

```powershell
.\schedule-add.ps1      # registers a weekly task "kk-GuelphGardensLayer", Tuesdays 19:30
.\schedule-remove.ps1   # unregisters it
```

Weekly is enough &mdash; the roster gains a garden or two a year; it is the gap
page, which diffs against live OSM, that moves week to week. Tuesday 19:30 is
clear of every other layer's slot (16:30 is taken Monday to Sunday, and Monday
19:30 is the water layer), so no two drive tippecanoe in the same WSL instance
at once.

### The link gate

Both network steps &mdash; the dataset query and the `gh-pages` push &mdash;
run behind `addressvault.net`, the same offline/metered gate the address vault
pulls behind. A dead link is not a build failure: `run.py` exits **75**
(`EX_TEMPFAIL`), nothing is written, and the task's restart-on-failure retries
three times half an hour apart rather than leaving a seven-day gap. It does not
wait the link out, since the task carries a hard `ExecutionTimeLimit` that would
kill a long wait anyway.

### Gap history

Every live comparison appends one line to `data/history.jsonl` -- the date, the
OSM data date, and the counts per status -- and
the site step charts it at [`/gaps/history.html`](https://guelph-maps.github.io/guelph-gardens-layer/gaps/history.html),
with the rows published beside it as `gaps/history.jsonl`. That is the whole
record the observer keeps: the tiles and the gap list are rebuilt from scratch
and force-pushed each week, but this file only grows, so the scheduled
`update` extends the chart by one point every Tuesday. A run that fell back to
cached OSM is not recorded; it observed nothing new, and a point it drew would
be a false plateau. A live row's OSM date is the mirror's declared
`timestamp_osm_base`, so a mirror answering with old data shows as such.

Nothing heavier is kept on purpose. OSM keeps its own history, so the record is
reconstructible: `python run.py backfill` asks `overpass-api.de` what OSM looked
like on each past Monday (an attic query, `[date:...]`, which only that
instance is relied on for) and re-runs the comparison against it, adding rows
marked `attic`. It is paced -- one attempt per date, 30 s between dates, and
it stops at the first unanswered query -- because attic queries cost the
instance more than live ones and this is a one-off, not the weekly build. Dates
already on record are skipped, so an interrupted run resumes when re-run.
The default range starts 2026-06-01, the same Monday the parks sibling's
chart starts on; `--since`, `--until`, `--every` and `--pause` adjust it.

Two caveats the page states: a reconstructed week is compared against
*today's* City roster (the City side is not archived), and the counts follow
the roster, so they move when the City adds or retires a garden, not only when
someone maps one.

A checkout without `data/history.jsonl` (a fresh clone, a wiped `data/`) seeds
itself from the published `gaps/history.jsonl` before recording, so the record
survives the machine it was made on.

### Keeping the OSM half fresh

The gap page is only worth acting on if both sides of the diff are current, and
the OSM side is the one that moves daily. Every mirror in `OVERPASS_URLS` is
tried, and the whole list is retried `OVERPASS_ROUNDS` times a minute apart,
because what is being worked around is a loaded instance shedding one request.
A reply with fewer than `OSM_MIN_ELEMENTS` elements is refused however healthy
its status code: a regional instance answers an out-of-region bbox with a
valid, empty result, which taken at face value would report every City garden
as missing from OSM. The floor (35) is half the first live reply's 74.

`overpass.kumi.systems` is deliberately **not** in the list. It returned 504s
through August 2026 and has since been caught serving months-stale data, which
is the worse of the two failures because it looks exactly like success.
`overpass.private.coffee` was dropped on 2026-09-29 for the same failure: the
Toronto sibling caught it serving OSM from May and July on consecutive days.
That leaves `overpass-api.de` alone, and a reply from any mirror whose data is
more than `OSM_MAX_AGE_DAYS` (3) old is refused like a 504 &mdash; and so is a
reply that carries no `timestamp_osm_base` at all, since it cannot be shown to
be fresh (the parks template dated such a reply "today"). Overpass also sends
a runtime error as an HTML page with a 200; that fails to parse and counts as
no answer. The first query this project ever sent got exactly that.

The page prints the **OSM database timestamp the mirror declares about its own
reply** (`osm3s.timestamp_osm_base`), not the date of the build — a mirror can
answer in two seconds with data from last week, and printing "today" beside it
would hide precisely that.

If no mirror can be reached, the cache is used &mdash; a stale gap page beats
none &mdash; but the run stops being quiet about it. The page carries a warning
banner beside the OSM date, and `update` exits **70** *after* publishing, so the
tiles still ship and the task's restart-on-failure tries the fetch again in half
an hour instead of in a week. Being offline is told apart from an Overpass
outage and stays a 75.


## Tests

```
pytest
```

## Licence / attribution

Garden data is &copy; City of Guelph, published under the
[Open Government Licence &ndash; City of Guelph](https://gismaps.guelph.ca/Images/OpenDataLicenceVersion2.pdf).
The OSMF Licence Working Group approved that licence as `compatible` on
2024-09-09.

**This project redistributes City data** &mdash; as published tiles on a public
URL &mdash; and the licence attaches a required attribution to that. The
landing page, the gap page and the history page each carry, visibly:

> Contains information licensed under the Open Government Licence – City of Guelph.

linked to the licence text. The same attribution is embedded in the vector tile
metadata. This is a condition of use, not a courtesy: if you fork this, the
notice travels with it.
