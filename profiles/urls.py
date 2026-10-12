from django.urls import path

from profiles import views

urlpatterns = [
    path("profile/new/", views.profile_create, name="profile_create"),
    path(
        "profiles/<int:profile_id>/",
        views.profile_detail,
        name="profile_detail",
    ),
    path(
        "profiles/<int:profile_id>/edit/",
        views.profile_edit,
        name="profile_edit",
    ),
    path(
        "profiles/<int:profile_id>/delete/",
        views.profile_delete,
        name="profile_delete",
    ),
    path(
        "profiles/<int:profile_id>/projects/new/",
        views.project_create,
        name="project_create",
    ),
    path(
        "profiles/<int:profile_id>/projects/<int:entry_id>/edit/",
        views.project_edit,
        name="project_edit",
    ),
    path(
        "profiles/<int:profile_id>/projects/<int:entry_id>/delete/",
        views.project_delete,
        name="project_delete",
    ),
    path(
        "profiles/<int:profile_id>/certificates/new/",
        views.certificate_create,
        name="certificate_create",
    ),
    path(
        "profiles/<int:profile_id>/certificates/<int:entry_id>/edit/",
        views.certificate_edit,
        name="certificate_edit",
    ),
    path(
        "profiles/<int:profile_id>/certificates/<int:entry_id>/delete/",
        views.certificate_delete,
        name="certificate_delete",
    ),
    path(
        "profiles/<int:profile_id>/skills/new/",
        views.skill_create,
        name="skill_create",
    ),
    path(
        "profiles/<int:profile_id>/skills/<int:entry_id>/edit/",
        views.skill_edit,
        name="skill_edit",
    ),
    path(
        "profiles/<int:profile_id>/skills/<int:entry_id>/delete/",
        views.skill_delete,
        name="skill_delete",
    ),
]
