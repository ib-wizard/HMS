# MediCore HMS — Hospital Management System

A Hospital Management System built with a Flask + PostgreSQL REST API backend
and a vanilla HTML/CSS/JS frontend (one self-contained file per page).

> **Scope note:** This delivery (Phase 1) fully implements **Authentication &
> RBAC, Admin Dashboard, Department Management, Doctor Management, Patient
> Management, and Appointment Management** end-to-end — real database, real
> API, real UI, no placeholders. The full database schema for the remaining
> modules (Pharmacy, Laboratory, Billing, Ward/Bed Management, Nursing,
> Emergency, Notifications, File Management, Reports) is already in place in
> `app/models.py` so they can be added as additional blueprints without
> breaking migrations. See **"Roadmap"** at the bottom for what's next.

---

## 1. Tech stack

| Layer      | Technology |
|------------|------------|
| Frontend   | HTML5 + CSS3 + vanilla JavaScript (one file per page, no build step) |
| Backend    | Python 3.12, Flask 3, SQLAlchemy 2, Flask-Migrate, Flask-JWT-Extended |
| Database   | PostgreSQL 14+ |
| Auth       | JWT (access + refresh tokens), bcrypt password hashing, RBAC |
| Deployment | Gunicorn, Docker / docker-compose, Render / Railway / Fly.io / any VPS |

---

## 2. Project structure

```
hms/
├── app/
│   ├── __init__.py            # Application factory
│   ├── extensions.py          # Shared Flask extension instances
│   ├── models.py              # Full SQLAlchemy schema (all 14 modules)
│   ├── cli.py                 # `flask seed-db`, `flask create-admin`
│   ├── auth/routes.py         # Login, logout, forgot/reset password
│   ├── admin/routes.py        # Dashboard, users, departments, audit logs
│   ├── patients/routes.py     # Registration, profile, medical history, admit/discharge
│   ├── doctors/routes.py      # Doctor profiles, schedules
│   ├── appointments/routes.py # Booking, reschedule, cancel, queue, slots
│   └── utils/
│       ├── security.py        # bcrypt hashing, password/email validation
│       └── decorators.py      # @roles_required, audit log helper
├── frontend/                  # Self-contained HTML/CSS/JS pages
│   ├── login.html
│   ├── forgot-password.html
│   ├── admin-dashboard.html
│   ├── patients.html
│   ├── doctors.html
│   └── appointments.html
├── scripts/
│   ├── init_db.sh             # First-time DB setup (migrate + seed)
│   └── start.sh                # Production start (migrate + gunicorn)
├── config.py                  # Env-driven configuration
├── run.py                     # WSGI entry point
├── gunicorn_config.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── runtime.txt
├── Procfile
├── .env.example
└── .gitignore
```

---

## 3. Local setup (without Docker)

### Prerequisites
- Python 3.12+
- PostgreSQL 14+ running locally (or a remote connection string)

### Steps

```bash
# 1. Clone and enter the project
cd hms

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env: set SECRET_KEY, JWT_SECRET_KEY, DATABASE_URL, DEFAULT_ADMIN_PASSWORD

# 5. Create the database (if it doesn't exist yet)
createdb hms_db   # or via psql: CREATE DATABASE hms_db;

# 6. Run migrations and seed data
chmod +x scripts/*.sh
./scripts/init_db.sh

# 7. Start the dev server
python run.py
```

The app will be available at **http://localhost:5000**.

Default admin login (from `.env`):
- Email: value of `DEFAULT_ADMIN_EMAIL` (default `admin@hospital.com`)
- Password: value of `DEFAULT_ADMIN_PASSWORD` (**change this in production**)

Seeded demo doctors (password `Doctor123!`):
- alicia.wren@hospital.com (Cardiology)
- marcus.odei@hospital.com (Neurology)
- priya.nair@hospital.com (Pediatrics)

---

## 4. Local setup with Docker (recommended)

```bash
cp .env.example .env
# Edit .env as needed — docker-compose reads SECRET_KEY, JWT_SECRET_KEY, etc.

docker compose up --build
```

This starts PostgreSQL and the Flask app together, automatically runs
migrations, and seeds the database on first boot. Visit **http://localhost:5000**.

---

## 5. Environment variables

See `.env.example` for the full list with descriptions. Key variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session/signing secret |
| `JWT_SECRET_KEY` | Signs access/refresh tokens — must be different from `SECRET_KEY` |
| `DATABASE_URL` | PostgreSQL connection string |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend origins |
| `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` | Seeded on `flask seed-db` |
| `RATE_LIMIT_STORAGE_URI` | Use `redis://...` in production (default `memory://` is dev-only) |
| `FORCE_HTTPS` | Set `1` in production to enforce HTTPS via Flask-Talisman |

**Never commit your real `.env` file.** It is already excluded via `.gitignore`.

---

## 6. Database

- All tables use UUID primary keys.
- Foreign keys and indexes are defined directly in `app/models.py`.
- Soft deletes (`is_active` flags) are used for patients and users to preserve
  audit/history integrity — records are deactivated, not hard-deleted.
- Migrations are managed with Flask-Migrate/Alembic:

```bash
flask db migrate -m "Description of change"
flask db upgrade
```

- `flask seed-db` seeds: roles, a default admin, hospital departments,
  default hospital settings, 3 demo doctors with weekday schedules, and 2
  demo patients.

---

## 7. API overview

All endpoints are prefixed with `/api`. Authenticated requests use
`Authorization: Bearer <access_token>`.

### Auth (`/api/auth`)
| Method | Path | Description |
|---|---|---|
| POST | `/login` | Returns access + refresh JWT and user profile |
| POST | `/refresh` | Exchange a refresh token for a new access token |
| POST | `/logout` | Revokes the current access token |
| GET  | `/me` | Current authenticated user |
| POST | `/forgot-password` | Issues a password reset token |
| POST | `/reset-password` | Consumes a reset token, sets new password |
| POST | `/change-password` | Authenticated password change |

### Admin (`/api/admin`) — role: `admin`
| Method | Path | Description |
|---|---|---|
| GET | `/dashboard` | Totals, 7-day appointment trend, department load |
| GET/POST | `/users` | List / create staff users |
| PUT/DELETE | `/users/<id>` | Update / deactivate a user |
| GET | `/roles` | List all roles |
| GET/POST | `/departments` | List (any authenticated user) / create (admin) |
| PUT/DELETE | `/departments/<id>` | Update / delete a department |
| GET | `/audit-logs` | Paginated system audit trail |

### Patients (`/api/patients`) — roles: `admin`, `receptionist`, `nurse`, `doctor` (varies by action)
| Method | Path | Description |
|---|---|---|
| GET | `/` | Search/list patients |
| POST | `/` | Register a new patient |
| GET/PUT/DELETE | `/<id>` | Profile detail / update / deactivate |
| POST | `/<id>/medical-records` | Add diagnosis + prescriptions |
| POST | `/<id>/admit` | Admit to a ward/bed |
| POST | `/admissions/<id>/discharge` | Discharge with summary |

### Doctors (`/api/doctors`)
| Method | Path | Description |
|---|---|---|
| GET | `/` | List/search doctors |
| POST | `/` | Create doctor (creates linked user account) — admin only |
| GET/PUT | `/<id>` | Profile detail / update |
| GET/POST | `/<id>/schedules` | Weekly availability |
| DELETE | `/schedules/<id>` | Remove a schedule slot |

### Appointments (`/api/appointments`)
| Method | Path | Description |
|---|---|---|
| GET | `/` | List/filter appointments |
| GET | `/available-slots` | Free slots for a doctor on a given date |
| POST | `/` | Book an appointment |
| POST | `/<id>/reschedule` | Change time |
| POST | `/<id>/cancel` | Cancel with reason |
| PATCH | `/<id>/status` | Update status (checked-in, in-progress, completed, no-show…) |
| GET | `/queue` | Today's live queue, ordered by queue number |

---

## 8. Security

- Passwords hashed with bcrypt (cost factor 12).
- JWT access tokens short-lived (30 min default); refresh tokens (7 days).
- Logout revokes the token via a server-side blocklist (`token_blocklist` table).
- Role-based access control enforced per-endpoint via `@roles_required(...)`.
- Rate limiting on login/password-reset endpoints (Flask-Limiter).
- Security headers + CSP via Flask-Talisman.
- CORS restricted to configured origins only.
- All user input validated server-side; SQLAlchemy ORM parameterizes queries
  (no raw SQL string interpolation, mitigating SQL injection).
- Every mutating action is written to `audit_logs` with actor, IP, and details.

**Production hardening checklist:**
- Set `FORCE_HTTPS=1` and serve behind TLS.
- Use a real `RATE_LIMIT_STORAGE_URI` (Redis) instead of in-memory.
- Rotate `SECRET_KEY` / `JWT_SECRET_KEY` and never reuse the example values.
- Configure real SMTP credentials so password-reset emails send (currently
  logged server-side; wire up `app/utils/mailer.py` when adding notifications).

---

## 9. Deployment

### Render / Railway / Fly.io
1. Push this repo to GitHub.
2. Create a PostgreSQL instance on the platform and copy its connection URL.
3. Create a new web service pointing at this repo.
4. Set environment variables from `.env.example` in the platform's dashboard.
5. Build command: `pip install -r requirements.txt`
6. Start command: `bash scripts/start.sh` (runs migrations, then Gunicorn)
   — or use the included `Procfile` directly on platforms that support it.

### Any VPS
1. Install Python 3.12, PostgreSQL, and Nginx.
2. Clone the repo, create a venv, `pip install -r requirements.txt`.
3. Configure `.env`.
4. Run `./scripts/init_db.sh` once.
5. Use the provided `gunicorn_config.py` behind Nginx as a reverse proxy
   (proxy `/` to `127.0.0.1:5000`).
6. Use systemd or supervisor to keep Gunicorn running; call
   `scripts/start.sh` as the service's `ExecStart`.

### Docker
```bash
docker compose up --build -d
```

---

## 10. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `psycopg2.OperationalError: connection refused` | PostgreSQL isn't running or `DATABASE_URL` is wrong |
| `401 Unauthorized` right after login | Check that `JWT_SECRET_KEY` didn't change between requests (e.g. multiple app instances with different `.env`) |
| Frontend shows nothing / redirects to login immediately | `localStorage` token missing or expired — sign in again |
| `flask: command not found` | Activate your virtualenv, or run `python -m flask ...` |
| CORS errors in browser console | Add your frontend origin to `CORS_ORIGINS` in `.env` |
| Migrations fail with "table already exists" | Run `flask db stamp head` if the schema was created outside of Alembic, then re-migrate |

---

## 11. Roadmap (not yet implemented in this delivery)

The schema already supports these; only the blueprints/routes + frontend
pages remain:
- Pharmacy (drug inventory, dispensing, supplier management, stock alerts)
- Laboratory (test requests, result entry, result printing)
- Billing & Finance (invoices, payments, insurance claims, financial reports)
- Ward & Bed Management UI (beds table exists; admit/discharge API exists;
  dedicated ward-management screen not yet built)
- Nurse module (assigned patients, observations, medication administration)
- Emergency module (triage, critical monitoring)
- Notifications (in-app bell + email delivery — table exists, delivery wiring pending)
- File management (patient document upload/download; PDF generation)
- Reports & analytics beyond the admin dashboard (custom report builder)

Ask for any of these next and they'll be added on top of this same
foundation — no rework required.
