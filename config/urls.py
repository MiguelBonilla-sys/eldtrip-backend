from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from importlib import import_module

try:
    spectacular_views = import_module("drf_spectacular.views")
    SpectacularAPIView = spectacular_views.SpectacularAPIView
    SpectacularRedocView = spectacular_views.SpectacularRedocView
    SpectacularSwaggerView = spectacular_views.SpectacularSwaggerView
except ModuleNotFoundError:
    SpectacularAPIView = None
    SpectacularRedocView = None
    SpectacularSwaggerView = None

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/trips/", include("trips.urls")),
    # Catch-all: serve React's index.html for all non-API routes
    re_path(r"^(?!api/|admin/).*$", TemplateView.as_view(template_name="index.html")),
]

if SpectacularAPIView and SpectacularSwaggerView and SpectacularRedocView:
    # OpenAPI schema + UI — only available when drf-spectacular is installed.
    urlpatterns.extend(
        [
            path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
            path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
            path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
        ]
    )
