"""
Appointment management endpoints: booking, rescheduling, cancellation,
queue management, and available-slot lookup.
"""
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from app.extensions import db
from app.models import Appointment, Doctor, DoctorSchedule, Patient, Notification
from app.utils.decorators import roles_required, log_action

appointments_bp = Blueprint("appointments", __name__)

STAFF_ROLES = ("admin", "doctor", "nurse", "receptionist")


@appointments_bp.route("", methods=["GET"])
@roles_required(*STAFF_ROLES)
def list_appointments():
    date_str = request.args.get("date")
    doctor_id = request.args.get("doctor_id")
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(int(request.args.get("per_page", 20)), 100)

    query = Appointment.query
    if date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date()
            query = query.filter(db.func.date(Appointment.scheduled_at) == day)
        except ValueError:
            return jsonify({"error": "validation_error", "message": "date must be YYYY-MM-DD"}), 400
    if doctor_id:
        query = query.filter(Appointment.doctor_id == doctor_id)
    if patient_id:
        query = query.filter(Appointment.patient_id == patient_id)
    if status:
        query = query.filter(Appointment.status == status)

    pagination = query.order_by(Appointment.scheduled_at.asc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "appointments": [a.to_dict() for a in pagination.items],
        "total": pagination.total,
        "page": page,
        "pages": pagination.pages,
    })


@appointments_bp.route("/available-slots", methods=["GET"])
@jwt_required()
def available_slots():
    doctor_id = request.args.get("doctor_id")
    date_str = request.args.get("date")
    if not doctor_id or not date_str:
        return jsonify({"error": "validation_error", "message": "doctor_id and date are required"}), 400

    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "validation_error", "message": "date must be YYYY-MM-DD"}), 400

    doctor = Doctor.query.get_or_404(doctor_id)
    weekday = day.weekday()  # Monday=0
    schedule = DoctorSchedule.query.filter_by(doctor_id=doctor.id, day_of_week=weekday, is_active=True).first()
    if not schedule:
        return jsonify({"slots": [], "message": "Doctor is not scheduled on this day"})

    booked = {
        a.scheduled_at.strftime("%H:%M")
        for a in Appointment.query.filter(
            Appointment.doctor_id == doctor.id,
            db.func.date(Appointment.scheduled_at) == day,
            Appointment.status.notin_(["cancelled", "no_show"]),
        ).all()
    }

    slots = []
    current = datetime.combine(day, schedule.start_time)
    end = datetime.combine(day, schedule.end_time)
    step = timedelta(minutes=schedule.slot_minutes)
    while current + step <= end:
        time_str = current.strftime("%H:%M")
        slots.append({"time": time_str, "available": time_str not in booked})
        current += step

    return jsonify({"slots": slots})


@appointments_bp.route("", methods=["POST"])
@roles_required(*STAFF_ROLES)
def book_appointment():
    data = request.get_json(silent=True) or {}
    required = ["patient_id", "doctor_id", "scheduled_at"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": "validation_error", "message": f"Missing fields: {', '.join(missing)}"}), 400

    patient = Patient.query.get_or_404(data["patient_id"])
    doctor = Doctor.query.get_or_404(data["doctor_id"])

    try:
        scheduled_at = datetime.fromisoformat(data["scheduled_at"])
    except ValueError:
        return jsonify({"error": "validation_error", "message": "scheduled_at must be ISO 8601"}), 400

    if scheduled_at < datetime.now(scheduled_at.tzinfo):
        return jsonify({"error": "validation_error", "message": "Cannot book an appointment in the past"}), 400

    clash = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.scheduled_at == scheduled_at,
        Appointment.status.notin_(["cancelled", "no_show"]),
    ).first()
    if clash:
        return jsonify({"error": "conflict", "message": "This time slot is already booked"}), 409

    day_appt_count = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        db.func.date(Appointment.scheduled_at) == scheduled_at.date(),
        Appointment.status.notin_(["cancelled", "no_show"]),
    ).count()

    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        scheduled_at=scheduled_at,
        duration_minutes=data.get("duration_minutes", 20),
        reason=data.get("reason"),
        queue_number=day_appt_count + 1,
    )
    db.session.add(appt)

    if doctor.user_id:
        db.session.add(Notification(
            user_id=doctor.user_id,
            title="New appointment booked",
            message=f"{patient.full_name} booked an appointment on {scheduled_at.strftime('%b %d, %Y at %H:%M')}",
            category="appointment",
        ))

    db.session.commit()
    log_action(get_jwt_identity(), "appointment.book", "Appointment", appt.id)
    return jsonify(appt.to_dict()), 201


@appointments_bp.route("/<appointment_id>/reschedule", methods=["POST"])
@roles_required(*STAFF_ROLES)
def reschedule_appointment(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    data = request.get_json(silent=True) or {}

    try:
        new_time = datetime.fromisoformat(data["scheduled_at"])
    except (KeyError, ValueError):
        return jsonify({"error": "validation_error", "message": "scheduled_at (ISO 8601) is required"}), 400

    clash = Appointment.query.filter(
        Appointment.doctor_id == appt.doctor_id,
        Appointment.scheduled_at == new_time,
        Appointment.id != appt.id,
        Appointment.status.notin_(["cancelled", "no_show"]),
    ).first()
    if clash:
        return jsonify({"error": "conflict", "message": "This time slot is already booked"}), 409

    appt.scheduled_at = new_time
    appt.status = "scheduled"
    appt.reminder_sent = False
    db.session.commit()
    log_action(get_jwt_identity(), "appointment.reschedule", "Appointment", appt.id)
    return jsonify(appt.to_dict())


@appointments_bp.route("/<appointment_id>/cancel", methods=["POST"])
@roles_required(*STAFF_ROLES)
def cancel_appointment(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    data = request.get_json(silent=True) or {}
    appt.status = "cancelled"
    appt.cancel_reason = data.get("reason")
    db.session.commit()
    log_action(get_jwt_identity(), "appointment.cancel", "Appointment", appt.id)
    return jsonify(appt.to_dict())


@appointments_bp.route("/<appointment_id>/status", methods=["PATCH"])
@roles_required(*STAFF_ROLES)
def update_status(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    valid_statuses = {"scheduled", "confirmed", "checked_in", "in_progress", "completed", "cancelled", "no_show"}
    if new_status not in valid_statuses:
        return jsonify({"error": "validation_error", "message": f"status must be one of {sorted(valid_statuses)}"}), 400

    appt.status = new_status
    db.session.commit()
    log_action(get_jwt_identity(), "appointment.status_update", "Appointment", appt.id, details=new_status)
    return jsonify(appt.to_dict())


@appointments_bp.route("/queue", methods=["GET"])
@roles_required(*STAFF_ROLES)
def today_queue():
    doctor_id = request.args.get("doctor_id")
    today = datetime.utcnow().date()
    query = Appointment.query.filter(
        db.func.date(Appointment.scheduled_at) == today,
        Appointment.status.in_(["scheduled", "confirmed", "checked_in", "in_progress"]),
    )
    if doctor_id:
        query = query.filter(Appointment.doctor_id == doctor_id)
    appts = query.order_by(Appointment.queue_number.asc()).all()
    return jsonify([a.to_dict() for a in appts])
