"""
Password hashing and simple validation helpers.

Uses bcrypt directly (via the `bcrypt` package) rather than Werkzeug's
generate_password_hash, since bcrypt has a mature, well-audited track record
specifically for password storage and includes built-in salting + configurable
work factor.
"""
import re
import bcrypt

PASSWORD_MIN_LENGTH = 8
_PASSWORD_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,}$"
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def is_strong_password(password: str) -> bool:
    """Requires 8+ chars, upper, lower, digit, and special character."""
    return bool(_PASSWORD_RE.match(password or ""))


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))
