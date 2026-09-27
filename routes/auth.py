"""Authentication and patient registration routes."""

from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

auth_bp = Blueprint("auth", __name__)


def login_required(role=None):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = session.get("user")
            if not user:
                flash("Please sign in to continue.", "info")
                return redirect(url_for("auth.patient_login" if role == "patient" else "auth.doctor_login" if role == "doctor" else "auth.patient_login"))
            if role and user.get("role") != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


@auth_bp.route("/patient/register", endpoint="patient_register", methods=["GET", "POST"])
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user"):
        return redirect(url_for("patient.dashboard" if session["user"]["role"] == "patient" else "doctor.dashboard"))
    if request.method == "POST":
        try:
            service = current_app.extensions["medtrack_service"]
            user_id = service.register_patient(request.form.get("name", ""), request.form.get("email", ""),
                                               request.form.get("password", ""), request.form.get("phone", ""),
                                               request.form.get("date_of_birth", ""))
            session.clear()
            session.permanent = True
            session["user"] = service.store.user(user_id)
            flash("Your patient account is ready. Welcome to MedTrack.", "success")
            return redirect(url_for("patient.dashboard"))
        except ValueError as exc:
            flash(str(exc), "danger")
    return render_template("auth/register.html")


@auth_bp.route("/patient/login", endpoint="patient_login_portal", methods=["GET", "POST"])
@auth_bp.route("/login", methods=["GET", "POST"])
def patient_login():
    return _login("patient")


@auth_bp.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():
    return _login("doctor")


def _login(role):
    if session.get("user"):
        return redirect(url_for("patient.dashboard" if session["user"]["role"] == "patient" else "doctor.dashboard"))
    if request.method == "POST":
        service = current_app.extensions["medtrack_service"]
        user = service.authenticate(request.form.get("email", ""), request.form.get("password", ""), role)
        if user:
            session.clear()
            session.permanent = True
            session["user"] = user
            flash(f"Welcome back, {user['name'].split()[0]}.", "success")
            return redirect(url_for("patient.dashboard" if role == "patient" else "doctor.dashboard"))
        flash("The email or password was not recognized for this sign-in.", "danger")
    return render_template("auth/login.html", role=role)


@auth_bp.post("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))
