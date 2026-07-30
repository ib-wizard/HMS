"""
Database models for the Hospital Management System.

Design notes:
- All primary keys are UUID strings for safety across a distributed system
  and to avoid leaking sequential IDs (e.g. patient counts) to the frontend.
- Timestamps use timezone-aware UTC datetimes.
- Soft-delete (`is_active`) is preferred over hard deletes for clinical and
  financial records to preserve audit history.
- This schema covers the full 14-module scope. Phase 1 of the build
  (this delivery) fully implements Auth, Admin, Patients, Doctors, and
  Appointments end-to-end. The remaining tables are included now so the
  schema does not need breaking migrations when later modules are added.
"""
import uuid
from datetime import datetime, timezone
from app.extensions import db


def gen_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

class Role(db.Model, TimestampMixin):
    __tablename__ = "roles"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(50), unique=True, nullable=False)  # admin, doctor, nurse, patient, pharmacist, lab_tech, receptionist, accountant
    description = db.Column(db.String(255))

    users = db.relationship("User", back_populates="role")

    def __repr__(self):
        return f"<Role {self.name}>"


class User(db.Model, TimestampMixin):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(30))
    role_id = db.Column(db.String(36), db.ForeignKey("roles.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    must_reset_password = db.Column(db.Boolean, default=False, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True))
    avatar_url = db.Column(db.String(255))

    role = db.relationship("Role", back_populates="users")
    doctor_profile = db.relationship("Doctor", back_populates="user", uselist=False, cascade="all, delete-orphan")
    nurse_profile = db.relationship("Nurse", back_populates="user", uselist=False, cascade="all, delete-orphan")
    audit_logs = db.relationship("AuditLog", back_populates="actor")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "phone": self.phone,
            "role": self.role.name if self.role else None,
            "is_active": self.is_active,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "avatar_url": self.avatar_url,
            "created_at": self.created_at.isoformat(),
        }


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    token_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    actor_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False)       # e.g. "patient.create"
    entity_type = db.Column(db.String(50))                    # e.g. "Patient"
    entity_id = db.Column(db.String(36))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    actor = db.relationship("User", back_populates="audit_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "actor": self.actor.full_name if self.actor else "System",
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Hospital structure
# ---------------------------------------------------------------------------

class Department(db.Model, TimestampMixin):
    __tablename__ = "departments"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    doctors = db.relationship("Doctor", back_populates="department")
    wards = db.relationship("Ward", back_populates="department")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "doctor_count": len(self.doctors),
        }


class HospitalSetting(db.Model, TimestampMixin):
    __tablename__ = "hospital_settings"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)


# ---------------------------------------------------------------------------
# Doctors / Nurses
# ---------------------------------------------------------------------------

class Doctor(db.Model, TimestampMixin):
    __tablename__ = "doctors"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), unique=True, nullable=False)
    department_id = db.Column(db.String(36), db.ForeignKey("departments.id"), nullable=False)
    specialization = db.Column(db.String(120))
    license_number = db.Column(db.String(60), unique=True)
    years_experience = db.Column(db.Integer, default=0)
    consultation_fee = db.Column(db.Numeric(10, 2), default=0)
    bio = db.Column(db.Text)
    is_available = db.Column(db.Boolean, default=True)

    user = db.relationship("User", back_populates="doctor_profile")
    department = db.relationship("Department", back_populates="doctors")
    schedules = db.relationship("DoctorSchedule", back_populates="doctor", cascade="all, delete-orphan")
    appointments = db.relationship("Appointment", back_populates="doctor")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.user.full_name if self.user else None,
            "email": self.user.email if self.user else None,
            "phone": self.user.phone if self.user else None,
            "department": self.department.name if self.department else None,
            "department_id": self.department_id,
            "specialization": self.specialization,
            "license_number": self.license_number,
            "years_experience": self.years_experience,
            "consultation_fee": float(self.consultation_fee or 0),
            "bio": self.bio,
            "is_available": self.is_available,
        }


class DoctorSchedule(db.Model):
    __tablename__ = "doctor_schedules"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    doctor_id = db.Column(db.String(36), db.ForeignKey("doctors.id"), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday ... 6=Sunday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    slot_minutes = db.Column(db.Integer, default=20)
    is_active = db.Column(db.Boolean, default=True)

    doctor = db.relationship("Doctor", back_populates="schedules")

    def to_dict(self):
        return {
            "id": self.id,
            "doctor_id": self.doctor_id,
            "day_of_week": self.day_of_week,
            "start_time": self.start_time.strftime("%H:%M"),
            "end_time": self.end_time.strftime("%H:%M"),
            "slot_minutes": self.slot_minutes,
            "is_active": self.is_active,
        }


class Nurse(db.Model, TimestampMixin):
    __tablename__ = "nurses"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), unique=True, nullable=False)
    department_id = db.Column(db.String(36), db.ForeignKey("departments.id"))
    license_number = db.Column(db.String(60))
    shift = db.Column(db.String(20))  # morning, evening, night

    user = db.relationship("User", back_populates="nurse_profile")
    department = db.relationship("Department")


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

class Patient(db.Model, TimestampMixin):
    __tablename__ = "patients"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    patient_code = db.Column(db.String(20), unique=True, nullable=False)  # e.g. PT-000123
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(20), nullable=False)
    blood_group = db.Column(db.String(5))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    emergency_contact_name = db.Column(db.String(120))
    emergency_contact_phone = db.Column(db.String(30))
    allergies = db.Column(db.Text)
    chronic_conditions = db.Column(db.Text)
    insurance_provider = db.Column(db.String(120))
    insurance_policy_number = db.Column(db.String(60))
    is_active = db.Column(db.Boolean, default=True)

    admissions = db.relationship("Admission", back_populates="patient")
    appointments = db.relationship("Appointment", back_populates="patient")
    medical_records = db.relationship("MedicalRecord", back_populates="patient", cascade="all, delete-orphan")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self):
        today = datetime.now(timezone.utc).date()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    def to_dict(self):
        return {
            "id": self.id,
            "patient_code": self.patient_code,
            "full_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "date_of_birth": self.date_of_birth.isoformat(),
            "age": self.age,
            "gender": self.gender,
            "blood_group": self.blood_group,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "emergency_contact_name": self.emergency_contact_name,
            "emergency_contact_phone": self.emergency_contact_phone,
            "allergies": self.allergies,
            "chronic_conditions": self.chronic_conditions,
            "insurance_provider": self.insurance_provider,
            "insurance_policy_number": self.insurance_policy_number,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }


class MedicalRecord(db.Model):
    __tablename__ = "medical_records"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    patient_id = db.Column(db.String(36), db.ForeignKey("patients.id"), nullable=False)
    doctor_id = db.Column(db.String(36), db.ForeignKey("doctors.id"))
    appointment_id = db.Column(db.String(36), db.ForeignKey("appointments.id"))
    visit_date = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    diagnosis = db.Column(db.Text)
    symptoms = db.Column(db.Text)
    treatment_plan = db.Column(db.Text)
    notes = db.Column(db.Text)

    patient = db.relationship("Patient", back_populates="medical_records")
    doctor = db.relationship("Doctor")
    prescriptions = db.relationship("Prescription", back_populates="medical_record", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "doctor": self.doctor.user.full_name if self.doctor and self.doctor.user else None,
            "visit_date": self.visit_date.isoformat(),
            "diagnosis": self.diagnosis,
            "symptoms": self.symptoms,
            "treatment_plan": self.treatment_plan,
            "notes": self.notes,
            "prescriptions": [p.to_dict() for p in self.prescriptions],
        }


class Prescription(db.Model):
    __tablename__ = "prescriptions"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    medical_record_id = db.Column(db.String(36), db.ForeignKey("medical_records.id"), nullable=False)
    medicine_name = db.Column(db.String(150), nullable=False)
    dosage = db.Column(db.String(80))
    frequency = db.Column(db.String(80))
    duration = db.Column(db.String(80))
    instructions = db.Column(db.String(255))
    status = db.Column(db.String(20), default="pending")  # pending, dispensed, cancelled

    medical_record = db.relationship("MedicalRecord", back_populates="prescriptions")

    def to_dict(self):
        return {
            "id": self.id,
            "medicine_name": self.medicine_name,
            "dosage": self.dosage,
            "frequency": self.frequency,
            "duration": self.duration,
            "instructions": self.instructions,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

class Appointment(db.Model, TimestampMixin):
    __tablename__ = "appointments"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    patient_id = db.Column(db.String(36), db.ForeignKey("patients.id"), nullable=False)
    doctor_id = db.Column(db.String(36), db.ForeignKey("doctors.id"), nullable=False)
    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    duration_minutes = db.Column(db.Integer, default=20)
    reason = db.Column(db.String(255))
    status = db.Column(db.String(20), default="scheduled", index=True)
    # scheduled, confirmed, checked_in, in_progress, completed, cancelled, no_show
    queue_number = db.Column(db.Integer)
    cancel_reason = db.Column(db.String(255))
    reminder_sent = db.Column(db.Boolean, default=False)

    patient = db.relationship("Patient", back_populates="appointments")
    doctor = db.relationship("Doctor", back_populates="appointments")

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "patient_name": self.patient.full_name if self.patient else None,
            "doctor_id": self.doctor_id,
            "doctor_name": self.doctor.user.full_name if self.doctor and self.doctor.user else None,
            "department": self.doctor.department.name if self.doctor and self.doctor.department else None,
            "scheduled_at": self.scheduled_at.isoformat(),
            "duration_minutes": self.duration_minutes,
            "reason": self.reason,
            "status": self.status,
            "queue_number": self.queue_number,
            "cancel_reason": self.cancel_reason,
        }


# ---------------------------------------------------------------------------
# Admissions / Wards / Beds
# ---------------------------------------------------------------------------

class Ward(db.Model, TimestampMixin):
    __tablename__ = "wards"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(100), nullable=False)
    department_id = db.Column(db.String(36), db.ForeignKey("departments.id"))
    ward_type = db.Column(db.String(50))  # general, icu, maternity, pediatric...
    floor = db.Column(db.String(20))

    department = db.relationship("Department", back_populates="wards")
    beds = db.relationship("Bed", back_populates="ward", cascade="all, delete-orphan")


class Bed(db.Model, TimestampMixin):
    __tablename__ = "beds"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    ward_id = db.Column(db.String(36), db.ForeignKey("wards.id"), nullable=False)
    bed_number = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default="available")  # available, occupied, maintenance

    ward = db.relationship("Ward", back_populates="beds")
    admissions = db.relationship("Admission", back_populates="bed")

    def to_dict(self):
        return {
            "id": self.id,
            "ward": self.ward.name if self.ward else None,
            "bed_number": self.bed_number,
            "status": self.status,
        }


class Admission(db.Model, TimestampMixin):
    __tablename__ = "admissions"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    patient_id = db.Column(db.String(36), db.ForeignKey("patients.id"), nullable=False)
    bed_id = db.Column(db.String(36), db.ForeignKey("beds.id"))
    admitting_doctor_id = db.Column(db.String(36), db.ForeignKey("doctors.id"))
    admission_date = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    discharge_date = db.Column(db.DateTime(timezone=True))
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default="admitted")  # admitted, discharged, transferred
    discharge_summary = db.Column(db.Text)

    patient = db.relationship("Patient", back_populates="admissions")
    bed = db.relationship("Bed", back_populates="admissions")
    admitting_doctor = db.relationship("Doctor")


# ---------------------------------------------------------------------------
# Pharmacy
# ---------------------------------------------------------------------------

class Supplier(db.Model, TimestampMixin):
    __tablename__ = "suppliers"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(150), nullable=False)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))


class Drug(db.Model, TimestampMixin):
    __tablename__ = "drugs"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(80))
    unit = db.Column(db.String(30))
    quantity_in_stock = db.Column(db.Integer, default=0)
    reorder_level = db.Column(db.Integer, default=10)
    unit_price = db.Column(db.Numeric(10, 2), default=0)
    expiry_date = db.Column(db.Date)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"))

    supplier = db.relationship("Supplier")


# ---------------------------------------------------------------------------
# Laboratory
# ---------------------------------------------------------------------------

class LabTest(db.Model, TimestampMixin):
    __tablename__ = "lab_tests"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    patient_id = db.Column(db.String(36), db.ForeignKey("patients.id"), nullable=False)
    doctor_id = db.Column(db.String(36), db.ForeignKey("doctors.id"))
    test_name = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(20), default="requested")  # requested, in_progress, completed
    result = db.Column(db.Text)
    result_file_url = db.Column(db.String(255))
    requested_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    completed_at = db.Column(db.DateTime(timezone=True))

    patient = db.relationship("Patient")
    doctor = db.relationship("Doctor")


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

class Invoice(db.Model, TimestampMixin):
    __tablename__ = "invoices"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    invoice_number = db.Column(db.String(30), unique=True, nullable=False)
    patient_id = db.Column(db.String(36), db.ForeignKey("patients.id"), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), default=0)
    paid_amount = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(20), default="unpaid")  # unpaid, partial, paid, cancelled
    insurance_claim_number = db.Column(db.String(60))

    patient = db.relationship("Patient")
    items = db.relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    invoice_id = db.Column(db.String(36), db.ForeignKey("invoices.id"), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), default=0)

    invoice = db.relationship("Invoice", back_populates="items")


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    invoice_id = db.Column(db.String(36), db.ForeignKey("invoices.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(30))  # cash, card, insurance, bank_transfer
    paid_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    reference = db.Column(db.String(80))

    invoice = db.relationship("Invoice", back_populates="payments")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(30), default="general")  # appointment, system, billing, emergency
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "is_read": self.is_read,
            "category": self.category,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

class PatientDocument(db.Model):
    __tablename__ = "patient_documents"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    patient_id = db.Column(db.String(36), db.ForeignKey("patients.id"), nullable=False)
    uploaded_by_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50))
    category = db.Column(db.String(50))  # lab_result, medical_image, report, other
    uploaded_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    patient = db.relationship("Patient")
    uploaded_by = db.relationship("User")


# ---------------------------------------------------------------------------
# Emergency
# ---------------------------------------------------------------------------

class TokenBlocklist(db.Model):
    """Revoked JWTs (used on logout) so tokens can't be replayed until expiry."""
    __tablename__ = "token_blocklist"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    jti = db.Column(db.String(64), nullable=False, index=True, unique=True)
    revoked_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class EmergencyCase(db.Model, TimestampMixin):
    __tablename__ = "emergency_cases"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    patient_id = db.Column(db.String(36), db.ForeignKey("patients.id"), nullable=False)
    triage_level = db.Column(db.String(20))  # critical, urgent, stable
    chief_complaint = db.Column(db.Text)
    attending_doctor_id = db.Column(db.String(36), db.ForeignKey("doctors.id"))
    status = db.Column(db.String(20), default="active")  # active, stabilized, admitted, discharged
    arrived_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    patient = db.relationship("Patient")
    attending_doctor = db.relationship("Doctor")
