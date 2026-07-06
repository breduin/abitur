from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("sync/", views.sync_status_view, name="sync_status"),
    path("analytics/", views.analytics_view, name="analytics"),
    path("api/refresh/", views.refresh_data_view, name="refresh_data"),
    path("api/refresh/status/", views.refresh_status_partial, name="refresh_status"),
]
