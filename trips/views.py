import logging

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .hos_calculator import HOSTripCalculator
from .ors_client import ORSError, geocode, get_route
from .serializers import (
    ErrorResponseSerializer,
    HealthResponseSerializer,
    TripPlanResponseSerializer,
    TripRequestSerializer,
    ValidationErrorResponseSerializer,
)

logger = logging.getLogger(__name__)


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
                response=ValidationErrorResponseSerializer,
                description="Validation error in request payload.",
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
