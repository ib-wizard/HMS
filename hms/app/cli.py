"""
Custom Flask CLI commands.

Usage:
    flask seed-db        # creates roles, default admin, departments, demo data
    flask create-admin    --email a@b.com --password Secret123!
"""
import click
from datetime import date, time, timedelta

from app.extensions import db
from app.models import (
    Role, User, Department, Doctor, DoctorSchedule, Patient, HospitalSetting,
)
from app.utils.security import hash_password


ROLE_DEFS = [
    ("admin", "Full system access"),
    ("doctor", "Clinical staff - consultations, prescriptions, diagnosis"),
    ("nurse", "Ward and patient care staff"),
    ("receptionist", "Front-desk, appointment booking"),
    ("pharmacist", "Pharmacy inventory and dispensing"),
    ("lab_technician", "Laboratory test processing"),
    ("accountant", "Billing and finance"),
    ("patient", "Patient portal access"),
]


def register_cli_commands(app):
    @app.cli.command("seed-db")
    def seed_db():
        """Seed roles, default admin, departments, and demo data."""
        _seed_roles()
        admin = _seed_admin(app)
        depts = _seed_departments()
        _seed_hospital_settings(app)
        _seed_demo_doctors(depts)
        _seed_demo_patients()
        db.session.commit()
        click.echo("✔ Database seeded successfully.")
        click.echo(f"  Admin login: {admin.email} / (see DEFAULT_ADMIN_PASSWORD in .env)")

    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    @click.option("--first-name", default="System")
    @click.option("--last-name", default="Administrator")
    def create_admin(email, password, first_name, last_name):
        """Create (or promote) a user as an administrator."""
        role = Role.query.filter_by(name="admin").first()
        if not role:
            role = Role(name="admin", description="Full system access")
            db.session.add(role)
            db.session.flush()

        user = User.query.filter_by(email=email).first()
        if user:
            user.role_id = role.id
            user.password_hash = hash_password(password)
            click.echo(f"Updated existing user {email} to admin.")
        else:
            user = User(
                email=email, password_hash=hash_password(password),
                first_name=first_name, last_name=last_name, role_id=role.id,
            )
            db.session.add(user)
            click.echo(f"Created admin user {email}.")
        db.session.commit()


def _seed_roles():
    for name, desc in ROLE_DEFS:
        if not Role.query.filter_by(name=name).first():
            db.session.add(Role(name=name, description=desc))
    db.session.flush()


def _seed_admin(app):
    role = Role.query.filter_by(name="admin").first()
    email = app.config["DEFAULT_ADMIN_EMAIL"]
    admin = User.query.filter_by(email=email).first()
    if not admin:
        admin = User(
            email=email,
            password_hash=hash_password(app.config["DEFAULT_ADMIN_PASSWORD"]),
            first_name="System",
            last_name="Administrator",
            role_id=role.id,
        )
        db.session.add(admin)
        db.session.flush()
    return admin


def _seed_departments():
    names = ["Cardiology", "Neurology", "Orthopedics", "Pediatrics", "General Medicine", "Emergency"]
    depts = {}
    for n in names:
        d = Department.query.filter_by(name=n).first()
        if not d:
            d = Department(name=n, description=f"{n} department")
            db.session.add(d)
            db.session.flush()
        depts[n] = d
    return depts


def _seed_hospital_settings(app):
    defaults = {
        "hospital_name": app.config["APP_NAME"],
        "hospital_phone": "+1 (555) 010-0100",
        "hospital_address": "123 Wellness Ave, Springfield",
        "appointment_slot_minutes": "20",
    }
    for k, v in defaults.items():
        if not HospitalSetting.query.filter_by(key=k).first():
            db.session.add(HospitalSetting(key=k, value=v))


def _seed_demo_doctors(depts):
    role = Role.query.filter_by(name="doctor").first()
    demo = [
        ("Alicia", "Wren", "alicia.wren@hospital.com", "Cardiology", "Cardiologist"),
        ("Marcus", "Odei", "marcus.odei@hospital.com", "Neurology", "Neurologist"),
        ("Priya", "Nair", "priya.nair@hospital.com", "Pediatrics", "Pediatrician"),
    ]
    for fn, ln, email, dept, spec in demo:
        if User.query.filter_by(email=email).first():
            continue
        u = User(email=email, password_hash=hash_password("Doctor123!"), first_name=fn, last_name=ln, role_id=role.id)
        db.session.add(u)
        db.session.flush()
        doc = Doctor(
            user_id=u.id, department_id=depts[dept].id, specialization=spec,
            license_number=f"LIC-{u.id[:8].upper()}", years_experience=8, consultation_fee=75,
        )
        db.session.add(doc)
        db.session.flush()
        for day in range(0, 5):  # Mon-Fri
            db.session.add(DoctorSchedule(
                doctor_id=doc.id, day_of_week=day,
                start_time=time(9, 0), end_time=time(17, 0), slot_minutes=20,
            ))


def _seed_demo_patients():
    demo = [
        ("John", "Carter", date(1985, 4, 12), "Male", "O+"),
        ("Maria", "Lopez", date(1992, 9, 3), "Female", "A-"),
    ]
    for i, (fn, ln, dob, gender, bg) in enumerate(demo, start=1):
        code = f"PT-{i:06d}"
        if Patient.query.filter_by(patient_code=code).first():
            continue
        db.session.add(Patient(
            patient_code=code, first_name=fn, last_name=ln, date_of_birth=dob,
            gender=gender, blood_group=bg, phone="+1-555-0100",
        ))
