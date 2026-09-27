"""Shared authenticated routes."""

from flask import Blueprint, render_template

from routes.auth import login_required

shared_bp = Blueprint("shared", __name__)


@shared_bp.get("/profile")
@login_required("patient")
def profile_alias():
    from flask import redirect, url_for
    return redirect(url_for("patient.profile"))
