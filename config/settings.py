"""Minimal settings for the SkillSwap project scaffold."""

import os

SECRET_KEY = "development-only-key"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

ROOT_URLCONF = "config.urls"
INSTALLED_APPS = []
MIDDLEWARE = []
TEMPLATES = []

if os.environ.get("DB_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "skillswap"),
            "USER": os.environ.get("DB_USER", "skillswap"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "skillswap"),
            "HOST": os.environ["DB_HOST"],
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
