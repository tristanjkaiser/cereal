"""Client dashboard blueprint — home page."""
from datetime import datetime

from flask import Blueprint, render_template

from web.extensions import get_db
from src.services.dashboard_service import DashboardService

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    active, inactive = DashboardService(get_db()).get_client_overview()
    generated_at = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")
    return render_template(
        "dashboard/index.html",
        active=active,
        inactive=inactive,
        generated_at=generated_at,
    )
