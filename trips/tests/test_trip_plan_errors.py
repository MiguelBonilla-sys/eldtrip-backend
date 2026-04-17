import json
from unittest.mock import patch

from django.test import Client

from trips.ors_client import ORSError


ROUTE_DISTANCE_LIMIT_MESSAGE = (
    "Route too long for a single request (ORS max 6000 km). "
    "Split the trip into smaller legs."
)


def _client() -> Client:
    return Client(HTTP_HOST="localhost")


def _payload() -> dict:
    return {
        "current_location": "Chicago, IL",
        "pickup_location": "Detroit, MI",
        "dropoff_location": "Nashville, TN",
        "current_cycle_used": 20,
    }


def _geo(display_name: str) -> dict:
    return {"lat": 41.0, "lng": -87.0, "display_name": display_name}


def test_trip_plan_returns_400_for_ors_distance_limit_code_2004() -> None:
    with patch(
        "trips.views.geocode",
        side_effect=[
            _geo("Chicago, Illinois, USA"),
            _geo("Detroit, Michigan, USA"),
            _geo("Nashville, Tennessee, USA"),
        ],
    ), patch(
        "trips.views.get_route",
        side_effect=ORSError(
            "ORS returned 400: route too long",
            status_code=400,
            ors_error_code=2004,
        ),
    ):
        response = _client().post(
            "/api/trips/plan/",
            data=json.dumps(_payload()),
            content_type="application/json",
        )

    assert response.status_code == 400
    assert response.json() == {"error": ROUTE_DISTANCE_LIMIT_MESSAGE}


def test_trip_plan_keeps_502_for_other_ors_routing_errors() -> None:
    with patch(
        "trips.views.geocode",
        side_effect=[
            _geo("Chicago, Illinois, USA"),
            _geo("Detroit, Michigan, USA"),
            _geo("Nashville, Tennessee, USA"),
        ],
    ), patch(
        "trips.views.get_route",
        side_effect=ORSError("Upstream routing outage", status_code=503),
    ):
        response = _client().post(
            "/api/trips/plan/",
            data=json.dumps(_payload()),
            content_type="application/json",
        )

    assert response.status_code == 502
    assert response.json()["error"].startswith("Routing failed:")


def test_trip_plan_keeps_502_for_non_2004_routing_bad_request() -> None:
    with patch(
        "trips.views.geocode",
        side_effect=[
            _geo("Chicago, Illinois, USA"),
            _geo("Detroit, Michigan, USA"),
            _geo("Nashville, Tennessee, USA"),
        ],
    ), patch(
        "trips.views.get_route",
        side_effect=ORSError(
            "Some other ORS bad request",
            status_code=400,
            ors_error_code=9999,
        ),
    ):
        response = _client().post(
            "/api/trips/plan/",
            data=json.dumps(_payload()),
            content_type="application/json",
        )

    assert response.status_code == 502
    assert response.json()["error"].startswith("Routing failed:")


def test_trip_plan_keeps_502_for_geocoding_ors_errors() -> None:
    with patch(
        "trips.views.geocode",
        side_effect=ORSError("No geocoding results", status_code=503),
    ):
        response = _client().post(
            "/api/trips/plan/",
            data=json.dumps(_payload()),
            content_type="application/json",
        )

    assert response.status_code == 502
    assert response.json()["error"].startswith("Location lookup failed:")
