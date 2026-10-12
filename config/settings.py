"""Minimal settings for the SkillSwap project scaffold."""

import os

SECRET_KEY = "development-only-key"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

ROOT_URLCONF = "config.urls"
STATIC_URL = "static/"
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "profiles",
    "listings",
    "mozilla_django_oidc",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "accounts.oidc.GoogleOIDCBackend",
]
GOOGLE_OIDC_CLIENT_ID = os.environ.get("GOOGLE_OIDC_CLIENT_ID", "")
GOOGLE_OIDC_CLIENT_SECRET = os.environ.get("GOOGLE_OIDC_CLIENT_SECRET", "")
GOOGLE_OIDC_CALLBACK_URL = os.environ.get("GOOGLE_OIDC_CALLBACK_URL", "")
OIDC_RP_CLIENT_ID = GOOGLE_OIDC_CLIENT_ID
OIDC_RP_CLIENT_SECRET = GOOGLE_OIDC_CLIENT_SECRET
OIDC_AUTHENTICATION_CALLBACK_URL = "oidc_callback"
OIDC_OP_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
OIDC_OP_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
OIDC_OP_USER_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
OIDC_OP_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
OIDC_OP_ISSUER = "https://accounts.google.com"
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_USE_NONCE = True
OIDC_USE_PKCE = True
OIDC_STATE_TIMEOUT = 600
OIDC_STORE_ACCESS_TOKEN = False
OIDC_STORE_ID_TOKEN = False
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@skillswap.local")
EMAIL_VERIFICATION_TIMEOUT = int(os.environ.get("EMAIL_VERIFICATION_TIMEOUT", "86400"))
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": ".".join(
            (
                "django.contrib.auth.password_validation",
                "UserAttributeSimilarityValidator",
            )
        )
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

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
else:
    DATABASES = {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}
    }
