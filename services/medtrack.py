"""Business operations independent of the persistence technology."""

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from werkzeug.security import check_password_hash, generate_password_hash

if TYPE_CHECKING:
    from services.data_store import DataStore


class MedTrackService:
    def __init__(self, store: "DataStore", notifications=None):
        self.store = store
        self.notifications = notifications

    @staticmethod
    def normalize_email(email):
        return email.strip().lower()

    def authenticate(self, email, password, role):
        user = self.store.user_by_email(self.normalize_email(email))
        if not user or user["role"] != role or not check_password_hash(user["password_hash"], password):
            return None
        return self.store.user(user["id"])

    def register_patient(self, name, email, password, phone, date_of_birth):
        name, email, phone = name.strip(), self.normalize_email(email), phone.strip()
        if not 2 <= len(name) <= 100:
            raise ValueError("Enter a name between 2 and 100 characters.")
        if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Enter a valid email address.")
        if not 10 <= len(password) <= 128:
            raise ValueError("Password must be between 10 and 128 characters.")
        if phone and not re.fullmatch(r"[+()0-9 .-]{7,25}", phone):
            raise ValueError("Enter a valid phone number.")
        if date_of_birth:
            try:
                if datetime.strptime(date_of_birth, "%Y-%m-%d").date() > datetime.now().date():
                    raise ValueError
            except ValueError as exc:
                raise ValueError("Enter a valid date of birth that is not in the future.") from exc
        try:
            return self.store.create_user("patient", name, email, generate_password_hash(password), phone, date_of_birth)
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("An account with that email already exists.") from exc
            raise

    def create_doctor(self, name, email, specialty, password):
        email = self.normalize_email(email)
        if (not 2 <= len(name.strip()) <= 100 or len(email) > 254 or
                not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or
                not 10 <= len(password) <= 128 or len(specialty.strip()) > 100):
            raise ValueError("Enter a valid doctor name and email.")
        try:
            return self.store.create_user("doctor", name.strip(), email,
                                          generate_password_hash(password), specialty=specialty.strip())
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("An account with that email already exists.") from exc
            raise

    def book_appointment(self, patient_id, doctor_id, appointment_at, reason):
        try:
            when = datetime.strptime(appointment_at, "%Y-%m-%dT%H:%M")
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose a valid appointment date and time.") from exc
        if when <= datetime.now():
            raise ValueError("Choose a future date and time.")
        reason = reason.strip()
        if not 5 <= len(reason) <= 500:
            raise ValueError("Reason for visit must be between 5 and 500 characters.")
        if not any(str(doctor["id"]) == str(doctor_id) for doctor in self.store.doctors()):
            raise ValueError("Choose an available doctor.")
        doctor_id = str(doctor_id)
        formatted_when = when.strftime("%Y-%m-%d %H:%M")
        if self.store.appointment_conflict(patient_id, doctor_id, formatted_when):
            raise ValueError("That time conflicts with an existing appointment. Choose another time.")
        appointment_id = self.store.create_appointment(patient_id, doctor_id, formatted_when, reason)
        doctor = next(d for d in self.store.doctors() if str(d["id"]) == doctor_id)
        self._timeline(patient_id, "appointment_requested", appointment_id,
                       "Appointment requested", f"Request sent to {doctor['name']}.", doctor_id)
        self.store.create_notification(doctor_id, "appointment_requested", "New appointment request",
                                      "A patient requested an appointment.", appointment_id)
        self._notify("appointment_request_created", appointment_id)
        return appointment_id

    def update_appointment_status(self, appointment_id, status):
        appointment = self.store.appointment(appointment_id)
        self.store.update_appointment_status(appointment_id, status)
        if appointment and appointment["status"] != status:
            titles = {"Confirmed": "Appointment confirmed", "Completed": "Consultation completed",
                      "Cancelled": "Appointment cancelled", "Pending": "Appointment updated"}
            self._timeline(appointment["patient_id"], f"appointment_{status.lower()}", appointment_id,
                           titles[status], f"Your appointment status is now {status.lower()}.", appointment["doctor_id"])
            self.store.create_notification(appointment["patient_id"], f"appointment_{status.lower()}",
                                           titles[status], f"Your appointment status is now {status.lower()}.", appointment_id)
            self._notify("appointment_status_changed", appointment_id, status)

    def _notify(self, event, appointment_id, status=None):
        if self.notifications:
            self.notifications.notify(event, appointment_id, status)

    def _timeline(self, patient_id, event_type, related_id, title, description, doctor_id=""):
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.store.add_timeline_event(patient_id, event_type, timestamp, related_id, title, description, doctor_id)

    @staticmethod
    def _bounded(value, label, maximum=500, required=False):
        value = (value or "").strip()
        if required and not value:
            raise ValueError(f"{label} is required.")
        if len(value) > maximum:
            raise ValueError(f"{label} must be {maximum} characters or fewer.")
        return value

    def submit_intake(self, patient_id, appointment, fields):
        if appointment["patient_id"] != str(patient_id) or appointment["status"] not in ("Pending", "Confirmed"):
            raise ValueError("Pre-visit information can only be added to your upcoming appointment.")
        if datetime.strptime(appointment["appointment_at"], "%Y-%m-%d %H:%M") <= datetime.now():
            raise ValueError("Pre-visit information can only be added before the appointment.")
        clean = {
            "main_concern": self._bounded(fields.get("main_concern"), "Main concern", 300, True),
            "symptoms": self._bounded(fields.get("symptoms"), "Symptoms", 1000),
            "duration": self._bounded(fields.get("duration"), "Duration", 120),
            "severity": self._bounded(fields.get("severity"), "Severity", 40),
            "allergies": self._bounded(fields.get("allergies"), "Allergies", 500),
            "medications": self._bounded(fields.get("medications"), "Current medications", 500),
            "additional_notes": self._bounded(fields.get("additional_notes"), "Additional notes", 1000),
        }
        intake_id = self.store.upsert_intake(patient_id, appointment["id"], clean)
        self._timeline(patient_id, "intake_submitted", appointment["id"], "Pre-visit information updated",
                       "Your structured information is available to your doctor.", appointment["doctor_id"])
        self.store.create_notification(appointment["doctor_id"], "intake_submitted", "Pre-visit information available",
                                       "A patient submitted pre-visit information.", appointment["id"])
        return intake_id

    def record_vitals(self, patient_id, recorded_by, values, appointment_id=""):
        clean = self._validate_vitals(values)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        vital_id = self.store.create_vital(patient_id, recorded_by, timestamp, **clean, appointment_id=appointment_id)
        self._timeline(patient_id, "vital_recorded", vital_id, "Vitals recorded",
                       "A set of health readings was added to the snapshot.",
                       recorded_by if recorded_by != patient_id else "")
        return vital_id

    @staticmethod
    def _validate_vitals(values):
        names = ("blood_pressure", "heart_rate", "temperature", "weight", "spo2")
        clean = {name: MedTrackService._bounded(values.get(name), name.replace("_", " ").title(), 24) for name in names}
        if not any(clean.values()):
            raise ValueError("Enter at least one vital reading.")
        for field, low, high in (("heart_rate", 20, 250), ("temperature", 25, 45),
                                 ("weight", 1, 500), ("spo2", 1, 100)):
            if clean[field]:
                try:
                    value = float(clean[field])
                except ValueError as exc:
                    raise ValueError(f"Enter a numeric value for {field.replace('_', ' ')}.") from exc
                if not low <= value <= high:
                    raise ValueError(f"Enter a plausible recorded value for {field.replace('_', ' ')}.")
        if clean["blood_pressure"] and not re.fullmatch(r"\d{2,3}/\d{2,3}", clean["blood_pressure"]):
            raise ValueError("Enter blood pressure in systolic/diastolic format, for example 120/80.")
        return clean

    def create_followup(self, patient_id, doctor_id, appointment_id, followup_date, reason, notes):
        try:
            parsed = datetime.strptime(followup_date, "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose a valid follow-up date.") from exc
        if parsed < datetime.now().date():
            raise ValueError("Choose a current or future follow-up date.")
        reason = self._bounded(reason, "Follow-up reason", 300, True)
        notes = self._bounded(notes, "Follow-up notes", 1000)
        followup_id = self.store.create_followup(patient_id, doctor_id, appointment_id,
                                                 parsed.isoformat(), reason, notes, "Scheduled")
        self._timeline(patient_id, "followup_created", followup_id, "Follow-up scheduled",
                       "A follow-up was added to your care plan.", doctor_id)
        self.store.create_notification(patient_id, "followup_created", "Follow-up scheduled",
                                       "A follow-up has been added to your care plan.", followup_id)
        return followup_id

    def update_followup_status(self, followup, status):
        if status not in {"Scheduled", "Completed", "Pending"}:
            raise ValueError("Choose a valid follow-up status.")
        self.store.update_followup_status(followup["id"], status)
        if followup["status"] != status:
            self._timeline(followup["patient_id"], "followup_status_changed", followup["id"],
                           "Follow-up updated", f"Follow-up status changed to {status.lower()}.", followup["doctor_id"])
            self.store.create_notification(followup["patient_id"], "followup_status_changed", "Follow-up updated",
                                           f"Your follow-up status is now {status.lower()}.", followup["id"])

    def submit_diagnosis(self, appointment, diagnosis, notes, observations="", followup_date="",
                         followup_notes="", vitals=None):
        diagnosis, notes = diagnosis.strip(), notes.strip()
        observations = self._bounded(observations, "Observations", 2000)
        followup_notes = self._bounded(followup_notes, "Follow-up notes", 1000)
        if not 3 <= len(diagnosis) <= 300:
            raise ValueError("Diagnosis must be between 3 and 300 characters.")
        if len(notes) > 2000:
            raise ValueError("Notes must be 2,000 characters or fewer.")
        if followup_date:
            try:
                if datetime.strptime(followup_date, "%Y-%m-%d").date() < datetime.now().date():
                    raise ValueError
            except ValueError as exc:
                raise ValueError("Choose a valid current or future follow-up date.") from exc
        clean_vitals = self._validate_vitals(vitals) if vitals and any((value or "").strip() for value in vitals.values()) else None
        self.store.add_diagnosis_and_complete_appointment(
            appointment["id"], appointment["patient_id"], appointment["doctor_id"],
            diagnosis, notes, appointment["status"] in ("Pending", "Confirmed"),
            observations, followup_date, followup_notes)
        self._timeline(appointment["patient_id"], "diagnosis_recorded", appointment["id"],
                       "Consultation record added", "Your doctor added a record to this visit.", appointment["doctor_id"])
        self.store.create_notification(appointment["patient_id"], "diagnosis_recorded", "New health record available",
                                       "Your doctor added a record to your health history.", appointment["id"])
        if clean_vitals:
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            vital_id = self.store.create_vital(appointment["patient_id"], appointment["doctor_id"], timestamp,
                                               **clean_vitals, appointment_id=appointment["id"])
            self._timeline(appointment["patient_id"], "vital_recorded", vital_id, "Vitals recorded",
                           "A set of health readings was added to the snapshot.", appointment["doctor_id"])
        if followup_date:
            self.create_followup(appointment["patient_id"], appointment["doctor_id"], appointment["id"],
                                 followup_date, "Recommended follow-up", followup_notes)
        if appointment["status"] in ("Pending", "Confirmed"):
            self._timeline(appointment["patient_id"], "appointment_completed", appointment["id"],
                           "Consultation completed", "The appointment was marked complete.", appointment["doctor_id"])
            self._notify("appointment_status_changed", appointment["id"], "Completed")

    @staticmethod
    def can_cancel(appointment):
        return appointment["status"] in ("Pending", "Confirmed") and datetime.strptime(appointment["appointment_at"], "%Y-%m-%d %H:%M") > datetime.now()
