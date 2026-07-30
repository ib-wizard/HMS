"""
Patient management endpoints: registration, profile, search, medical
history, admissions/discharge summaries.
"""
from datetime import datetime, date

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from app.extensions import db
from app.models import Patient, MedicalRecord, Admission, Prescription
from app.utils.decorators import roles_required, log_action

patients_bp = Blueprint("patients", __name__)

STAFF_ROLES = ("admin", "doctor", "nurse", "receptionist")


def _next_patient_code():
    last = Patient.query.order_by(Patient.created_at.desc()).first()
    next_num = 1
    if last and last.patient_code.startswith("PT-"):
        try:
            next_num = int(last.patient_code.split("-")[1]) + 1
        except (IndexError, ValueError):
            next_num = Patient.query.count() + 1
    return f"PT-{next_num:06d}"


@patients_bp.route("", methods=["GET"])
@roles_required(*STAFF_ROLES)
def list_patients():
    q = request.args.get("q", "").strip()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(int(request.args.get("per_page", 20)), 100)

    query = Patient.query.filter_by(is_active=True)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Patient.first_name.ilike(like),
                Patient.last_name.ilike(like),
                Patient.patient_code.ilike(like),
                Patient.phone.ilike(like),
            )
        )
    pagination = query.order_by(Patient.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "patients": [p.to_dict() for p in pagination.items],
        "total": pagination.total,
        "page": page,
        "pages": pagination.pages,
    })


@patients_bp.route("/<patient_id>", methods=["GET"])
@roles_required(*STAFF_ROLES)
def get_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    data = patient.to_dict()
    data["visit_history"] = [r.to_dict() for r in sorted(
        patient.medical_records, key=lambda r: r.visit_date, reverse=True
    )]
    data["admissions"] = [{
        "id": a.id,
        "bed": a.bed.bed_number if a.bed else None,
        "ward": a.bed.ward.name if a.bed and a.bed.ward else None,
        "admission_date": a.admission_date.isoformat(),
        "discharge_date": a.discharge_date.isoformat() if a.discharge_date else None,
        "status": a.status,
        "reason": a.reason,
    } for a in patient.admissions]
    return jsonify(data)


@patients_bp.route("", methods=["POST"])
@roles_required("admin", "receptionist", "nurse")
def register_patient():
    data = request.get_json(silent=True) or {}
    required = ["first_name", "last_name", "date_of_birth", "gender"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": "validation_error", "message": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        dob = datetime.strptime(data["date_of_birth"], "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "validation_error", "message": "date_of_birth must be YYYY-MM-DD"}), 400

    if dob > date.today():
        return jsonify({"error": "validation_error", "message": "date_of_birth cannot be in the future"}), 400

    patient = Patient(
        patient_code=_next_patient_code(),
        first_name=data["first_name"].strip(),
        last_name=data["last_name"].strip(),
        date_of_birth=dob,
        gender=data["gender"],
        blood_group=data.get("blood_group"),
        phone=data.get("phone"),
        email=data.get("email"),
        address=data.get("address"),
        emergency_contact_name=data.get("emergency_contact_name"),
        emergency_contact_phone=data.get("emergency_contact_phone"),
        allergies=data.get("allergies"),
        chronic_conditions=data.get("chronic_conditions"),
        insurance_provider=data.get("insurance_provider"),
        insurance_policy_number=data.get("insurance_policy_number"),
    )
    db.session.add(patient)
    db.session.commit()
    log_action(get_jwt_identity(), "patient.register", "Patient", patient.id, details=patient.full_name)
    return jsonify(patient.to_dict()), 201


@patients_bp.route("/<patient_id>", methods=["PUT"])
@roles_required("admin", "receptionist", "nurse", "doctor")
def update_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json(silent=True) or {}

    editable = [
        "first_name", "last_name", "gender", "blood_group", "phone", "email", "address",
        "emergency_contact_name", "emergency_contact_phone", "allergies", "chronic_conditions",
        "insurance_provider", "insurance_policy_number",
    ]
    for field in editable:
        if field in data:
            setattr(patient, field, data[field])

    if "date_of_birth" in data:
        try:
            patient.date_of_birth = datetime.strptime(data["date_of_birth"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "validation_error", "message": "date_of_birth must be YYYY-MM-DD"}), 400

    db.session.commit()
    log_action(get_jwt_identity(), "patient.update", "Patient", patient.id)
    return jsonify(patient.to_dict())


@patients_bp.route("/<patient_id>", methods=["DELETE"])
@roles_required("admin")
def deactivate_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    patient.is_active = False
    db.session.commit()
    log_action(get_jwt_identity(), "patient.deactivate", "Patient", patient.id)
    return jsonify({"message": "Patient record deactivated"})


# ---------------------------------------------------------------------------
# Medical history
# ---------------------------------------------------------------------------

@patients_bp.route("/<patient_id>/medical-records", methods=["POST"])
@roles_required("admin", "doctor")
def add_medical_record(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json(silent=True) or {}
    claims = get_jwt()

    from app.models import Doctor
    doctor = Doctor.query.filter_by(user_id=get_jwt_identity()).first() if claims.get("role") == "doctor" else None

    record = MedicalRecord(
        patient_id=patient.id,
        doctor_id=doctor.id if doctor else data.get("doctor_id"),
        appointment_id=data.get("appointment_id"),
        diagnosis=data.get("diagnosis"),
        symptoms=data.get("symptoms"),
        treatment_plan=data.get("treatment_plan"),
        notes=data.get("notes"),
    )
    db.session.add(record)
    db.session.flush()

    for item in data.get("prescriptions", []):
        db.session.add(Prescription(
            medical_record_id=record.id,
            medicine_name=item.get("medicine_name"),
            dosage=item.get("dosage"),
            frequency=item.get("frequency"),
            duration=item.get("duration"),
            instructions=item.get("instructions"),
        ))

    db.session.commit()
    log_action(get_jwt_identity(), "patient.medical_record.create", "Patient", patient.id)
    return jsonify(record.to_dict()), 201


# ---------------------------------------------------------------------------
# Admissions / Discharge
# ---------------------------------------------------------------------------

@patients_bp.route("/<patient_id>/admit", methods=["POST"])
@roles_required("admin", "doctor", "nurse")
def admit_patient(patient_id):
    from app.models import Bed

    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json(silent=True) or {}
    bed_id = data.get("bed_id")

    bed = None
    if bed_id:
        bed = Bed.query.get_or_404(bed_id)
        if bed.status != "available":
            return jsonify({"error": "conflict", "message": "Selected bed is not available"}), 409
        bed.status = "occupied"

    admission = Admission(
        patient_id=patient.id,
        bed_id=bed.id if bed else None,
        admitting_doctor_id=data.get("doctor_id"),
        reason=data.get("reason"),
    )
    db.session.add(admission)
    db.session.commit()
    log_action(get_jwt_identity(), "patient.admit", "Patient", patient.id)
    return jsonify({"message": "Patient admitted", "admission_id": admission.id}), 201


@patients_bp.route("/admissions/<admission_id>/discharge", methods=["POST"])
@roles_required("admin", "doctor", "nurse")
def discharge_patient(admission_id):
    admission = Admission.query.get_or_404(admission_id)
    data = request.get_json(silent=True) or {}

    admission.status = "discharged"
    admission.discharge_date = datetime.utcnow()
    admission.discharge_summary = data.get("discharge_summary")
    if admission.bed:
        admission.bed.status = "available"

    db.session.commit()
    log_action(get_jwt_identity(), "patient.discharge", "Admission", admission.id)
    return jsonify({"message": "Patient discharged"})
