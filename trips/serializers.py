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
