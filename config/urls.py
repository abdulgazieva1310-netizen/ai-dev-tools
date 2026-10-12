from django.http import HttpResponse
from django.urls import include, path


def home(request):
    return HttpResponse("<html><body><h1>SkillSwap</h1></body></html>")


urlpatterns = [
    path("", include("accounts.urls")),
    path("", home, name="home"),
]
