from django.urls import path

from listings import views

urlpatterns = [
    path("listings/search/", views.listing_search, name="listing_search"),
    path("listings/", views.listing_index, name="listing_index"),
    path("listings/new/", views.listing_create, name="listing_create"),
    path(
        "listings/<int:listing_id>/",
        views.listing_detail,
        name="listing_detail",
    ),
    path(
        "listings/<int:listing_id>/edit/",
        views.listing_edit,
        name="listing_edit",
    ),
    path(
        "listings/<int:listing_id>/actions/",
        views.listing_transition,
        name="listing_transition",
    ),
]
