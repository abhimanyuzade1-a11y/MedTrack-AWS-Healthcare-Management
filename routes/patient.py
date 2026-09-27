"""Patient dashboard and self-service routes."""

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
import re
from datetime import datetime

from routes.auth import login_required

patient_bp = Blueprint("patient", __name__)


def service():
    return current_app.extensions["medtrack_service"]


@patient_bp.get("/")
@patient_bp.get("/dashboard")
@login_required("patient")
def dashboard():
    user = session["user"]
    appointments = service().store.appointments_for_patient(user["id"])
    diagnoses = service().store.diagnoses_for_patient(user["id"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    upcoming = sorted((a for a in appointments if a["status"] in ("Pending", "Confirmed") and a["appointment_at"] >= now), key=lambda a: a["appointment_at"])
    followups = sorted(service().store.followups_for_patient(user["id"]), key=lambda item: item["followup_date"])
    vitals = service().store.vitals_for_patient(user["id"])
    timeline = service().store.timeline_for_patient(user["id"])
    notifications = service().store.notifications_for_user(user["id"])
    return render_template("patient/dashboard.html", appointments=upcoming[:4], diagnoses=diagnoses[:3],
                           diagnosis_count=len(diagnoses), appointment_count=len(upcoming),
                           followups=followups, vitals=vitals, timeline=timeline[:6],
                           notification_count=len(notifications))


@patient_bp.get("/timeline")
@login_required("patient")
def timeline():
    store = service().store
    return render_template("patient/timeline.html", events=store.timeline_for_patient(session["user"]["id"]))


@patient_bp.route("/health", methods=["GET", "POST"])
@login_required("patient")
def health_snapshot():
    if request.method == "POST":
        try:
            service().record_vitals(session["user"]["id"], session["user"]["id"], request.form)
            flash("Your readings were added to the health snapshot.", "success")
            return redirect(url_for("patient.health_snapshot"))
        except ValueError as exc:
            flash(str(exc), "danger")
    readings = service().store.vitals_for_patient(session["user"]["id"])
    return render_template("patient/health.html", readings=readings)


@patient_bp.route("/appointments/<appointment_id>/intake", methods=["GET", "POST"])
@login_required("patient")
def intake(appointment_id):
    store = service().store
    appointment = store.appointment(appointment_id)
    if not appointment or appointment["patient_id"] != session["user"]["id"]:
        return render_template("errors/error.html", error=type("NotFound", (), {"code": 404, "description": "Appointment not found."})()), 404
    if request.method == "POST":
        try:
            service().submit_intake(session["user"]["id"], appointment, request.form)
            flash("Your pre-visit information is available to your doctor.", "success")
            return redirect(url_for("patient.intake", appointment_id=appointment_id))
        except ValueError as exc:
            flash(str(exc), "danger")
    return render_template("patient/intake.html", appointment=appointment,
                           intake=store.intake_for_appointment(appointment_id))


@patient_bp.get("/followups")
@login_required("patient")
def followups():
    return render_template("patient/followups.html", followups=service().store.followups_for_patient(session["user"]["id"]))


@patient_bp.get("/notifications")
@login_required("patient")
def notifications():
    return render_template("shared/notifications.html", notifications=service().store.notifications_for_user(session["user"]["id"]))


@patient_bp.route("/appointments", methods=["GET", "POST"])
@login_required("patient")
def appointments():
    if request.method == "POST":
        appointment = service().store.appointment(request.form.get("appointment_id", ""))
        if appointment and appointment["patient_id"] == session["user"]["id"] and service().can_cancel(appointment):
            service().update_appointment_status(appointment["id"], "Cancelled")
            flash("Appointment cancelled.", "success")
        else:
            flash("This appointment cannot be cancelled.", "warning")
        return redirect(url_for("patient.appointments"))
    appointments = service().store.appointments_for_patient(session["user"]["id"])
    for appointment in appointments:
        appointment["has_intake"] = bool(service().store.intake_for_appointment(appointment["id"]))
    return render_template("appointments/list.html", appointments=appointments, patient_view=True)


@patient_bp.route("/appointments/book", methods=["GET", "POST"])
@login_required("patient")
def book_appointment():
    if request.method == "POST":
        try:
            service().book_appointment(session["user"]["id"], request.form.get("doctor_id", ""),
                                       request.form.get("appointment_at", ""), request.form.get("reason", ""))
            flash("Your appointment request has been sent. It is pending doctor confirmation.", "success")
            return redirect(url_for("patient.appointments"))
        except (ValueError, TypeError) as exc:
            flash(str(exc), "danger")
    doctors = service().store.doctors()
    return render_template("appointments/book.html", doctors=doctors)


@patient_bp.get("/history")
@login_required("patient")
def history():
    return render_template("patient/history.html", diagnoses=service().store.diagnoses_for_patient(session["user"]["id"]))


@patient_bp.route("/profile", methods=["GET", "POST"])
@login_required("patient")
def profile():
    store = service().store
    if request.method == "POST":
        name, phone, birth = (request.form.get(key, "").strip() for key in ("name", "phone", "date_of_birth"))
        valid_birth = True
        if birth:
            try:
                valid_birth = datetime.strptime(birth, "%Y-%m-%d").date() <= datetime.now().date()
            except ValueError:
                valid_birth = False
        if (not 2 <= len(name) <= 100 or
                (phone and not re.fullmatch(r"[+()0-9 .-]{7,25}", phone)) or not valid_birth):
            flash("Please enter a valid name, phone number, and date of birth.", "danger")
        else:
            store.update_patient(session["user"]["id"], name, phone, birth)
            session["user"] = store.user(session["user"]["id"])
            flash("Your profile has been updated.", "success")
            return redirect(url_for("patient.profile"))
    return render_template("patient/profile.html")
