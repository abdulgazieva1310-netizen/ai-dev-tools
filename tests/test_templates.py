import json

import pytest
from django.conf import settings
from django.template import Context, Template
from django.test import override_settings
from django.urls import reverse


def render(source, **context):
    template = Template("{% load vite_assets %}" + source)
    return template.render(Context(context))


@pytest.mark.django_db
def test_base_shell_has_semantic_landmarks_and_responsive_viewport(client):
    response = client.get(reverse("home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "<!doctype html>" in content
    assert '<html lang="en">' in content
    assert 'name="viewport"' in content
    assert "width=device-width" in content
    assert "<header" in content
    assert "<nav" in content
    assert 'aria-label="Primary"' in content
    assert "<main" in content
    assert "{%" not in content


def test_base_template_exposes_asset_and_content_blocks():
    content = (settings.BASE_DIR / "templates" / "base.html").read_text(
        encoding="utf-8"
    )

    assert "{% block title %}" in content
    assert "{% block head_assets %}" in content
    assert "{% block body_assets %}" in content
    assert "{% block content %}" in content
    assert "{% vite_asset" in content


def test_only_base_template_declares_a_doctype():
    template_dirs = [
        settings.BASE_DIR / "templates",
        settings.BASE_DIR / "accounts" / "templates",
        settings.BASE_DIR / "profiles" / "templates",
        settings.BASE_DIR / "listings" / "templates",
    ]
    offenders = []
    for directory in template_dirs:
        for path in directory.rglob("*.html"):
            if path.name == "base.html":
                continue
            if "<!doctype" in path.read_text(encoding="utf-8").lower():
                offenders.append(path)

    assert offenders == []


def test_alert_partial_renders_with_alert_role():
    html = render(
        '{% include "partials/alert.html" with message="Something went wrong" %}'
    )

    assert 'role="alert"' in html
    assert "Something went wrong" in html


def test_form_field_partial_renders_label_widget_and_help_text():
    from accounts.forms import RegistrationForm

    form = RegistrationForm()
    html = render(
        '{% include "partials/form_field.html" with field=field %}',
        field=form["email"],
    )

    assert "<label" in html
    assert 'for="id_email"' in html
    assert 'name="email"' in html


def test_button_partial_renders_a_submit_button_by_default():
    html = render('{% include "partials/button.html" with label="Sign in" %}')

    assert html.startswith("<button")
    assert 'type="submit"' in html
    assert "Sign in" in html


def test_button_partial_honours_name_and_value():
    html = render(
        '{% include "partials/button.html" with label="Save" name="action" value="save" %}'  # noqa: E501
    )

    assert 'name="action"' in html
    assert 'value="save"' in html


def _write_manifest(static_dir, manifest):
    manifest_dir = static_dir / "build" / ".vite"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


MANIFEST = {
    "frontend/main.js": {
        "file": "assets/main-abc123.js",
        "name": "main",
        "src": "frontend/main.js",
        "isEntry": True,
        "css": ["assets/main-def456.css"],
    }
}


def test_vite_asset_resolves_hashed_assets_from_the_manifest(tmp_path):
    _write_manifest(tmp_path, MANIFEST)

    with override_settings(STATICFILES_DIRS=[tmp_path], VITE_DEV_SERVER_URL=""):
        by_name = render('{% vite_asset "main" %}')
        by_path = render('{% vite_asset "frontend/main.js" %}')

    for html in (by_name, by_path):
        assert 'href="/static/assets/main-def456.css"' in html
        assert 'src="/static/assets/main-abc123.js"' in html
        assert html.index("<link") < html.index("<script")


def test_vite_asset_uses_the_dev_server_when_configured():
    with override_settings(VITE_DEV_SERVER_URL="http://localhost:5173"):
        html = render('{% vite_asset "main" %}')

    assert "http://localhost:5173/@vite/client" in html
    assert "http://localhost:5173/frontend/main.js" in html


def test_vite_asset_renders_nothing_without_a_manifest_or_dev_server(tmp_path):
    with override_settings(STATICFILES_DIRS=[tmp_path], VITE_DEV_SERVER_URL=""):
        html = render('{% vite_asset "main" %}')

    assert html.strip() == ""
    assert "<link" not in html
    assert "<script" not in html


@pytest.mark.django_db
def test_pages_still_render_without_a_built_bundle(client, tmp_path):
    with override_settings(STATICFILES_DIRS=[tmp_path], VITE_DEV_SERVER_URL=""):
        for url in (reverse("home"), reverse("login"), reverse("register")):
            response = client.get(url)

            assert response.status_code == 200
            assert b'aria-label="Primary"' in response.content
            assert b'<link rel="stylesheet"' not in response.content
            assert b'<script type="module"' not in response.content

    assert b'<form method="post"' in client.get(reverse("login")).content


@pytest.mark.django_db
def test_pages_render_the_built_assets_when_a_manifest_exists(client, tmp_path):
    _write_manifest(tmp_path, MANIFEST)

    with override_settings(STATICFILES_DIRS=[tmp_path], VITE_DEV_SERVER_URL=""):
        response = client.get(reverse("home"))

    assert response.status_code == 200
    assert b"/static/assets/main-def456.css" in response.content
    assert b"/static/assets/main-abc123.js" in response.content


@pytest.mark.django_db
def test_navigation_and_forms_work_without_javascript(client):
    home = client.get(reverse("home")).content.decode()
    login = client.get(reverse("login")).content.decode()

    assert '<a href="/listings/"' in home
    assert ">Live lessons</a>" in home
    assert '<a href="/listings/search/"' in home
    assert ">Search lessons</a>" in home
    assert "<main" in home
    assert '<form method="post"' in login
    assert '<button type="submit"' in login
    assert "csrfmiddlewaretoken" in login


def test_base_and_page_templates_use_responsive_breakpoints():
    base = (settings.BASE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    home = (settings.BASE_DIR / "templates" / "home.html").read_text(encoding="utf-8")

    assert "sm:" in base
    assert "md:" in base
    assert "md:grid-cols-2" in home
