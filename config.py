import os
from datetime import timedelta


class BaseConfig:
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    WTF_CSRF_TIME_LIMIT = 8 * 60 * 60
    WTF_CSRF_CHECK_DEFAULT = False
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_HEADERS_ENABLED = True


class DevelopmentConfig(BaseConfig):
    DEBUG = os.environ.get("FLASK_DEBUG") == "1"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False


class ProductionConfig(BaseConfig):
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"


def load_security_config(app):
    environment = os.environ.get(
        "APP_ENV", os.environ.get("FLASK_ENV", "development")
    ).strip().lower()
    production = environment == "production"
    app.config.from_object(ProductionConfig if production else DevelopmentConfig)

    secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if production and not secret_key:
        raise RuntimeError("FLASK_SECRET_KEY is required in production.")
    if not secret_key:
        secret_key = "development-only-change-this-secret"
        app.logger.warning(
            "FLASK_SECRET_KEY is missing; using development-only fallback."
        )
    app.config["SECRET_KEY"] = secret_key
    app.config["APP_ENV"] = environment

    if production and os.environ.get("OAUTHLIB_INSECURE_TRANSPORT") == "1":
        raise RuntimeError(
            "OAUTHLIB_INSECURE_TRANSPORT must not be enabled in production."
        )
