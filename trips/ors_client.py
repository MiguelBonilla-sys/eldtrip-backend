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
    coordinates = [
        [origin["lng"], origin["lat"]],
        [pickup["lng"], pickup["lat"]],
        [dropoff["lng"], dropoff["lat"]],
    ]

    data = _post(
        f"{ORS_BASE}/v2/directions/driving-hgv/geojson",
        {"coordinates": coordinates},
    )

    features = data.get("features", [])
    if not features:
        raise ORSError("ORS directions returned no route.")

    props = features[0]["properties"]
    summary = props["summary"]
    total_meters = summary["distance"]
    total_seconds = summary["duration"]

    # Convert: meters → miles, seconds → hours
    total_miles = total_meters * 0.000621371
    duration_hours = total_seconds / 3600.0

    # GeoJSON geometry: coordinates are [lng, lat] pairs
    geom_coords = features[0]["geometry"]["coordinates"]
    polyline = [[c[1], c[0]] for c in geom_coords]  # flip to [lat, lng]

    # Sample waypoints (every ~50th point for the map)
    step = max(1, len(polyline) // 50)
    waypoints = polyline[::step]
    if polyline and waypoints[-1] != polyline[-1]:
        waypoints.append(polyline[-1])

    return {
        "total_miles": round(total_miles, 1),
        "duration_hours": round(duration_hours, 2),
        "waypoints": waypoints,
        "polyline": polyline,
    }
