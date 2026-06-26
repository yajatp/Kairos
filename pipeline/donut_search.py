from __future__ import annotations

import logging
import math
import time
from typing import Callable

import requests

logger = logging.getLogger(__name__)

PLACES_BASE = "https://places.googleapis.com/v1"

_SEARCH_RADIUS_M = 1000.0
_SPACING_FACTOR = 1.2
CIRCLE_WARNING_THRESHOLD = 200


def _meters_to_lat_deg(meters: float) -> float:
    return meters / 111320.0


def _meters_to_lng_deg(meters: float, lat: float) -> float:
    cos_lat = math.cos(math.radians(lat))
    return meters / (111320.0 * max(cos_lat, 1e-9))


def compute_bounding_box(coords: list[list[float]]) -> tuple[float, float, float, float]:
    """coords: [[lng, lat], ...] GeoJSON order. Returns (min_lat, max_lat, min_lng, max_lng)."""
    lats = [c[1] for c in coords]
    lngs = [c[0] for c in coords]
    return min(lats), max(lats), min(lngs), max(lngs)


def estimate_circle_count(coords: list[list[float]], radius_m: float = _SEARCH_RADIUS_M) -> int:
    min_lat, max_lat, min_lng, max_lng = compute_bounding_box(coords)
    spacing_m = radius_m * _SPACING_FACTOR
    center_lat = (min_lat + max_lat) / 2.0
    lat_span_m = (max_lat - min_lat) * 111320.0
    lng_span_m = (max_lng - min_lng) * 111320.0 * math.cos(math.radians(center_lat))
    rows = max(1, math.ceil(lat_span_m / spacing_m) + 1)
    cols = max(1, math.ceil(lng_span_m / spacing_m) + 1)
    return rows * cols


def _tile_bounding_box(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    radius_m: float = _SEARCH_RADIUS_M,
) -> list[tuple[float, float]]:
    spacing_m = radius_m * _SPACING_FACTOR
    center_lat = (min_lat + max_lat) / 2.0
    dy = _meters_to_lat_deg(spacing_m)
    dx = _meters_to_lng_deg(spacing_m, center_lat)

    centers: list[tuple[float, float]] = []
    lat = min_lat
    while lat <= max_lat + dy * 0.5:
        lng = min_lng
        while lng <= max_lng + dx * 0.5:
            centers.append((lat, lng))
            lng += dx
        lat += dy
    return centers


def _nearby_search_page(
    lat: float, lng: float, radius_m: float, api_key: str,
) -> dict:
    body: dict = {
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius_m),
            }
        },
        "includedTypes": ["dentist"],
        "maxResultCount": 20,
    }

    resp = requests.post(
        f"{PLACES_BASE}/places:searchNearby",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.businessStatus"
            ),
        },
        json=body,
        timeout=15,
    )
    return resp.json()


def _search_one_circle(lat: float, lng: float, radius_m: float, api_key: str) -> list[dict]:
    results: list[dict] = []

    data = _nearby_search_page(lat, lng, radius_m, api_key)
    if "error" in data:
        logger.warning("Nearby Search error at (%.5f,%.5f): %s", lat, lng, data["error"])
        return results

    for place in data.get("places", []):
        if place.get("businessStatus") == "CLOSED_PERMANENTLY":
            continue
        loc = place.get("location", {})
        results.append({
            "place_id": place["id"],
            "name": place.get("displayName", {}).get("text", ""),
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
        })

    return results


def get_place_details_for_donut(place_id: str, api_key: str) -> dict:
    try:
        resp = requests.get(
            f"{PLACES_BASE}/places/{place_id}",
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": (
                    "id,displayName,formattedAddress,nationalPhoneNumber,"
                    "websiteUri,regularOpeningHours,location"
                ),
            },
            timeout=10,
        )
        time.sleep(0.2)
        data = resp.json()

        if "error" in data:
            logger.warning("Place details failed for %s: %s", place_id, data["error"])
            return {}

        loc = data.get("location", {})

        hours_by_day: dict[str, str] = {}
        if "regularOpeningHours" in data:
            for desc in data["regularOpeningHours"].get("weekdayDescriptions", []):
                if ":" in desc:
                    day, times = desc.split(":", 1)
                    hours_by_day[day.strip()] = times.strip()

        return {
            "place_id": place_id,
            "name": data.get("displayName", {}).get("text", ""),
            "address": data.get("formattedAddress", ""),
            "phone": data.get("nationalPhoneNumber", ""),
            "website": data.get("websiteUri", ""),
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
            "hours_by_day": hours_by_day,
        }
    except Exception as e:
        logger.warning("Error fetching details for %s: %s", place_id, e)
        return {}


def compute_polygon_iou(coords1: list[list[float]], coords2: list[list[float]]) -> float:
    """Intersection-over-union of two polygons. Coords in [[lng, lat], ...] GeoJSON format."""
    try:
        from shapely.geometry import Polygon

        p1 = Polygon([(c[0], c[1]) for c in coords1])
        p2 = Polygon([(c[0], c[1]) for c in coords2])
        if not p1.is_valid or not p2.is_valid:
            return 0.0
        intersection = p1.intersection(p2).area
        union = p1.union(p2).area
        return intersection / union if union > 0 else 0.0
    except Exception:
        return 0.0


def compute_polygon_area_sqmi(coords: list[list[float]]) -> float:
    """Approximate the area of the polygon in square miles."""
    try:
        from shapely.geometry import Polygon
        poly = Polygon([(c[0], c[1]) for c in coords])
        area_sq_deg = poly.area
        # Approx: 1 deg lat = 69 miles, 1 deg lng = 69 * cos(lat) miles
        centroid_lat = poly.centroid.y
        miles_per_deg_lng = 69.0 * math.cos(math.radians(centroid_lat))
        miles_per_deg_lat = 69.0
        # Area in sq miles = area_sq_deg * (miles_per_deg_lat * miles_per_deg_lng)
        return area_sq_deg * (miles_per_deg_lat * miles_per_deg_lng)
    except Exception:
        return 0.0


def compute_polygon_centroid(coords: list[list[float]]) -> tuple[float, float]:
    """Return (lat, lng) of the polygon's centroid."""
    try:
        from shapely.geometry import Polygon
        poly = Polygon([(c[0], c[1]) for c in coords])
        return (poly.centroid.y, poly.centroid.x)
    except Exception:
        if not coords:
            return (0.0, 0.0)
        lats = [c[1] for c in coords]
        lngs = [c[0] for c in coords]
        return (sum(lats) / len(lats), sum(lngs) / len(lngs))


def compute_buffered_outline(coords: list[list[float]], buffer_miles: float) -> list[list[float]]:
    """Exterior ring [[lng, lat], ...] of the polygon expanded by buffer_miles.
    Mirrors the degree buffer (1 mi ~= 1/69 deg) used in filter_by_polygon so the
    drawn outline matches exactly which clinics get tagged 'buffer'."""
    if not coords or buffer_miles <= 0:
        return []
    try:
        from shapely.geometry import Polygon
        poly = Polygon([(c[0], c[1]) for c in coords])
        buffered = poly.buffer(buffer_miles / 69.0)
        return [[x, y] for x, y in buffered.exterior.coords]
    except Exception:
        return []


def filter_by_polygon(
    clinics: list[dict],
    polygon_coords: list[list[float]],
    buffer_miles: float = 0.5,
) -> list[dict]:
    """
    Tag each clinic with inclusion_zone 'core' or 'buffer'; discard anything outside.
    Uses a uniform degree buffer (1 mi ≈ 1/69°) — slightly asymmetric at non-equatorial
    latitudes but acceptable for the sub-mile scale of the DFW use case.
    """
    try:
        from shapely.geometry import Point, Polygon
    except ImportError:
        logger.error("shapely not installed; cannot filter by polygon")
        for c in clinics:
            c["inclusion_zone"] = "core"
        return clinics

    poly = Polygon([(c[0], c[1]) for c in polygon_coords])
    buffered = poly.buffer(buffer_miles / 69.0)

    result: list[dict] = []
    for clinic in clinics:
        lat, lng = clinic.get("lat"), clinic.get("lng")
        if lat is None or lng is None:
            continue
        pt = Point(lng, lat)
        if poly.contains(pt):
            clinic["inclusion_zone"] = "core"
            result.append(clinic)
        elif buffered.contains(pt):
            clinic["inclusion_zone"] = "buffer"
            result.append(clinic)

    return result


def run_grid_search(
    polygon_coords: list[list[float]],
    api_key: str,
    radius_m: float = _SEARCH_RADIUS_M,
    progress_cb: Callable[[str, float], None] | None = None,
) -> list[dict]:
    """
    Tile the polygon bounding box with overlapping circles, run Nearby Search for each,
    deduplicate by Place ID, fetch Place Details for each unique result. Returns raw
    (un-filtered) clinic list; call filter_by_polygon afterward.

    progress_cb(message, fraction_0_to_1)
    """
    min_lat, max_lat, min_lng, max_lng = compute_bounding_box(polygon_coords)
    centers = _tile_bounding_box(min_lat, max_lat, min_lng, max_lng, radius_m)
    total_centers = len(centers)

    seen: dict[str, dict] = {}
    for i, (lat, lng) in enumerate(centers):
        if progress_cb:
            progress_cb(
                f"Searching grid cell {i + 1} of {total_centers}...",
                int(2 + 48 * (i + 1) / max(total_centers, 1)),
            )
        for stub in _search_one_circle(lat, lng, radius_m, api_key):
            pid = stub.get("place_id")
            if pid and pid not in seen:
                seen[pid] = stub
        time.sleep(0.1)

    unique_stubs = list(seen.values())
    if progress_cb:
        progress_cb(
            f"Found {len(unique_stubs)} unique clinics. Fetching details...",
            50,
        )

    clinics: list[dict] = []
    total_stubs = len(unique_stubs)
    for j, stub in enumerate(unique_stubs):
        if progress_cb:
            progress_cb(
                f"Fetching details for clinic {j + 1} of {total_stubs}...",
                int(50 + 40 * (j + 1) / max(total_stubs, 1)),
            )
        details = get_place_details_for_donut(stub["place_id"], api_key)
        if details:
            clinics.append(details)

    return clinics
