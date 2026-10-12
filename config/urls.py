from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


def home(request):
    return HttpResponse("<html><body><h1>SkillSwap</h1></body></html>")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("profiles.urls")),
    path("", include("listings.urls")),
    path("", home, name="home"),
]
