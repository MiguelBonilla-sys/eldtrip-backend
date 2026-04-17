import logging
import json
from functools import lru_cache
from pathlib import Path

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .hos_calculator import HOSTripCalculator
from .ors_client import ORSError, geocode, get_route
from .serializers import (
    ErrorResponseSerializer,
    HealthResponseSerializer,
    LocationSearchResponseSerializer,
    TripPlanResponseSerializer,
    TripRequestSerializer,
)

logger = logging.getLogger(__name__)

LOCATIONS_DATASET_PATH = Path(__file__).resolve().parent / "data" / "locations_us.json"
DEFAULT_LOCATION_LIMIT = 12
MAX_LOCATION_LIMIT = 25
ORS_ROUTE_DISTANCE_LIMIT_CODE = 2004
ORS_ROUTE_DISTANCE_LIMIT_MESSAGE = (
    "Route too long for a single request (ORS max 6000 km). "
    "Split the trip into smaller legs."
)

STATE_CODE_TO_NAME = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}
STATE_NAME_TO_CODE = {name.lower(): code for code, name in STATE_CODE_TO_NAME.items()}


def _is_ors_route_distance_limit_error(exc: ORSError) -> bool:
    return (
        exc.status_code == status.HTTP_400_BAD_REQUEST
        and exc.ors_error_code == ORS_ROUTE_DISTANCE_LIMIT_CODE
    )


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def _load_locations() -> list[dict]:
    with LOCATIONS_DATASET_PATH.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("locations_us.json must contain an array.")

    normalized_locations: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue

        state = str(entry.get("state", "")).strip()
        state_code = STATE_NAME_TO_CODE.get(state.lower(), "")
        normalized_locations.append(
            {
                "city": str(entry.get("city", "")).strip(),
                "state": state,
                "state_code": state_code,
                "label": str(entry.get("label", "")).strip(),
                "population": _to_int(entry.get("population", 0)),
                "lat": entry.get("lat"),
                "lng": entry.get("lng"),
            }
        )

    return normalized_locations


def _normalize_query(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _query_variants(query: str) -> list[str]:
    variants = {query}
    tokens = query.replace(",", " ").split()

    for token in tokens:
        token_code = token.upper()
        full_state = STATE_CODE_TO_NAME.get(token_code)
        if not full_state:
            continue
        variants.add(query.replace(token.lower(), full_state.lower()))

    if len(query) == 2 and query.upper() in STATE_CODE_TO_NAME:
        variants.add(STATE_CODE_TO_NAME[query.upper()].lower())

    return [variant for variant in variants if variant]


def _score_location(entry: dict, query: str) -> int | None:
    city = str(entry.get("city", "")).lower()
    state = str(entry.get("state", "")).lower()
    state_code = str(entry.get("state_code", "")).lower()
    label = str(entry.get("label", "")).lower()

    if city.startswith(query):
        return 0
    if label.startswith(query):
        return 1
    if state_code == query:
        return 2
    if any(token.startswith(query) for token in label.split()):
        return 3
    if query in city:
        return 4
    if query in state_code:
        return 5
    if query in state:
        return 6
    if query in label:
        return 7
    return None


class HealthCheckView(APIView):
    """GET /api/health/ - Simple health check endpoint for deployment verification."""

    @extend_schema(
        tags=["health"],
        summary="Health check",
        responses={200: HealthResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class TripPlanView(APIView):
    """
    POST /api/trips/plan/

    Accepts trip parameters, calls ORS for routing, runs HOS calculator,
    and returns the full itinerary with log sheets.
    """

    @extend_schema(
        tags=["trips"],
        summary="Plan a trip with FMCSA HOS",
        request=TripRequestSerializer,
        responses={
            200: OpenApiResponse(response=TripPlanResponseSerializer),
            400: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description=(
                    "Validation error in request payload or unsupported route distance. "
                    "May return field-level validation details or an {'error': '...'} message."
                ),
            ),
            502: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Upstream ORS geocoding/routing failure.",
            ),
            500: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Unexpected internal trip calculation failure.",
            ),
        },
        examples=[
            OpenApiExample(
                "Trip request",
                value={
                    "current_location": "Chicago, IL",
                    "pickup_location": "Detroit, MI",
                    "dropoff_location": "Nashville, TN",
                    "current_cycle_used": 20,
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        serializer = TripRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        current_cycle_used: float = data["current_cycle_used"]

        # --- Geocode all three locations ---
        try:
            origin = geocode(data["current_location"])
            pickup = geocode(data["pickup_location"])
            dropoff = geocode(data["dropoff_location"])
        except ORSError as exc:
            logger.error("Geocoding failed: %s", exc)
            return Response(
                {"error": f"Location lookup failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # --- Get route ---
        try:
            route = get_route(origin, pickup, dropoff)
        except ORSError as exc:
            if _is_ors_route_distance_limit_error(exc):
                logger.warning("Route exceeds ORS distance limit: %s", exc)
                return Response(
                    {"error": ORS_ROUTE_DISTANCE_LIMIT_MESSAGE},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            logger.error("Routing failed: %s", exc)
            return Response(
                {"error": f"Routing failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # --- Calculate HOS itinerary ---
        try:
            calc = HOSTripCalculator(
                total_miles=route["total_miles"],
                current_cycle_used=current_cycle_used,
            )
            trip_plan = calc.plan_trip()
        except Exception as exc:
            logger.exception("HOS calculation failed")
            return Response(
                {"error": f"Trip calculation failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # --- Enrich stops with location context ---
        stops = trip_plan["stops"]
        if stops:
            stops[0]["location"] = origin["display_name"]
            stops[0]["pickup_name"] = pickup["display_name"]
            stops[-1]["location"] = dropoff["display_name"]

        return Response(
            {
                "route": {
                    "total_miles": route["total_miles"],
                    "duration_hours": route["duration_hours"],
                    "waypoints": route["waypoints"],
                    "polyline": route["polyline"],
                    "origin": origin,
                    "pickup": pickup,
                    "dropoff": dropoff,
                },
                "stops": stops,
                "log_sheets": trip_plan["log_sheets"],
                "total_days": trip_plan["total_days"],
            },
            status=status.HTTP_200_OK,
        )


class LocationSearchView(APIView):
    """GET /api/trips/locations/ - Search location suggestions from local JSON dataset."""

    @extend_schema(
        tags=["trips"],
        summary="Search location suggestions",
        parameters=[
            OpenApiParameter(
                name="q",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search text for city or state.",
                type=str,
            ),
            OpenApiParameter(
                name="limit",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Max results (1-25). Default is 12.",
                type=int,
            ),
        ],
        responses={
            200: OpenApiResponse(response=LocationSearchResponseSerializer),
            503: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Location dataset is unavailable.",
            ),
        },
        examples=[
            OpenApiExample(
                "Location search",
                value={
                    "query": "chi",
                    "count": 2,
                    "results": [
                        {
                            "city": "Chicago",
                            "state": "Illinois",
                            "state_code": "IL",
                            "label": "Chicago, Illinois",
                            "population": 2718782,
                            "lat": 41.8781136,
                            "lng": -87.6297982,
                        },
                        {
                            "city": "Chico",
                            "state": "California",
                            "state_code": "CA",
                            "label": "Chico, California",
                            "population": 86187,
                            "lat": 39.7284944,
                            "lng": -121.8374777,
                        },
                    ],
                },
                response_only=True,
                status_codes=["200"],
            )
        ],
    )
    def get(self, request: Request) -> Response:
        query = _normalize_query(request.query_params.get("q", ""))
        query_variants = _query_variants(query)

        try:
            limit = int(request.query_params.get("limit", DEFAULT_LOCATION_LIMIT))
        except (TypeError, ValueError):
            limit = DEFAULT_LOCATION_LIMIT
        limit = max(1, min(limit, MAX_LOCATION_LIMIT))

        try:
            locations = _load_locations()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.exception("Failed to load locations dataset: %s", exc)
            return Response(
                {"error": "Location suggestions are temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not query:
            results = locations[:limit]
            return Response(
                {"query": query, "count": len(results), "results": results},
                status=status.HTTP_200_OK,
            )

        ranked_matches: list[tuple[int, int, str, dict]] = []
        for entry in locations:
            scores = [
                _score_location(entry, variant)
                for variant in query_variants
            ]
            scores = [score for score in scores if score is not None]
            if not scores:
                continue

            population = _to_int(entry.get("population", 0))
            label = str(entry.get("label", ""))
            ranked_matches.append((min(scores), -population, label, entry))

        ranked_matches.sort(key=lambda item: (item[0], item[1], item[2]))
        results = [item[3] for item in ranked_matches[:limit]]

        return Response(
            {"query": query, "count": len(results), "results": results},
            status=status.HTTP_200_OK,
        )
