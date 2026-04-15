from django.urls import path

from .views import TripPlanView

urlpatterns = [
    path("plan/", TripPlanView.as_view(), name="trip-plan"),
]
