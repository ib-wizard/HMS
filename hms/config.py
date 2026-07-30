"""
Application configuration.

Loads settings from environment variables (see .env.example). Never hardcode
secrets here — this file is checked into source control.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(env_val, default=False):
    if env_val is None:
        return default
    return str(env_val).lower() in ("1", "true", "yes", "on")


class Config:
    """Base configuration shared by all environments."""

    APP_NAME = os.environ.get("APP_NAME", "MediCore HMS")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    # Database
    # NOTE: no localhost fallback here on purpose. If DATABASE_URL is missing
    # in production, we want a loud, immediate error at startup - not a silent
    # connection attempt to localhost that fails deep inside SQLAlchemy.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    if not SQLALCHEMY_DATABASE_URI:
        if os.environ.get("FLASK_ENV") == "development":
            # Local dev only: safe to fall back to a local Postgres instance.
            SQLALCHEMY_DATABASE_URI = (
                "postgresql://hms_user:hms_password@localhost:5432/hms_db"
            )
        else:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set. "
                "Set it in your Render service's Environment tab to the "
                "External Database URL of your Postgres instance."
            )

    # Render/Heroku sometimes provide "postgres://" - SQLAlchemy 2.x needs "postgresql://"
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    # JWT
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 30))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 7))
    )
    JWT_TOKEN_LOCATION = ["headers"]
    JWT_HEADER_NAME = "Authorization"
    JWT_HEADER_TYPE = "Bearer"

    # CORS
    CORS_ORIGINS = os.environ.get(
        "CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000"
    ).split(",")

    # Mail
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = _bool(os.environ.get("MAIL_USE_TLS"), True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "no-reply@hospital.com")

    # Uploads
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(BASE_DIR, "app", "uploads"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_MB", 15)) * 1024 * 1024
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "doc", "docx"}

    # Default admin (used by `flask seed-db`)
    DEFAULT_ADMIN_EMAIL = os.environ.get("DEFAULT_ADMIN_EMAIL", "admin@hospital.com")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD", "ChangeMe123!")

    # Rate limiting
    RATE_LIMIT_STORAGE_URI = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")

    # Security headers (Flask-Talisman)
    FORCE_HTTPS = _bool(os.environ.get("FORCE_HTTPS"), False)


class DevelopmentConfig(Config):
    DEBUG = True
    FORCE_HTTPS = False


class ProductionConfig(Config):
    DEBUG = False
    FORCE_HTTPS = _bool(os.environ.get("FORCE_HTTPS"), True)


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "postgresql://hms_user:hms_password@localhost:5432/hms_test_db"
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=60)


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
