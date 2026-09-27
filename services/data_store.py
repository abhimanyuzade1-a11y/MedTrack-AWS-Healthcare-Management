"""Repository contract and local SQLite implementation for MedTrack."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from uuid import uuid4
from datetime import datetime, timezone


class DataStoreError(RuntimeError):
    """Safe, user-facing indication that a persistence operation failed."""


class DuplicateEmailError(ValueError):
    """Raised when an account already owns the normalized email address."""


class AppointmentConflictError(ValueError):
    """Raised when a patient or doctor already has that appointment slot."""


class DataStore(Protocol):
    """Operations required by routes and domain services.

    Implementations return plain dictionaries and lists so the application does
    not depend on a particular database SDK or SQL query shape.
    """

    def user_by_email(self, email: str): ...
    def user(self, user_id: str): ...
    def create_user(self, role: str, name: str, email: str, password_hash: str,
                    phone: str = "", date_of_birth: str = "", specialty: str = ""): ...
    def update_patient(self, user_id: str, name: str, phone: str, date_of_birth: str) -> None: ...
    def doctors(self) -> list[dict]: ...
    def appointment(self, appointment_id: str): ...
    def appointments_for_patient(self, patient_id: str) -> list[dict]: ...
    def appointments_for_doctor(self, doctor_id: str) -> list[dict]: ...
    def appointment_conflict(self, patient_id: str, doctor_id: str, appointment_at: str) -> bool: ...
    def create_appointment(self, patient_id: str, doctor_id: str, appointment_at: str, reason: str) -> str: ...
    def update_appointment_status(self, appointment_id: str, status: str) -> None: ...
    def diagnoses_for_patient(self, patient_id: str) -> list[dict]: ...
    def diagnoses_for_doctor(self, doctor_id: str) -> list[dict]: ...
    def add_diagnosis(self, appointment_id: str, patient_id: str, doctor_id: str,
                      diagnosis: str, notes: str) -> str: ...
    def add_diagnosis_and_complete_appointment(self, appointment_id: str, patient_id: str,
                                               doctor_id: str, diagnosis: str, notes: str,
                                               complete_appointment: bool, observations: str = "",
                                               followup_date: str = "", followup_notes: str = "") -> str: ...
    def create_vital(self, patient_id: str, recorded_by: str, recorded_at: str, blood_pressure: str,
                     heart_rate: str, temperature: str, weight: str, spo2: str, appointment_id: str = "") -> str: ...
    def vitals_for_patient(self, patient_id: str) -> list[dict]: ...
    def upsert_intake(self, patient_id: str, appointment_id: str, fields: dict) -> str: ...
    def intake_for_appointment(self, appointment_id: str): ...
    def create_followup(self, patient_id: str, doctor_id: str, appointment_id: str,
                        followup_date: str, reason: str, notes: str, status: str = "Scheduled") -> str: ...
    def followups_for_patient(self, patient_id: str) -> list[dict]: ...
    def followups_for_doctor(self, doctor_id: str) -> list[dict]: ...
    def update_followup_status(self, followup_id: str, status: str) -> None: ...
    def add_timeline_event(self, patient_id: str, event_type: str, event_time: str,
                           related_id: str, title: str, description: str, doctor_id: str = "") -> str: ...
    def timeline_for_patient(self, patient_id: str) -> list[dict]: ...
    def create_notification(self, user_id: str, event_type: str, title: str,
                            message: str, related_id: str = "") -> str: ...
    def notifications_for_user(self, user_id: str) -> list[dict]: ...


class SQLiteDataStore:
    """SQLite repository for local development; no AWS services are required."""

    def __init__(self, database_path: str):
        self.path = Path(database_path)

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as db:
            existing = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
            if existing:
                columns = {row["name"]: row["type"].upper() for row in db.execute("PRAGMA table_info(users)")}
                if columns.get("id") != "TEXT":
                    raise RuntimeError(
                        "This SQLite database uses the legacy integer-ID schema and was left unchanged. "
                        "Back it up, then set MEDTRACK_DATABASE_PATH to a new database path for this UUID-based version."
                    )
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('patient','doctor')),
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    date_of_birth TEXT NOT NULL DEFAULT '',
                    specialty TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS appointments (
                    id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL REFERENCES users(id),
                    doctor_id TEXT NOT NULL REFERENCES users(id),
                    appointment_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pending'
                        CHECK(status IN ('Pending','Confirmed','Completed','Cancelled')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_appointments_patient_time
                    ON appointments(patient_id, appointment_at);
                CREATE INDEX IF NOT EXISTS idx_appointments_doctor_time
                    ON appointments(doctor_id, appointment_at);
                CREATE TABLE IF NOT EXISTS diagnoses (
                    id TEXT PRIMARY KEY,
                    appointment_id TEXT NOT NULL REFERENCES appointments(id),
                    patient_id TEXT NOT NULL REFERENCES users(id),
                    doctor_id TEXT NOT NULL REFERENCES users(id),
                    diagnosis TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_diagnoses_patient_created
                    ON diagnoses(patient_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_diagnoses_doctor_created
                    ON diagnoses(doctor_id, created_at);
            """)
            diagnosis_columns = {row[1] for row in db.execute("PRAGMA table_info(diagnoses)")}
            for column in ("observations", "followup_date", "followup_notes"):
                if column not in diagnosis_columns:
                    db.execute(f"ALTER TABLE diagnoses ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS health_vitals (
                    id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES users(id),
                    recorded_by TEXT NOT NULL REFERENCES users(id), doctor_id TEXT NOT NULL DEFAULT '',
                    appointment_id TEXT NOT NULL DEFAULT '',
                    recorded_at TEXT NOT NULL, blood_pressure TEXT NOT NULL DEFAULT '',
                    heart_rate TEXT NOT NULL DEFAULT '', temperature TEXT NOT NULL DEFAULT '',
                    weight TEXT NOT NULL DEFAULT '', spo2 TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_vitals_patient_time ON health_vitals(patient_id, recorded_at);
                CREATE TABLE IF NOT EXISTS pre_visit_intakes (
                    id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES users(id),
                    appointment_id TEXT NOT NULL UNIQUE REFERENCES appointments(id),
                    main_concern TEXT NOT NULL, symptoms TEXT NOT NULL DEFAULT '', duration TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT '', allergies TEXT NOT NULL DEFAULT '',
                    medications TEXT NOT NULL DEFAULT '', additional_notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intakes_patient_time ON pre_visit_intakes(patient_id, created_at);
                CREATE TABLE IF NOT EXISTS followups (
                    id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES users(id),
                    doctor_id TEXT NOT NULL REFERENCES users(id), appointment_id TEXT NOT NULL DEFAULT '',
                    followup_date TEXT NOT NULL, reason TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('Scheduled','Completed','Pending')),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_followups_patient_date ON followups(patient_id, followup_date);
                CREATE INDEX IF NOT EXISTS idx_followups_doctor_date ON followups(doctor_id, followup_date);
                CREATE TABLE IF NOT EXISTS timeline_events (
                    id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES users(id),
                    doctor_id TEXT NOT NULL DEFAULT '', event_type TEXT NOT NULL, event_time TEXT NOT NULL,
                    related_id TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_timeline_patient_time ON timeline_events(patient_id, event_time);
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    event_type TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL,
                    related_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, read_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_user_time ON notifications(user_id, created_at);
            """)
            vital_columns = {row["name"] for row in db.execute("PRAGMA table_info(health_vitals)")}
            if "doctor_id" not in vital_columns:
                db.execute("ALTER TABLE health_vitals ADD COLUMN doctor_id TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _dict(row):
        return dict(row) if row else None

    def doctors(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name,specialty FROM users WHERE role='doctor' ORDER BY name").fetchall()]

    def user_by_email(self, email):
        with self._connect() as db:
            return self._dict(db.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone())

    def user(self, user_id):
        with self._connect() as db:
            return self._dict(db.execute(
                "SELECT id,role,name,email,phone,date_of_birth,specialty,created_at FROM users WHERE id=?",
                (str(user_id),)).fetchone())

    def create_user(self, role, name, email, password_hash, phone="", date_of_birth="", specialty=""):
        user_id = str(uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO users(id,role,name,email,password_hash,phone,date_of_birth,specialty) VALUES(?,?,?,?,?,?,?,?)",
                       (user_id,role,name,email,password_hash,phone,date_of_birth,specialty))
        return user_id

    def update_patient(self, user_id, name, phone, date_of_birth):
        with self._connect() as db:
            db.execute("UPDATE users SET name=?,phone=?,date_of_birth=? WHERE id=? AND role='patient'",
                       (name,phone,date_of_birth,str(user_id)))

    def _appointment_sql(self):
        return """SELECT a.*, p.name patient_name,p.email patient_email,p.phone patient_phone,
                  d.name doctor_name,d.specialty doctor_specialty
                  FROM appointments a JOIN users p ON p.id=a.patient_id
                  JOIN users d ON d.id=a.doctor_id"""

    def appointment(self, appointment_id):
        with self._connect() as db:
            return self._dict(db.execute(self._appointment_sql() + " WHERE a.id=?", (str(appointment_id),)).fetchone())

    def appointments_for_patient(self, patient_id):
        with self._connect() as db:
            rows = db.execute(self._appointment_sql() + " WHERE a.patient_id=? ORDER BY a.appointment_at DESC",
                              (str(patient_id),)).fetchall()
            return [dict(row) for row in rows]

    def appointments_for_doctor(self, doctor_id):
        with self._connect() as db:
            rows = db.execute(self._appointment_sql() + " WHERE a.doctor_id=? ORDER BY a.appointment_at DESC",
                              (str(doctor_id),)).fetchall()
            return [dict(row) for row in rows]

    def appointment_conflict(self, patient_id, doctor_id, appointment_at):
        with self._connect() as db:
            row = db.execute("""SELECT id FROM appointments
                WHERE appointment_at=? AND status IN ('Pending','Confirmed')
                AND (patient_id=? OR doctor_id=?) LIMIT 1""",
                             (appointment_at,str(patient_id),str(doctor_id))).fetchone()
            return row is not None

    def create_appointment(self, patient_id, doctor_id, appointment_at, reason):
        appointment_id = str(uuid4())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conflict = db.execute("""SELECT 1 FROM appointments
                WHERE appointment_at=? AND status IN ('Pending','Confirmed')
                AND (patient_id=? OR doctor_id=?) LIMIT 1""",
                                  (appointment_at,str(patient_id),str(doctor_id))).fetchone()
            if conflict:
                raise AppointmentConflictError("That appointment time is no longer available.")
            db.execute("INSERT INTO appointments(id,patient_id,doctor_id,appointment_at,reason) VALUES(?,?,?,?,?)",
                       (appointment_id,str(patient_id),str(doctor_id),appointment_at,reason))
        return appointment_id

    def update_appointment_status(self, appointment_id, status):
        with self._connect() as db:
            db.execute("UPDATE appointments SET status=? WHERE id=?", (status,str(appointment_id)))

    def _diagnoses(self, where, value):
        sql = """SELECT x.*,d.name doctor_name,p.name patient_name,a.appointment_at
                 FROM diagnoses x JOIN users d ON d.id=x.doctor_id
                 JOIN users p ON p.id=x.patient_id JOIN appointments a ON a.id=x.appointment_id
                 WHERE x.""" + where + "=? ORDER BY x.created_at DESC"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, (str(value),)).fetchall()]

    def diagnoses_for_patient(self, patient_id):
        return self._diagnoses("patient_id", patient_id)

    def diagnoses_for_doctor(self, doctor_id):
        return self._diagnoses("doctor_id", doctor_id)

    def add_diagnosis(self, appointment_id, patient_id, doctor_id, diagnosis, notes):
        return self.add_diagnosis_and_complete_appointment(
            appointment_id, patient_id, doctor_id, diagnosis, notes, False)

    def add_diagnosis_and_complete_appointment(self, appointment_id, patient_id, doctor_id,
                                               diagnosis, notes, complete_appointment,
                                               observations="", followup_date="", followup_notes=""):
        diagnosis_id = str(uuid4())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            appointment = db.execute("SELECT patient_id,doctor_id FROM appointments WHERE id=?",
                                     (str(appointment_id),)).fetchone()
            if not appointment or appointment["patient_id"] != str(patient_id) or appointment["doctor_id"] != str(doctor_id):
                raise DataStoreError("The appointment could not be found for this diagnosis.")
            db.execute("INSERT INTO diagnoses(id,appointment_id,patient_id,doctor_id,diagnosis,notes,observations,followup_date,followup_notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (diagnosis_id,str(appointment_id),str(patient_id),str(doctor_id),diagnosis,notes,
                        observations,followup_date,followup_notes,self._now()))
            if complete_appointment:
                cursor = db.execute("UPDATE appointments SET status='Completed' WHERE id=? AND status IN ('Pending','Confirmed')",
                                    (str(appointment_id),))
                if cursor.rowcount != 1:
                    raise DataStoreError("The appointment status changed before the diagnosis was saved.")
        return diagnosis_id

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def create_vital(self, patient_id, recorded_by, recorded_at, blood_pressure, heart_rate,
                     temperature, weight, spo2, appointment_id=""):
        vital_id = str(uuid4())
        with self._connect() as db:
            doctor_id = str(recorded_by) if str(recorded_by) != str(patient_id) else ""
            db.execute("INSERT INTO health_vitals(id,patient_id,recorded_by,doctor_id,appointment_id,recorded_at,blood_pressure,heart_rate,temperature,weight,spo2) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (vital_id,str(patient_id),str(recorded_by),doctor_id,str(appointment_id),recorded_at,
                        blood_pressure,heart_rate,temperature,weight,spo2))
        return vital_id

    def vitals_for_patient(self, patient_id):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM health_vitals WHERE patient_id=? ORDER BY recorded_at DESC", (str(patient_id),)).fetchall()]

    def upsert_intake(self, patient_id, appointment_id, fields):
        intake_id = str(uuid4())
        created_at = self._now()
        with self._connect() as db:
            existing = db.execute("SELECT id FROM pre_visit_intakes WHERE appointment_id=?", (str(appointment_id),)).fetchone()
            if existing:
                intake_id = existing["id"]
                db.execute("UPDATE pre_visit_intakes SET main_concern=?,symptoms=?,duration=?,severity=?,allergies=?,medications=?,additional_notes=?,created_at=? WHERE appointment_id=? AND patient_id=?",
                           (fields["main_concern"],fields["symptoms"],fields["duration"],fields["severity"],fields["allergies"],fields["medications"],fields["additional_notes"],created_at,str(appointment_id),str(patient_id)))
            else:
                db.execute("INSERT INTO pre_visit_intakes(id,patient_id,appointment_id,main_concern,symptoms,duration,severity,allergies,medications,additional_notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (intake_id,str(patient_id),str(appointment_id),fields["main_concern"],fields["symptoms"],fields["duration"],fields["severity"],fields["allergies"],fields["medications"],fields["additional_notes"],created_at))
        return intake_id

    def intake_for_appointment(self, appointment_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM pre_visit_intakes WHERE appointment_id=?", (str(appointment_id),)).fetchone()
            return self._dict(row)

    def create_followup(self, patient_id, doctor_id, appointment_id, followup_date, reason, notes, status="Scheduled"):
        followup_id = str(uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO followups(id,patient_id,doctor_id,appointment_id,followup_date,reason,notes,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (followup_id,str(patient_id),str(doctor_id),str(appointment_id),followup_date,reason,notes,status,self._now()))
        return followup_id

    def followups_for_patient(self, patient_id):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT f.*,u.name doctor_name,u.specialty doctor_specialty FROM followups f JOIN users u ON u.id=f.doctor_id WHERE f.patient_id=? ORDER BY f.followup_date DESC", (str(patient_id),)).fetchall()]

    def followups_for_doctor(self, doctor_id):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT f.*,u.name patient_name FROM followups f JOIN users u ON u.id=f.patient_id WHERE f.doctor_id=? ORDER BY f.followup_date DESC", (str(doctor_id),)).fetchall()]

    def update_followup_status(self, followup_id, status):
        with self._connect() as db:
            db.execute("UPDATE followups SET status=? WHERE id=?", (status,str(followup_id)))

    def add_timeline_event(self, patient_id, event_type, event_time, related_id, title, description, doctor_id=""):
        event_id = str(uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO timeline_events(id,patient_id,doctor_id,event_type,event_time,related_id,title,description) VALUES(?,?,?,?,?,?,?,?)",
                       (event_id,str(patient_id),str(doctor_id),event_type,event_time,str(related_id),title,description))
        return event_id

    def timeline_for_patient(self, patient_id):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM timeline_events WHERE patient_id=? ORDER BY event_time DESC", (str(patient_id),)).fetchall()]

    def create_notification(self, user_id, event_type, title, message, related_id=""):
        notification_id = str(uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO notifications(id,user_id,event_type,title,message,related_id,created_at) VALUES(?,?,?,?,?,?,?)",
                       (notification_id,str(user_id),event_type,title,message,str(related_id),self._now()))
        return notification_id

    def notifications_for_user(self, user_id):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC", (str(user_id),)).fetchall()]
