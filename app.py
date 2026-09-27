"""MedTrack Flask application entry point."""

import getpass
import os
import secrets
from datetime import datetime, timedelta

import click
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from config import Config
from routes.auth import auth_bp
from routes.doctor import doctor_bp
from routes.patient import patient_bp
from routes.shared import shared_bp
from services.data_store import DataStoreError, SQLiteDataStore
from services.medtrack import MedTrackService
from services.notification_service import SNSNotificationService


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    os.makedirs(app.instance_path, exist_ok=True)

    backend = app.config["MEDTRACK_DATA_STORE"]
    if backend == "sqlite":
        store = SQLiteDataStore(app.config["DATABASE_PATH"])
        store.initialize()
    elif backend == "dynamodb":
        table_name = app.config["DYNAMODB_TABLE_NAME"]
        if not table_name:
            raise RuntimeError("DYNAMODB_TABLE_NAME is required when MEDTRACK_DATA_STORE=dynamodb.")
        from services.dynamodb_data_store import DynamoDBDataStore
        store = DynamoDBDataStore(table_name, app.config["AWS_REGION"])
    else:
        raise RuntimeError("MEDTRACK_DATA_STORE must be either 'sqlite' or 'dynamodb'.")
    notifications = SNSNotificationService(
        enabled=(backend == "dynamodb" and app.config["MEDTRACK_SNS_ENABLED"]),
        topic_arn=app.config["SNS_TOPIC_ARN"],
        region=app.config["AWS_REGION"],
        logger=app.logger,
    )
    app.extensions["medtrack_service"] = MedTrackService(store, notifications)

    app.register_blueprint(auth_bp)
    app.register_blueprint(patient_bp, url_prefix="/patient")
    app.register_blueprint(doctor_bp, url_prefix="/doctor")
    app.register_blueprint(shared_bp)

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            expected = session.get("csrf_token")
            supplied = request.form.get("csrf_token", "")
            if not expected or not secrets.compare_digest(expected, supplied):
                abort(400, description="The form expired or could not be verified. Please go back and try again.")

    @app.context_processor
    def inject_template_values():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        hour = datetime.now().hour
        greeting = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        return {"current_user": session.get("user"), "csrf_token": session["csrf_token"],
                "now_year": datetime.now().year, "now_date": datetime.now().strftime("%A, %B %d, %Y"),
                "today": datetime.now().strftime("%Y-%m-%d"), "greeting": greeting,
                "min_datetime": datetime.now().strftime("%Y-%m-%dT%H:%M")}

    @app.template_filter("datefmt")
    def datefmt(value, format_string="%b %d, %Y"):
        if not value:
            return "—"
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.strftime(format_string)
        except (TypeError, ValueError):
            return value

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(500)
    def handle_error(error):
        return render_template("errors/error.html", error=error), error.code

    @app.errorhandler(DataStoreError)
    def handle_data_store_error(error):
        from werkzeug.exceptions import ServiceUnavailable
        app.logger.error("Data store operation failed (%s).", type(error).__name__)
        safe_error = ServiceUnavailable(description="The care workspace is temporarily unavailable. Please try again.")
        return render_template("errors/error.html", error=safe_error), 503

    @app.get("/")
    def index():
        if session.get("user"):
            return redirect(url_for("patient.dashboard" if session["user"]["role"] == "patient" else "doctor.dashboard"))
        return render_template("index.html")

    @app.cli.command("create-doctor")
    def create_doctor():
        """Create a doctor login without placing credentials in source code."""
        name = click.prompt("Doctor full name").strip()
        email = click.prompt("Doctor email").strip().lower()
        specialty = click.prompt("Specialty", default="General Practice").strip()
        password = getpass.getpass("Password (minimum 10 characters): ")
        confirm = getpass.getpass("Confirm password: ")
        if len(password) < 10 or password != confirm:
            raise click.ClickException("Passwords must match and contain at least 10 characters.")
        try:
            app.extensions["medtrack_service"].create_doctor(name, email, specialty, password)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Doctor account created for {email}.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Create a synthetic, explicitly requested local demonstration dataset."""
        service = app.extensions["medtrack_service"]
        store = service.store
        if app.config["MEDTRACK_DATA_STORE"] != "sqlite":
            raise click.ClickException("seed-demo is restricted to SQLite local/demo mode; no AWS data was changed.")
        service = MedTrackService(store)
        demo_emails = ["demo.doctor@medtrack.test", "demo.patient@medtrack.test",
                       "demo.patient2@medtrack.test", "demo.patient3@medtrack.test"]
        if any(store.user_by_email(email) for email in demo_emails):
            click.echo("Demo accounts already exist; no records were added. Remove the demo database to reseed it.")
            return

        demo_password = "MedTrackDemo-2026!"
        doctor_id = service.create_doctor("Dr. Avery Sample", demo_emails[0], "Family Medicine", demo_password)
        people = [
            ("Jordan Example", demo_emails[1], "555-0101"),
            ("Taylor Sample", demo_emails[2], "555-0102"),
            ("Casey Demo", demo_emails[3], "555-0103"),
        ]
        patient_ids = [service.register_patient(name, email, demo_password, phone, "1990-01-01")
                       for name, email, phone in people]
        now = datetime.now()
        past_time = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
        past_id = store.create_appointment(patient_ids[0], doctor_id, past_time, "Synthetic completed demo visit")
        service.update_appointment_status(past_id, "Completed")
        service.submit_diagnosis(store.appointment(past_id), "Synthetic demo visit record",
                                 "Example-only notes for the product walkthrough.",
                                 observations="Synthetic observation entered for demonstration.",
                                 followup_date=(now.date() + timedelta(days=10)).isoformat(),
                                 followup_notes="Synthetic follow-up plan for demonstration.",
                                 vitals={"blood_pressure": "118/76", "heart_rate": "72", "temperature": "36.8",
                                         "weight": "68", "spo2": "98"})
        appointments = []
        for offset, patient_id in enumerate(patient_ids, start=1):
            at = (now + timedelta(days=offset, hours=9 - now.hour)).replace(minute=0, second=0, microsecond=0)
            appointment_id = service.book_appointment(
                patient_id, doctor_id, at.strftime("%Y-%m-%dT%H:%M"), "Synthetic routine care visit")
            appointments.append(appointment_id)
        service.update_appointment_status(appointments[2], "Confirmed")
        service.submit_intake(patient_ids[1], store.appointment(appointments[1]), {
            "main_concern": "Synthetic pre-visit concern", "symptoms": "Example symptoms for demonstration only.",
            "duration": "A few days", "severity": "Mild", "allergies": "No demo data supplied",
            "medications": "No demo data supplied", "additional_notes": "Synthetic intake; not real patient information."})
        service.record_vitals(patient_ids[1], patient_ids[1], {
            "blood_pressure": "120/80", "heart_rate": "74", "temperature": "36.7",
            "weight": "70", "spo2": "97"})
        click.echo("Synthetic MedTrack demo dataset created.")
        click.echo(f"Doctor: {demo_emails[0]} / {demo_password}")
        click.echo(f"Patient: {demo_emails[1]} / {demo_password}")
        click.echo("Additional synthetic patients: demo.patient2@medtrack.test, demo.patient3@medtrack.test")

    return app


app = create_app()


if __name__ == "__main__":
    app.run()
