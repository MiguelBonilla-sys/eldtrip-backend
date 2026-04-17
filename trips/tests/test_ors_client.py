from unittest.mock import patch

import pytest
from django.test import override_settings

from trips.ors_client import ORSError, _extract_ors_error, _post, get_route


class _DummyResponse:
    def __init__(
        self,
        status_code: int,
        text: str,
        json_data: object = None,
        json_raises: bool = False,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._json_data = json_data
        self._json_raises = json_raises

    def json(self):
        if self._json_raises:
            raise ValueError("Invalid JSON")
        return self._json_data


def test_extract_ors_error_reads_code_and_message() -> None:
    response = _DummyResponse(
        status_code=400,
        text="raw fallback",
        json_data={
            "error": {
                "code": 2004,
                "message": "Request parameters exceed the server configuration limits.",
            }
        },
    )

    message, error_code = _extract_ors_error(response)

    assert message == "Request parameters exceed the server configuration limits."
    assert error_code == 2004


def test_extract_ors_error_falls_back_on_invalid_json() -> None:
    response = _DummyResponse(
        status_code=400,
        text="plain-text-error",
        json_raises=True,
    )

    message, error_code = _extract_ors_error(response)

    assert message == "plain-text-error"
    assert error_code is None


@override_settings(ORS_API_KEY="test-api-key")
@patch("trips.ors_client.requests.post")
def test_post_raises_orserror_with_parsed_ors_code(mock_post) -> None:
    mock_post.return_value = _DummyResponse(
        status_code=400,
        text='{"error":{"code":2004,"message":"Too long"}}',
        json_data={"error": {"code": "2004", "message": "Too long"}},
    )

    with pytest.raises(ORSError) as exc_info:
        _post("https://example.com", {"coordinates": []})

    assert exc_info.value.status_code == 400
    assert exc_info.value.ors_error_code == 2004
    assert str(exc_info.value) == "ORS returned 400: Too long"


def _route_response(distance: float, duration: float, coordinates: list[list[float]]) -> dict:
    return {
        "features": [
            {
                "properties": {
                    "summary": {
                        "distance": distance,
                        "duration": duration,
                    }
                },
                "geometry": {"coordinates": coordinates},
            }
        ]
    }


@override_settings(ORS_API_KEY="test-api-key")
@patch("trips.ors_client._post")
def test_get_route_splits_long_segment_automatically(mock_post) -> None:
    mock_post.side_effect = [
        ORSError("Too long", status_code=400, ors_error_code=2004),
        _route_response(1000.0, 100.0, [[0.0, 0.0], [0.5, 0.0]]),
        _route_response(1200.0, 120.0, [[0.5, 0.0], [1.0, 0.0]]),
        _route_response(2000.0, 200.0, [[1.0, 0.0], [2.0, 0.0]]),
    ]

    result = get_route(
        origin={"lat": 0.0, "lng": 0.0},
        pickup={"lat": 0.0, "lng": 1.0},
        dropoff={"lat": 0.0, "lng": 2.0},
    )

    assert mock_post.call_count == 4
    assert result["total_miles"] == 2.6
    assert result["duration_hours"] == 0.12
    assert result["polyline"] == [
        [0.0, 0.0],
        [0.0, 0.5],
        [0.0, 1.0],
        [0.0, 2.0],
    ]
    assert result["waypoints"] == result["polyline"]


@override_settings(ORS_API_KEY="test-api-key")
@patch("trips.ors_client._post")
def test_get_route_raises_after_split_depth_limit(mock_post, monkeypatch) -> None:
    monkeypatch.setattr("trips.ors_client.MAX_ROUTE_SPLIT_DEPTH", 1)
    mock_post.side_effect = ORSError(
        "Still too long",
        status_code=400,
        ors_error_code=2004,
    )

    with pytest.raises(ORSError) as exc_info:
        get_route(
            origin={"lat": 0.0, "lng": 0.0},
            pickup={"lat": 0.0, "lng": 1.0},
            dropoff={"lat": 0.0, "lng": 2.0},
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.ors_error_code == 2004
