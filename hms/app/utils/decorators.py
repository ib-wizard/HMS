"""
Role-based access control decorators and audit-logging helper.
"""
from functools import wraps
from flask import jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt

from app.extensions import db
from app.models import AuditLog


def roles_required(*allowed_roles):
    """
    Restricts an endpoint to users whose role is in `allowed_roles`.
    Must be used alongside @jwt_required() ordering is handled internally.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            role = claims.get("role")
            if role not in allowed_roles:
                return jsonify({"error": "forbidden", "message": "You do not have permission to perform this action"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def log_action(actor_id, action, entity_type=None, entity_id=None, details=None):
    """Writes an audit log entry. Never raises — logging must not break requests."""
    try:
        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
