"""Doctor dashboard, appointment management, and diagnosis routes."""

from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from routes.auth import login_required

doctor_bp = Blueprint("doctor", __name__)


def service():
    return current_app.extensions["medtrack_service"]


@doctor_bp.get("/")
@doctor_bp.get("/dashboard")
@login_required("doctor")
def dashboard():
    appointments = service().store.appointments_for_doctor(session["user"]["id"])
    today = datetime.now().strftime("%Y-%m-%d")
    today_appointments = [a for a in appointments if a["appointment_at"].startswith(today) and a["status"] != "Cancelled"]
    upcoming = [a for a in appointments if a["appointment_at"] >= datetime.now().strftime("%Y-%m-%d %H:%M") and a["status"] in ("Pending", "Confirmed")]
    diagnoses = service().store.diagnoses_for_doctor(session["user"]["id"])
    followups = service().store.followups_for_doctor(session["user"]["id"])
    week = datetime.now().strftime("%Y-%W")
    weekly_count = sum(1 for a in appointments if datetime.strptime(a["appointment_at"], "%Y-%m-%d %H:%M").strftime("%Y-%W") == week)
    pending_count = sum(1 for a in appointments if a["status"] == "Pending")
    completed_count = sum(1 for a in appointments if a["status"] == "Completed")
    active_followups = [f for f in followups if f["status"] in ("Scheduled", "Pending") and f["followup_date"] >= today]
    intake_ids = {a["id"] for a in appointments if service().store.intake_for_appointment(a["id"])}
    for appointment in today_appointments:
        appointment["has_intake"] = appointment["id"] in intake_ids
    return render_template("doctor/dashboard.html", today_appointments=today_appointments,
                           upcoming=upcoming[:5], diagnoses=diagnoses[:4], patient_count=len({a['patient_id'] for a in appointments}),
                           pending_count=pending_count, completed_count=completed_count,
                           weekly_count=weekly_count, followups_due=len(active_followups),
                           notification_count=len(service().store.notifications_for_user(session["user"]["id"])))


@doctor_bp.get("/appointments")
@login_required("doctor")
def appointments():
    appointments = service().store.appointments_for_doctor(session["user"]["id"])
    for appointment in appointments:
        appointment["has_intake"] = bool(service().store.intake_for_appointment(appointment["id"]))
    return render_template("appointments/list.html", appointments=appointments, patient_view=False)


@doctor_bp.get("/patients")
@login_required("doctor")
def patients():
    store = service().store
    appointments = store.appointments_for_doctor(session["user"]["id"])
    latest = {}
    for appointment in appointments:
        current = latest.get(appointment["patient_id"])
        if not current or appointment["appointment_at"] > current["appointment_at"]:
            latest[appointment["patient_id"]] = appointment
    query = request.args.get("q", "").strip().casefold()
    status_filter = request.args.get("status", "")
    directory = []
    for patient_id, appointment in latest.items():
        patient = store.user(patient_id)
        if patient and (not query or query in patient["name"].casefold()) and (not status_filter or appointment["status"] == status_filter):
            directory.append({"patient": patient, "appointment": appointment})
    directory.sort(key=lambda row: row["appointment"]["appointment_at"], reverse=True)
    return render_template("doctor/patients.html", patients=directory, query=query, status_filter=status_filter)


@doctor_bp.get("/patients/<patient_id>")
@login_required("doctor")
def patient_detail(patient_id):
    store = service().store
    related = [a for a in store.appointments_for_doctor(session["user"]["id"]) if a["patient_id"] == patient_id]
    if not related:
        return render_template("errors/error.html", error=type("NotFound", (), {"code": 404, "description": "Patient record not found."})()), 404
    patient = store.user(patient_id)
    diagnoses = [d for d in store.diagnoses_for_patient(patient_id) if d["doctor_id"] == session["user"]["id"]]
    followups = [f for f in store.followups_for_patient(patient_id) if f["doctor_id"] == session["user"]["id"]]
    vitals = [v for v in store.vitals_for_patient(patient_id) if v.get("doctor_id") in ("", session["user"]["id"])]
    related_ids = {a["id"] for a in related}
    intakes = [store.intake_for_appointment(aid) for aid in related_ids]
    intakes = [intake for intake in intakes if intake]
    events = [event for event in store.timeline_for_patient(patient_id)
              if event.get("doctor_id") == session["user"]["id"] or event.get("related_id") in related_ids]
    return render_template("doctor/patient_detail.html", patient=patient, appointments=related,
                           diagnoses=diagnoses, followups=followups, vitals=vitals,
                           intakes=intakes, events=events)


@doctor_bp.get("/timeline")
@login_required("doctor")
def timeline():
    store = service().store
    appointments = store.appointments_for_doctor(session["user"]["id"])
    allowed_ids = {a["id"] for a in appointments}
    patient_ids = {a["patient_id"] for a in appointments}
    events = [event for patient_id in patient_ids for event in store.timeline_for_patient(patient_id)
              if event.get("doctor_id") == session["user"]["id"] or event.get("related_id") in allowed_ids]
    names = {patient_id: (store.user(patient_id) or {}).get("name", "Connected patient") for patient_id in patient_ids}
    for event in events:
        event["patient_name"] = names.get(event["patient_id"], "Connected patient")
    events.sort(key=lambda event: event["event_time"], reverse=True)
    return render_template("doctor/timeline.html", events=events)


@doctor_bp.route("/followups", methods=["GET", "POST"])
@login_required("doctor")
def followups():
    store = service().store
    if request.method == "POST":
        followup = next((f for f in store.followups_for_doctor(session["user"]["id"])
                         if f["id"] == request.form.get("followup_id")), None)
        try:
            if not followup:
                raise ValueError("Follow-up not found.")
            service().update_followup_status(followup, request.form.get("status", ""))
            flash("Follow-up status updated.", "success")
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("doctor.followups"))
    return render_template("doctor/followups.html", followups=store.followups_for_doctor(session["user"]["id"]))


@doctor_bp.get("/notifications")
@login_required("doctor")
def notifications():
    return render_template("shared/notifications.html", notifications=service().store.notifications_for_user(session["user"]["id"]))


@doctor_bp.get("/profile")
@login_required("doctor")
def profile():
    return render_template("doctor/profile.html", doctor=service().store.user(session["user"]["id"]))


@doctor_bp.get("/appointments/<appointment_id>/intake")
@login_required("doctor")
def view_intake(appointment_id):
    store = service().store
    appointment = store.appointment(appointment_id)
    if not appointment or appointment["doctor_id"] != session["user"]["id"]:
        return render_template("errors/error.html", error=type("NotFound", (), {"code": 404, "description": "Appointment not found."})()), 404
    return render_template("doctor/intake.html", appointment=appointment,
                           intake=store.intake_for_appointment(appointment_id))


@doctor_bp.post("/appointments/<appointment_id>/status")
@login_required("doctor")
def update_status(appointment_id):
    store = service().store
    appointment = store.appointment(appointment_id)
    status = request.form.get("status", "")
    allowed = {"Pending", "Confirmed", "Completed", "Cancelled"}
    if not appointment or appointment["doctor_id"] != session["user"]["id"] or status not in allowed:
        flash("That appointment update could not be applied.", "danger")
    elif appointment["status"] in ("Completed", "Cancelled"):
        flash("Closed appointments cannot be changed.", "warning")
    else:
        service().update_appointment_status(appointment_id, status)
        flash(f"Appointment marked {status.lower()}.", "success")
    return redirect(url_for("doctor.appointments"))


@doctor_bp.route("/appointments/<appointment_id>/diagnosis", methods=["GET", "POST"])
@login_required("doctor")
def diagnosis(appointment_id):
    store = service().store
    appointment = store.appointment(appointment_id)
    if not appointment or appointment["doctor_id"] != session["user"]["id"]:
        return render_template("errors/error.html", error=type("NotFound", (), {"code": 404, "description": "Appointment not found."})()), 404
    if appointment["status"] == "Cancelled":
        flash("A diagnosis cannot be added to a cancelled appointment.", "warning")
        return redirect(url_for("doctor.appointments"))
    if request.method == "POST":
        try:
            service().submit_diagnosis(appointment, request.form.get("diagnosis", ""), request.form.get("notes", ""),
                                       request.form.get("observations", ""), request.form.get("followup_date", ""),
                                       request.form.get("followup_notes", ""),
                                       {key: request.form.get(key, "") for key in
                                        ("blood_pressure", "heart_rate", "temperature", "weight", "spo2")})
            flash("Diagnosis saved to the patient record.", "success")
            return redirect(url_for("doctor.diagnosis", appointment_id=appointment_id))
        except ValueError as exc:
            flash(str(exc), "danger")
    records = [d for d in store.diagnoses_for_doctor(session["user"]["id"]) if d["appointment_id"] == appointment_id]
    return render_template("doctor/diagnosis.html", appointment=appointment, diagnoses=records,
                           intake=store.intake_for_appointment(appointment_id))


@doctor_bp.get("/patients/<patient_id>/history")
@login_required("doctor")
def patient_history(patient_id):
    store = service().store
    related = [a for a in store.appointments_for_doctor(session["user"]["id"]) if a["patient_id"] == patient_id]
    if not related:
        return render_template("errors/error.html", error=type("NotFound", (), {"code": 404, "description": "Patient record not found."})()), 404
    patient = store.user(patient_id)
    diagnoses = [d for d in store.diagnoses_for_patient(patient_id) if d["doctor_id"] == session["user"]["id"]]
    return render_template("patient/history.html", diagnoses=diagnoses, doctor_view=True, patient=patient)


@doctor_bp.get("/diagnoses")
@login_required("doctor")
def diagnoses():
    return render_template("doctor/diagnoses.html", diagnoses=service().store.diagnoses_for_doctor(session["user"]["id"]))
