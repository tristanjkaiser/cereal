"""Activity log blueprint — pipeline monitoring feed."""
from datetime import datetime

from flask import Blueprint, render_template, request

from web.extensions import get_db
from src.services.activity_log_service import ActivityLogService

bp = Blueprint("activity", __name__, url_prefix="/activity")

PERIOD_MAP = {"today": 1, "week": 7, "month": 30}


@bp.route("/")
def index():
    period = request.args.get("period", "today")
    days = PERIOD_MAP.get(period, 1)
    svc = ActivityLogService(get_db())
    grouped = svc.get_log_grouped_by_day(days=days)
    generated_at = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")
    return render_template(
        "activity/index.html",
        grouped=grouped,
        period=period,
        generated_at=generated_at,
    )
