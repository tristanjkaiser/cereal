"""Timeline visualization blueprint."""
from datetime import date, datetime

from flask import Blueprint, abort, render_template, request

from web.extensions import get_db
from src.services.timeline_service import TimelineService

bp = Blueprint("timelines", __name__, url_prefix="/timelines")


@bp.route("/")
def overview():
    svc = TimelineService(get_db())
    status_filter = request.args.get("status")
    items = svc.get_overview(status=status_filter)
    generated_at = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")
    return render_template(
        "timelines/overview.html",
        items=items,
        status_filter=status_filter or "",
        today=date.today(),
        generated_at=generated_at,
    )


@bp.route("/<int:timeline_id>")
def detail(timeline_id):
    svc = TimelineService(get_db())
    data = svc.get_detail(timeline_id)
    if not data:
        abort(404)
    generated_at = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")
    return render_template(
        "timelines/detail.html",
        **data,
        today=date.today(),
        generated_at=generated_at,
    )
