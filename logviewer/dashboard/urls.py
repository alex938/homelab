from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("service/<slug:slug>/", views.service_detail, name="service_detail"),
    path("refresh/", views.trigger_refresh, name="refresh"),
    path("api/state/", views.state, name="state"),
    path("healthz/", views.healthz, name="healthz"),
]
