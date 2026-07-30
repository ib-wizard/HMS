"""
Application factory for the Hospital Management System.
"""
import os
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify, send_from_directory
from flask_jwt_extended.exceptions import JWTExtendedException

from config import config_by_name
from app.extensions import db, migrate, jwt, cors, limiter, talisman


def create_app(config_name=None):
    config_name = config_name or os.environ.get("FLASK_ENV", "production")
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_by_name.get(config_name, config_by_name["production"]))

    _init_extensions(app)
    _init_logging(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_frontend_routes(app)
    _register_cli(app)

    return app


def _init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}}, supports_credentials=True)
    limiter.init_app(app)
    limiter.storage_uri = app.config["RATE_LIMIT_STORAGE_URI"]

    # Security headers. CSP is relaxed for inline <style>/<script> tags since
    # every frontend page is a single self-contained HTML file per the
    # project's frontend requirement.
    csp = {
        "default-src": "'self'",
        "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com", "https://cdnjs.cloudflare.com"],
        "font-src": ["'self'", "https://fonts.gstatic.com", "https://cdnjs.cloudflare.com"],
        "script-src": ["'self'", "'unsafe-inline'", "https://cdnjs.cloudflare.com"],
        "img-src": ["'self'", "data:", "blob:"],
        "connect-src": "'self'",
    }
    talisman.init_app(
        app,
        force_https=app.config["FORCE_HTTPS"],
        content_security_policy=csp,
        session_cookie_secure=app.config["FORCE_HTTPS"],
    )

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def _init_logging(app):
    if not app.debug:
        os.makedirs("logs", exist_ok=True)
        handler = RotatingFileHandler("logs/hms.log", maxBytes=1_000_000, backupCount=5)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s [in %(pathname)s:%(lineno)d]")
        )
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info("HMS startup")


def _register_blueprints(app):
    from app.auth.routes import auth_bp
    from app.admin.routes import admin_bp
    from app.patients.routes import patients_bp
    from app.doctors.routes import doctors_bp
    from app.appointments.routes import appointments_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(patients_bp, url_prefix="/api/patients")
    app.register_blueprint(doctors_bp, url_prefix="/api/doctors")
    app.register_blueprint(appointments_bp, url_prefix="/api/appointments")


def _register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "bad_request", "message": str(e)}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "not_found", "message": "Resource not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "method_not_allowed", "message": "Method not allowed"}), 405

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": "rate_limited", "message": "Too many requests, please slow down"}), 429

    @app.errorhandler(JWTExtendedException)
    def jwt_error(e):
        return jsonify({"error": "unauthorized", "message": str(e)}), 401

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": "server_error", "message": "An unexpected error occurred"}), 500


def _register_frontend_routes(app):
    """
    Serves the single-file HTML/CSS/JS pages from /frontend.
    Each page is fully self-contained per the project's frontend requirement.
    """
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

    @app.route("/")
    def index():
        return send_from_directory(frontend_dir, "login.html")

    @app.route("/<page>.html")
    def serve_page(page):
        safe_name = f"{page}.html"
        file_path = os.path.join(frontend_dir, safe_name)
        if not os.path.isfile(file_path):
            return jsonify({"error": "not_found"}), 404
        return send_from_directory(frontend_dir, safe_name)

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "app": app.config["APP_NAME"]})


def _register_cli(app):
    from app.cli import register_cli_commands
    register_cli_commands(app)
