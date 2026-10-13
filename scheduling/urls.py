from django.urls import path

from scheduling import views

urlpatterns = [
    path("availability/", views.availability, name="availability"),
    path(
        "availability/rules/new/",
        views.availability_rule_create,
        name="availability_rule_create",
    ),
    path(
        "availability/rules/<int:rule_id>/edit/",
        views.availability_rule_edit,
        name="availability_rule_edit",
    ),
    path(
        "availability/rules/<int:rule_id>/delete/",
        views.availability_rule_delete,
        name="availability_rule_delete",
    ),
    path(
        "availability/exceptions/new/",
        views.availability_exception_create,
        name="availability_exception_create",
    ),
    path(
        "availability/exceptions/<int:exception_id>/edit/",
        views.availability_exception_edit,
        name="availability_exception_edit",
    ),
    path(
        "availability/exceptions/<int:exception_id>/delete/",
        views.availability_exception_delete,
        name="availability_exception_delete",
    ),
    path(
        "listings/<int:listing_id>/book/",
        views.booking_create,
        name="booking_create",
    ),
    path("bookings/", views.booking_list, name="booking_list"),
    path(
        "bookings/<int:booking_id>/",
        views.booking_detail,
        name="booking_detail",
    ),
    path(
        "bookings/<int:booking_id>/meeting-link/",
        views.booking_meeting_link,
        name="booking_meeting_link",
    ),
]
