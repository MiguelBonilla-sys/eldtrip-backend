from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    current_location = serializers.CharField(max_length=200)
    pickup_location = serializers.CharField(max_length=200)
    dropoff_location = serializers.CharField(max_length=200)
    current_cycle_used = serializers.FloatField(min_value=0.0, max_value=70.0)

    def validate_current_location(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Current location cannot be blank.")
        return value.strip()

    def validate_pickup_location(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Pickup location cannot be blank.")
        return value.strip()

    def validate_dropoff_location(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Dropoff location cannot be blank.")
        return value.strip()


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField()


class ValidationErrorResponseSerializer(serializers.Serializer):
    current_location = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    pickup_location = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    dropoff_location = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    current_cycle_used = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    non_field_errors = serializers.ListField(
        child=serializers.CharField(), required=False
    )


class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    display_name = serializers.CharField()


class RouteResponseSerializer(serializers.Serializer):
    total_miles = serializers.FloatField()
    duration_hours = serializers.FloatField()
    waypoints = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField())
    )
    polyline = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField())
    )
    origin = LocationSerializer()
    pickup = LocationSerializer()
    dropoff = LocationSerializer()


class StopSerializer(serializers.Serializer):
    type = serializers.CharField()
    duration_hours = serializers.FloatField(required=False)
    notes = serializers.CharField(required=False)
    location = serializers.CharField(required=False)
    pickup_name = serializers.CharField(required=False)


class LogSegmentSerializer(serializers.Serializer):
    status = serializers.CharField()
    start = serializers.CharField()
    end = serializers.CharField()
    notes = serializers.CharField(required=False)


class LogTotalsSerializer(serializers.Serializer):
    off_duty = serializers.FloatField()
    sleeper = serializers.FloatField()
    driving = serializers.FloatField()
    on_duty = serializers.FloatField()


class LogSheetSerializer(serializers.Serializer):
    date = serializers.CharField()
    driver_start_time = serializers.CharField(required=False)
    segments = LogSegmentSerializer(many=True)
    totals = LogTotalsSerializer()
    miles_today = serializers.FloatField()


class TripPlanResponseSerializer(serializers.Serializer):
    route = RouteResponseSerializer()
    stops = StopSerializer(many=True)
    log_sheets = LogSheetSerializer(many=True)
    total_days = serializers.IntegerField()


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField()


class LocationOptionSerializer(serializers.Serializer):
    city = serializers.CharField()
    state = serializers.CharField()
    state_code = serializers.CharField(allow_blank=True)
    label = serializers.CharField()
    population = serializers.IntegerField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class LocationSearchResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    count = serializers.IntegerField()
    results = LocationOptionSerializer(many=True)
