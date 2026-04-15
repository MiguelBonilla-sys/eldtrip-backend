from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/trips/", include("trips.urls")),
    # OpenAPI schema + UI — always active for interactive Swagger input.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Catch-all: serve React's index.html for all non-API routes
    re_path(r"^(?!api/|admin/).*$", TemplateView.as_view(template_name="index.html")),
]
