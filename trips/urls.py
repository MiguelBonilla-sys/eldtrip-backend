from django.urls import path

from .views import HealthCheckView, LocationSearchView, TripPlanView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("locations/", LocationSearchView.as_view(), name="location-search"),
    path("plan/", TripPlanView.as_view(), name="trip-plan"),
]
