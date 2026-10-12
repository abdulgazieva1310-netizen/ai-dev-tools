from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path

from listings.recommendations import recommend_listings


def home(request):
    recommendations = recommend_listings(request.user, [], limit=5)
    return render(request, "home.html", {"recommendations": recommendations})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("profiles.urls")),
    path("", include("listings.urls")),
    path("", home, name="home"),
]
