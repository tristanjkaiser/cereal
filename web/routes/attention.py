"""Attention queue blueprint."""
from datetime import datetime

from flask import Blueprint, redirect, render_template, request, url_for

from web.extensions import get_db
from src.services.attention_service import AttentionService

bp = Blueprint("attention", __name__, url_prefix="/attention")


@bp.route("/")
def index():
    svc = AttentionService(get_db())
    alerts = svc.get_alerts()
    generated_at = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")
    return render_template(
        "attention/index.html",
        alerts=alerts,
        generated_at=generated_at,
    )


@bp.route("/dismiss", methods=["POST"])
def dismiss():
    db = get_db()
    alert_type = request.form.get("alert_type", "")
    reference_id = request.form.get("reference_id", type=int)
    if alert_type and reference_id is not None:
        db.dismiss_alert(alert_type, reference_id)
    return redirect(url_for("attention.index"))
