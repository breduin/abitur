from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("api/refresh/", views.refresh_data_view, name="refresh_data"),
    path("api/refresh/status/", views.refresh_status_partial, name="refresh_status"),
]
