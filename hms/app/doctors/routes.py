"""
Doctor management endpoints: profiles, department assignment,
schedule management, availability.
"""
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from app.extensions import db
from app.models import Doctor, DoctorSchedule, User, Role, Department
from app.utils.security import hash_password, is_strong_password, is_valid_email
from app.utils.decorators import roles_required, log_action

doctors_bp = Blueprint("doctors", __name__)


@doctors_bp.route("", methods=["GET"])
@jwt_required()
def list_doctors():
    dept_id = request.args.get("department_id")
    q = request.args.get("q", "").strip()

    query = Doctor.query.join(User)
    if dept_id:
        query = query.filter(Doctor.department_id == dept_id)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(User.first_name.ilike(like), User.last_name.ilike(like)))

    doctors = query.all()
    return jsonify([d.to_dict() for d in doctors])


@doctors_bp.route("/<doctor_id>", methods=["GET"])
@jwt_required()
def get_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    data = doctor.to_dict()
    data["schedules"] = [s.to_dict() for s in doctor.schedules]
    return jsonify(data)


@doctors_bp.route("", methods=["POST"])
@roles_required("admin")
def create_doctor():
    """Creates both the user account and the doctor profile in one call."""
    data = request.get_json(silent=True) or {}
    required = ["email", "password", "first_name", "last_name", "department_id"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": "validation_error", "message": f"Missing fields: {', '.join(missing)}"}), 400

    if not is_valid_email(data["email"]):
        return jsonify({"error": "validation_error", "message": "Invalid email address"}), 400
    if not is_strong_password(data["password"]):
        return jsonify({"error": "weak_password", "message": "Password must be 8+ chars with upper/lower/number/symbol"}), 400
    if User.query.filter_by(email=data["email"].lower()).first():
        return jsonify({"error": "conflict", "message": "A user with this email already exists"}), 409

    department = Department.query.get(data["department_id"])
    if not department:
        return jsonify({"error": "validation_error", "message": "Unknown department"}), 400

    role = Role.query.filter_by(name="doctor").first()
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
    db.session.flush()

    doctor = Doctor(
        user_id=user.id,
        department_id=department.id,
        specialization=data.get("specialization"),
        license_number=data.get("license_number"),
        years_experience=data.get("years_experience", 0),
        consultation_fee=data.get("consultation_fee", 0),
        bio=data.get("bio"),
    )
    db.session.add(doctor)
    db.session.commit()
    log_action(get_jwt_identity(), "doctor.create", "Doctor", doctor.id, details=user.full_name)
    return jsonify(doctor.to_dict()), 201


@doctors_bp.route("/<doctor_id>", methods=["PUT"])
@roles_required("admin", "doctor")
def update_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    claims = get_jwt()
    if claims.get("role") == "doctor" and doctor.user_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    for field in ("specialization", "license_number", "years_experience", "consultation_fee", "bio", "is_available"):
        if field in data:
            setattr(doctor, field, data[field])
    if "department_id" in data and claims.get("role") == "admin":
        doctor.department_id = data["department_id"]

    db.session.commit()
    log_action(get_jwt_identity(), "doctor.update", "Doctor", doctor.id)
    return jsonify(doctor.to_dict())


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

@doctors_bp.route("/<doctor_id>/schedules", methods=["GET"])
@jwt_required()
def get_schedules(doctor_id):
    Doctor.query.get_or_404(doctor_id)
    schedules = DoctorSchedule.query.filter_by(doctor_id=doctor_id).order_by(DoctorSchedule.day_of_week).all()
    return jsonify([s.to_dict() for s in schedules])


@doctors_bp.route("/<doctor_id>/schedules", methods=["POST"])
@roles_required("admin", "doctor")
def add_schedule(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    claims = get_jwt()
    if claims.get("role") == "doctor" and doctor.user_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    try:
        start_time = datetime.strptime(data["start_time"], "%H:%M").time()
        end_time = datetime.strptime(data["end_time"], "%H:%M").time()
        day_of_week = int(data["day_of_week"])
    except (KeyError, ValueError):
        return jsonify({"error": "validation_error", "message": "day_of_week (0-6), start_time and end_time (HH:MM) are required"}), 400

    if end_time <= start_time:
        return jsonify({"error": "validation_error", "message": "end_time must be after start_time"}), 400

    schedule = DoctorSchedule(
        doctor_id=doctor.id, day_of_week=day_of_week,
        start_time=start_time, end_time=end_time,
        slot_minutes=data.get("slot_minutes", 20),
    )
    db.session.add(schedule)
    db.session.commit()
    log_action(get_jwt_identity(), "doctor.schedule.create", "Doctor", doctor.id)
    return jsonify(schedule.to_dict()), 201


@doctors_bp.route("/schedules/<schedule_id>", methods=["DELETE"])
@roles_required("admin", "doctor")
def delete_schedule(schedule_id):
    schedule = DoctorSchedule.query.get_or_404(schedule_id)
    claims = get_jwt()
    if claims.get("role") == "doctor" and schedule.doctor.user_id != get_jwt_identity():
        return jsonify({"error": "forbidden"}), 403
    db.session.delete(schedule)
    db.session.commit()
    return jsonify({"message": "Schedule slot removed"})
