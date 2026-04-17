"""
OpenRouteService API client.
Uses the free tier — no credit card required.
API key stored in ORS_API_KEY env var.
"""
import logging
import time
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ORS_BASE = "https://api.openrouteservice.org"
ORS_ROUTE_DISTANCE_LIMIT_CODE = 2004
MAX_ROUTE_SPLIT_DEPTH = 8

# Simple process-lifetime geocoding cache
_geocode_cache: dict[str, dict] = {}


class ORSError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 0,
        ors_error_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.ors_error_code = ors_error_code


def _is_distance_limit_error(exc: ORSError) -> bool:
    return exc.status_code == 400 and exc.ors_error_code == ORS_ROUTE_DISTANCE_LIMIT_CODE


def _coordinates_from_points(points: list[dict[str, float]]) -> list[list[float]]:
    return [[point["lng"], point["lat"]] for point in points]


def _parse_route_geojson(data: dict[str, Any]) -> dict[str, Any]:
    features = data.get("features", [])
    if not features:
        raise ORSError("ORS directions returned no route.")

    props = features[0]["properties"]
    summary = props["summary"]
    total_meters = float(summary["distance"])
    total_seconds = float(summary["duration"])

    # GeoJSON geometry: coordinates are [lng, lat] pairs.
    geom_coords = features[0]["geometry"]["coordinates"]
    polyline = [[coord[1], coord[0]] for coord in geom_coords]

    return {
        "total_meters": total_meters,
        "total_seconds": total_seconds,
        "polyline": polyline,
    }


def _merge_polylines(first: list[list[float]], second: list[list[float]]) -> list[list[float]]:
    if not first:
        return [point[:] for point in second]
    if not second:
        return [point[:] for point in first]

    head = [point[:] for point in first]
    tail_source = second[1:] if first[-1] == second[0] else second
    tail = [point[:] for point in tail_source]
    return head + tail


def _merge_route_segments(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_meters": first["total_meters"] + second["total_meters"],
        "total_seconds": first["total_seconds"] + second["total_seconds"],
        "polyline": _merge_polylines(first["polyline"], second["polyline"]),
    }


def _midpoint(start: dict[str, float], end: dict[str, float]) -> dict[str, float]:
    return {
        "lat": (start["lat"] + end["lat"]) / 2.0,
        "lng": (start["lng"] + end["lng"]) / 2.0,
    }


def _request_segment_route(start: dict[str, float], end: dict[str, float]) -> dict[str, Any]:
    if start["lat"] == end["lat"] and start["lng"] == end["lng"]:
        return {
            "total_meters": 0.0,
            "total_seconds": 0.0,
            "polyline": [[start["lat"], start["lng"]]],
        }

    data = _post(
        f"{ORS_BASE}/v2/directions/driving-hgv/geojson",
        {"coordinates": _coordinates_from_points([start, end])},
    )
    return _parse_route_geojson(data)


def _route_segment_with_auto_split(
    start: dict[str, float],
    end: dict[str, float],
    split_depth: int = 0,
) -> dict[str, Any]:
    try:
        return _request_segment_route(start, end)
    except ORSError as exc:
        if not _is_distance_limit_error(exc) or split_depth >= MAX_ROUTE_SPLIT_DEPTH:
            raise

        middle = _midpoint(start, end)
        logger.info(
            "Splitting long ORS segment at depth %s between (%s, %s) and (%s, %s)",
            split_depth,
            start["lat"],
            start["lng"],
            end["lat"],
            end["lng"],
        )
        first_half = _route_segment_with_auto_split(start, middle, split_depth + 1)
        second_half = _route_segment_with_auto_split(middle, end, split_depth + 1)
        return _merge_route_segments(first_half, second_half)


def _build_waypoints(polyline: list[list[float]]) -> list[list[float]]:
    if not polyline:
        return []

    # Sample waypoints (every ~50th point for the map).
    step = max(1, len(polyline) // 50)
    waypoints = polyline[::step]
    if waypoints[-1] != polyline[-1]:
        return waypoints + [polyline[-1]]
    return waypoints


def _extract_ors_error(resp: requests.Response) -> tuple[str, int | None]:
    """Extract ORS error message/code from JSON payload when available."""
    fallback_message = resp.text[:200]

    try:
        payload = resp.json()
    except ValueError:
        return fallback_message, None

    if not isinstance(payload, dict):
        return fallback_message, None

    error_data = payload.get("error")
    if not isinstance(error_data, dict):
        return fallback_message, None

    message_raw = error_data.get("message")
    code_raw = error_data.get("code")

    ors_error_code = None
    if isinstance(code_raw, int):
        ors_error_code = code_raw
    elif isinstance(code_raw, str):
        try:
            ors_error_code = int(code_raw)
        except ValueError:
            ors_error_code = None

    if isinstance(message_raw, str) and message_raw.strip():
        return message_raw.strip(), ors_error_code

    return fallback_message, ors_error_code


def _get(url: str, params: dict) -> dict:
    """GET with 1 retry on 429 or 5xx."""
    api_key = settings.ORS_API_KEY
    if not api_key:
        raise ORSError("ORS_API_KEY is not configured.")

    headers = {"Authorization": api_key}
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
        except requests.RequestException as exc:
            raise ORSError(f"Network error: {exc}") from exc

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429 and attempt == 0:
            time.sleep(2)
            continue
        if resp.status_code >= 500 and attempt == 0:
            time.sleep(1)
            continue
        error_message, ors_error_code = _extract_ors_error(resp)
        raise ORSError(
            f"ORS returned {resp.status_code}: {error_message}",
            status_code=resp.status_code,
            ors_error_code=ors_error_code,
        )
    raise ORSError("ORS request failed after retries.")


def _post(url: str, body: dict) -> dict:
    """POST with 1 retry on 429 or 5xx."""
    api_key = settings.ORS_API_KEY
    if not api_key:
        raise ORSError("ORS_API_KEY is not configured.")

    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    for attempt in range(2):
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=15)
        except requests.RequestException as exc:
            raise ORSError(f"Network error: {exc}") from exc

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429 and attempt == 0:
            time.sleep(2)
            continue
        if resp.status_code >= 500 and attempt == 0:
            time.sleep(1)
            continue
        error_message, ors_error_code = _extract_ors_error(resp)
        raise ORSError(
            f"ORS returned {resp.status_code}: {error_message}",
            status_code=resp.status_code,
            ors_error_code=ors_error_code,
        )
    raise ORSError("ORS request failed after retries.")


def geocode(location: str) -> dict[str, Any]:
    """
    Convert a location string to lat/lng.
    Returns: {'lat': float, 'lng': float, 'display_name': str}
    """
    if location in _geocode_cache:
        return _geocode_cache[location]

    data = _get(
        f"{ORS_BASE}/geocode/search",
        {"api_key": settings.ORS_API_KEY, "text": location, "size": 1},
    )

    features = data.get("features", [])
    if not features:
        raise ORSError(f"No geocoding results for: {location!r}")

    coords = features[0]["geometry"]["coordinates"]  # [lng, lat]
    display = features[0]["properties"].get("label", location)
    result = {"lat": coords[1], "lng": coords[0], "display_name": display}
    _geocode_cache[location] = result
    return result


def get_route(
    origin: dict, pickup: dict, dropoff: dict
) -> dict[str, Any]:
    """
    Get a route between three points using ORS driving-hgv profile.

    Args:
        origin:  {'lat': float, 'lng': float}
        pickup:  {'lat': float, 'lng': float}
        dropoff: {'lat': float, 'lng': float}

    Returns:
        {
            'total_miles': float,
            'duration_hours': float,
            'waypoints': [{'lat': float, 'lng': float}, ...],
            'polyline': [[lat, lng], ...],
        }
    """
    first_leg = _route_segment_with_auto_split(origin, pickup)
    second_leg = _route_segment_with_auto_split(pickup, dropoff)
    merged_route = _merge_route_segments(first_leg, second_leg)
    total_meters = merged_route["total_meters"]
    total_seconds = merged_route["total_seconds"]

    # Convert: meters → miles, seconds → hours
    total_miles = total_meters * 0.000621371
    duration_hours = total_seconds / 3600.0

    # GeoJSON geometry: coordinates are [lng, lat] pairs
    polyline = merged_route["polyline"]
    waypoints = _build_waypoints(polyline)

    return {
        "total_miles": round(total_miles, 1),
        "duration_hours": round(duration_hours, 2),
        "waypoints": waypoints,
        "polyline": polyline,
    }
