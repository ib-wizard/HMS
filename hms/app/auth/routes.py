"""
Authentication endpoints.

POST /api/auth/login            - email + password -> access & refresh JWTs
POST /api/auth/logout            - revokes the current access token
POST /api/auth/refresh           - exchange refresh token for new access token
GET  /api/auth/me                - current user profile
POST /api/auth/forgot-password   - issues a reset token (emailed in production)
POST /api/auth/reset-password    - consumes a reset token, sets new password
POST /api/auth/change-password   - authenticated password change
"""
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token, jwt_required,
    get_jwt_identity, get_jwt,
)

from app.extensions import db, jwt, limiter
from app.models import User, Role, PasswordResetToken, TokenBlocklist
from app.utils.security import hash_password, verify_password, is_strong_password, is_valid_email
from app.utils.decorators import log_action

auth_bp = Blueprint("auth", __name__)


@jwt.token_in_blocklist_loader
def check_if_revoked(jwt_header, jwt_payload):
    jti = jwt_payload["jti"]
    return TokenBlocklist.query.filter_by(jti=jti).first() is not None


@jwt.user_lookup_loader
def load_user(jwt_header, jwt_payload):
    return User.query.get(jwt_payload["sub"])


def _issue_tokens(user):
    extra_claims = {"role": user.role.name, "email": user.email, "name": user.full_name}
    access_token = create_access_token(identity=user.id, additional_claims=extra_claims)
    refresh_token = create_refresh_token(identity=user.id, additional_claims={"role": user.role.name})
    return access_token, refresh_token


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "validation_error", "message": "Email and password are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not verify_password(password, user.password_hash):
        return jsonify({"error": "invalid_credentials", "message": "Incorrect email or password"}), 401

    if not user.is_active:
        return jsonify({"error": "account_disabled", "message": "This account has been disabled. Contact an administrator."}), 403

    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()

    access_token, refresh_token = _issue_tokens(user)
    log_action(user.id, "auth.login", "User", user.id)

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user.to_dict(),
        "must_reset_password": user.must_reset_password,
    })


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user or not user.is_active:
        return jsonify({"error": "unauthorized"}), 401
    access_token = create_access_token(
        identity=user.id,
        additional_claims={"role": user.role.name, "email": user.email, "name": user.full_name},
    )
    return jsonify({"access_token": access_token})


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    jti = get_jwt()["jti"]
    db.session.add(TokenBlocklist(jti=jti))
    db.session.commit()
    log_action(get_jwt_identity(), "auth.logout")
    return jsonify({"message": "Logged out successfully"})


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "not_found"}), 404
    return jsonify(user.to_dict())


@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("5 per minute")
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    generic_response = jsonify({
        "message": "If an account with that email exists, a password reset link has been sent."
    })

    if not is_valid_email(email):
        return generic_response

    user = User.query.filter_by(email=email).first()
    if not user:
        return generic_response  # Do not reveal whether the account exists

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.session.add(reset)
    db.session.commit()

    # In production this token is emailed to the user via app/utils/mailer.py.
    # It is only returned directly here when running in debug mode, to make
    # local development/testing possible without an SMTP server configured.
    current_app.logger.info(f"Password reset requested for {email}")
    response_payload = {"message": "If an account with that email exists, a password reset link has been sent."}
    if current_app.debug:
        response_payload["debug_reset_token"] = raw_token
    return jsonify(response_payload)


@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("10 per minute")
def reset_password():
    data = request.get_json(silent=True) or {}
    token = data.get("token") or ""
    new_password = data.get("new_password") or ""

    if not is_strong_password(new_password):
        return jsonify({
            "error": "weak_password",
            "message": "Password must be 8+ characters and include upper/lowercase letters, a number, and a symbol.",
        }), 400

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reset = PasswordResetToken.query.filter_by(token_hash=token_hash, used=False).first()

    if not reset or reset.expires_at < datetime.now(timezone.utc):
        return jsonify({"error": "invalid_token", "message": "This reset link is invalid or has expired"}), 400

    user = User.query.get(reset.user_id)
    user.password_hash = hash_password(new_password)
    user.must_reset_password = False
    reset.used = True
    db.session.commit()

    log_action(user.id, "auth.password_reset", "User", user.id)
    return jsonify({"message": "Password has been reset. You may now log in."})


@auth_bp.route("/change-password", methods=["POST"])
@jwt_required()
def change_password():
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    user = User.query.get(get_jwt_identity())
    if not verify_password(current_password, user.password_hash):
        return jsonify({"error": "invalid_credentials", "message": "Current password is incorrect"}), 401

    if not is_strong_password(new_password):
        return jsonify({
            "error": "weak_password",
            "message": "Password must be 8+ characters and include upper/lowercase letters, a number, and a symbol.",
        }), 400

    user.password_hash = hash_password(new_password)
    user.must_reset_password = False
    db.session.commit()
    log_action(user.id, "auth.password_change", "User", user.id)
    return jsonify({"message": "Password updated successfully"})
