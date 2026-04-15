from django.test import Client


def _client() -> Client:
    return Client(HTTP_HOST="localhost")


def test_location_search_with_state_abbreviation() -> None:
    response = _client().get(
        "/api/trips/locations/",
        {"q": "nashville, tn", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    labels = [item["label"].lower() for item in payload["results"]]
    assert any("nashville" in label and "tennessee" in label for label in labels)


def test_location_search_clamps_limit() -> None:
    response = _client().get(
        "/api/trips/locations/",
        {"q": "a", "limit": 999},
    )

    assert response.status_code == 200
    assert response.json()["count"] <= 25


def test_location_search_default_results_for_empty_query() -> None:
    response = _client().get("/api/trips/locations/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == ""
    assert payload["count"] == 12


def test_location_search_result_contains_state_code() -> None:
    response = _client().get(
        "/api/trips/locations/",
        {"q": "chicago", "limit": 1},
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["state_code"] == "IL"
