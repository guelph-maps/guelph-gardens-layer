"""Download the City's two Community Gardens layers from its ArcGIS service.

The roster (points, layer 18) and the footprints (polygons, layer 28) are
fetched the same way the parks sibling fetches Park Boundary: an ArcGIS
``/query`` has no meaningful Last-Modified -- it is generated when you ask --
so each body is hashed, and an unchanged hash keeps the existing dated file.
That keeps each file's date meaning "when the City last changed this layer",
which is worth having twice over here: the roster moves, the footprints have
been frozen since 2025-06, and the site says so.

Output contract: one dated GeoJSON FeatureCollection per layer in data/
(gardens-points-DATE.geojson, gardens-polygons-DATE.geojson), which is all
`slim` knows about.

Every request is gated on a usable link first (``addressvault.net``, the same
gate the address vault pulls behind).
"""

import hashlib
import json
import os
import time
from datetime import date

import requests
from addressvault import net

from src import config

# Each layer is ~50 KB. A retry costs a couple of seconds when the link is
# healthy and buys back a week when it is not.
RETRIES = 3
RETRY_WAIT = 30


def download(force=False):
    """Download both layers.

    Returns {key: (status, filepath)} where status is "DOWNLOADED" or
    "SKIPPED". Raises ``net.LinkUnavailable`` when the host has no usable link:
    nothing was attempted, so the caller exits 75 rather than reporting a build
    failure.
    """
    os.makedirs(config.DATA_DIR, exist_ok=True)

    # Ask before doing anything; never block waiting for the link -- the task
    # carries a hard ExecutionTimeLimit, and retrying is the scheduler's job.
    net.wait_for_link(wait=False)

    # Fetch and check both before writing either, so a run that fails halfway
    # never leaves a new roster beside last week's footprints, or the reverse.
    bodies = {}
    for key, (layer, _prefix) in config.SOURCES.items():
        print(f"Querying Community Gardens {key} (layer {layer}) ...")
        body = _fetch(config.dataset_url(layer))
        _check_payload(body)
        bodies[key] = body

    sidecar = _load_sidecar()
    results = {}
    for key, body in bodies.items():
        results[key] = _save(key, body, sidecar, force)
    _save_sidecar(sidecar)
    return results


def _save(key, body, sidecar, force):
    digest = hashlib.sha256(body).hexdigest()
    prior = sidecar.get(key) or {}
    if not force and prior.get("sha256") == digest:
        existing = os.path.join(config.DATA_DIR, prior.get("filename", ""))
        if os.path.isfile(existing):
            print(f"  {key}: unchanged since the last download.")
            return "SKIPPED", existing

    # No server-side edit date exists for the layer as a whole (editingInfo is
    # null), so the file is dated by the day the change was first seen here.
    prefix = config.SOURCES[key][1]
    filename = f"{prefix}-{date.today().isoformat()}.geojson"
    filepath = os.path.join(config.DATA_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(body)
    print(f"  {key}: {filepath} ({len(body) // 1024:,} KB)")
    sidecar[key] = {"sha256": digest, "bytes": len(body), "filename": filename}
    return "DOWNLOADED", filepath


def latest(key):
    """Path of the newest downloaded file for source ``key``."""
    prefix = config.SOURCES[key][1] + "-"
    files = sorted(
        f for f in os.listdir(config.DATA_DIR)
        if f.startswith(prefix) and f.endswith(".geojson")
    ) if os.path.isdir(config.DATA_DIR) else []
    if not files:
        raise RuntimeError(f"No {key} GeoJSON in data/. Run 'download' first.")
    return os.path.join(config.DATA_DIR, files[-1])


def _fetch(url):
    """GET ``url``, retrying a dropped connection. Returns the raw body."""
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": config.USER_AGENT},
                timeout=600,
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            if attempt == RETRIES:
                # Out of retries. If the link itself is down then this was never
                # a City failure -- say so, and the run exits 75.
                net.wait_for_link(wait=False)
                raise
            print(f"  query failed ({e}); retrying in {RETRY_WAIT}s")
            time.sleep(RETRY_WAIT)


def _check_payload(body):
    """Reject an answer that is not a whole FeatureCollection.

    An ArcGIS service answers an error with HTTP 200 and a JSON body carrying an
    ``error`` object, so raise_for_status proves nothing. It also silently
    truncates a page at maxRecordCount and sets ``exceededTransferLimit``; at
    ~70 rows against a limit of 100,000 that cannot happen today, so this
    raises rather than paginating -- a partial roster would report the gardens
    that fell off the end as gone.
    """
    try:
        doc = json.loads(body)
    except ValueError as e:
        raise RuntimeError(f"The service did not return JSON: {e}")
    if "error" in doc:
        raise RuntimeError(f"The service returned an error: {doc['error']}")
    if doc.get("type") != "FeatureCollection":
        raise RuntimeError(f"Expected a FeatureCollection, got {doc.get('type')!r}")
    if doc.get("exceededTransferLimit"):
        raise RuntimeError(
            "The service truncated the result (exceededTransferLimit). The "
            "download is a partial extract -- paginate with resultOffset / "
            "resultRecordCount before trusting it."
        )
    n = len(doc.get("features") or ())
    print(f"  {n:,} features")
    if not n:
        raise RuntimeError("The service returned an empty FeatureCollection.")


def _load_sidecar():
    if os.path.isfile(config.LAST_DOWNLOAD_PATH):
        with open(config.LAST_DOWNLOAD_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_sidecar(sidecar):
    with open(config.LAST_DOWNLOAD_PATH, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2)
