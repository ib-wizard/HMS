"""
Administrator endpoints: dashboard statistics, user management,
department management, and audit logs. All routes require the "admin" role.
"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.extensions import db
from app.models import User, Role, Department, Patient, Doctor, Appointment, AuditLog
from app.utils.security import hash_password, is_strong_password, is_valid_email
from app.utils.decorators import roles_required, log_action

admin_bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@admin_bp.route("/dashboard", methods=["GET"])
@roles_required("admin")
def dashboard():
    today = datetime.now(timezone.utc).date()
    week_ago = today - timedelta(days=6)

    total_patients = Patient.query.filter_by(is_active=True).count()
    total_doctors = Doctor.query.count()
    total_staff = User.query.count()
    today_appointments = Appointment.query.filter(
        db.func.date(Appointment.scheduled_at) == today
    ).count()

    status_counts = dict(
        db.session.query(Appointment.status, db.func.count(Appointment.id))
        .group_by(Appointment.status).all()
    )

    # Appointments per day for the last 7 days (for a trend chart)
    trend = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = Appointment.query.filter(db.func.date(Appointment.scheduled_at) == day).count()
        trend.append({"date": day.isoformat(), "count": count})

    dept_load = (
        db.session.query(Department.name, db.func.count(Doctor.id))
        .join(Doctor, Doctor.department_id == Department.id)
        .group_by(Department.name).all()
    )

    return jsonify({
        "totals": {
            "patients": total_patients,
            "doctors": total_doctors,
            "staff": total_staff,
            "today_appointments": today_appointments,
        },
        "appointment_status_breakdown": status_counts,
        "appointments_last_7_days": trend,
        "department_doctor_counts": [{"department": d, "doctors": c} for d, c in dept_load],
    })


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

@admin_bp.route("/users", methods=["GET"])
@roles_required("admin")
def list_users():
    q = request.args.get("q", "").strip()
    role_filter = request.args.get("role")
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(int(request.args.get("per_page", 20)), 100)

    query = User.query.join(Role)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(User.first_name.ilike(like), User.last_name.ilike(like), User.email.ilike(like))
        )
    if role_filter:
        query = query.filter(Role.name == role_filter)

    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "users": [u.to_dict() for u in pagination.items],
        "total": pagination.total,
        "page": page,
        "pages": pagination.pages,
    })


@admin_bp.route("/users", methods=["POST"])
@roles_required("admin")
def create_user():
    data = request.get_json(silent=True) or {}
    required = ["email", "password", "first_name", "last_name", "role"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": "validation_error", "message": f"Missing fields: {', '.join(missing)}"}), 400

    if not is_valid_email(data["email"]):
        return jsonify({"error": "validation_error", "message": "Invalid email address"}), 400
    if not is_strong_password(data["password"]):
        return jsonify({"error": "weak_password", "message": "Password must be 8+ chars with upper/lower/number/symbol"}), 400
    if User.query.filter_by(email=data["email"].lower()).first():
        return jsonify({"error": "conflict", "message": "A user with this email already exists"}), 409

    role = Role.query.filter_by(name=data["role"]).first()
    if not role:
        return jsonify({"error": "validation_error", "message": "Unknown role"}), 400

    user = User(
        email=data["email"].strip().lower(),
        password_hash=hash_password(data["password"]),
        first_name=data["first_name"].strip(),
        last_name=data["last_name"].strip(),
        phone=data.get("phone"),
        role_id=role.id,
        must_reset_password=True,
    )
    db.session.add(user)
    db.session.commit()
    log_action(get_jwt_identity(), "user.create", "User", user.id, details=user.email)
    return jsonify(user.to_dict()), 201


@admin_bp.route("/users/<user_id>", methods=["PUT"])
@roles_required("admin")
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    for field in ("first_name", "last_name", "phone"):
        if field in data:
            setattr(user, field, data[field])

    if "role" in data:
        role = Role.query.filter_by(name=data["role"]).first()
        if not role:
            return jsonify({"error": "validation_error", "message": "Unknown role"}), 400
        user.role_id = role.id

    if "is_active" in data:
        user.is_active = bool(data["is_active"])

    db.session.commit()
    log_action(get_jwt_identity(), "user.update", "User", user.id)
    return jsonify(user.to_dict())


@admin_bp.route("/users/<user_id>", methods=["DELETE"])
@roles_required("admin")
def deactivate_user(user_id):
    """Soft-delete: deactivates rather than hard-deletes to preserve history."""
    user = User.query.get_or_404(user_id)
    user.is_active = False
    db.session.commit()
    log_action(get_jwt_identity(), "user.deactivate", "User", user.id)
    return jsonify({"message": "User deactivated"})


@admin_bp.route("/roles", methods=["GET"])
@roles_required("admin")
def list_roles():
    return jsonify([{"id": r.id, "name": r.name, "description": r.description} for r in Role.query.all()])


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

@admin_bp.route("/departments", methods=["GET"])
@jwt_required()
def list_departments():
    return jsonify([d.to_dict() for d in Department.query.order_by(Department.name).all()])


@admin_bp.route("/departments", methods=["POST"])
@roles_required("admin")
def create_department():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "validation_error", "message": "Department name is required"}), 400
    if Department.query.filter_by(name=name).first():
        return jsonify({"error": "conflict", "message": "Department already exists"}), 409

    dept = Department(name=name, description=data.get("description"))
    db.session.add(dept)
    db.session.commit()
    log_action(get_jwt_identity(), "department.create", "Department", dept.id, details=name)
    return jsonify(dept.to_dict()), 201


@admin_bp.route("/departments/<dept_id>", methods=["PUT"])
@roles_required("admin")
def update_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    data = request.get_json(silent=True) or {}
    if "name" in data:
        dept.name = data["name"].strip()
    if "description" in data:
        dept.description = data["description"]
    if "is_active" in data:
        dept.is_active = bool(data["is_active"])
    db.session.commit()
    log_action(get_jwt_identity(), "department.update", "Department", dept.id)
    return jsonify(dept.to_dict())


@admin_bp.route("/departments/<dept_id>", methods=["DELETE"])
@roles_required("admin")
def delete_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    if dept.doctors:
        return jsonify({"error": "conflict", "message": "Cannot delete a department with assigned doctors"}), 409
    db.session.delete(dept)
    db.session.commit()
    log_action(get_jwt_identity(), "department.delete", "Department", dept_id)
    return jsonify({"message": "Department deleted"})


# ---------------------------------------------------------------------------
# Audit logs
# ---------------------------------------------------------------------------

@admin_bp.route("/audit-logs", methods=["GET"])
@roles_required("admin")
def audit_logs():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(int(request.args.get("per_page", 25)), 100)
    pagination = AuditLog.query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify({
        "logs": [log.to_dict() for log in pagination.items],
        "total": pagination.total,
        "page": page,
        "pages": pagination.pages,
    })
