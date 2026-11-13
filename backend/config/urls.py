from django.urls import include, path

from packs import share_views, web_views

urlpatterns = [
    path("", web_views.index),
    path("app/<str:name>", web_views.asset),
    path("s/<str:token>", share_views.shared_page),
    path("v1/", include("packs.urls")),
]
