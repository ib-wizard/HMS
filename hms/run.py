"""
WSGI entry point.

Local dev:   python run.py
Production:  gunicorn -c gunicorn_config.py run:app
"""
import os
from app import create_app

app = create_app(os.environ.get("FLASK_ENV", "production"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=app.config.get("DEBUG", False))
