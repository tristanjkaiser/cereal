"""Client detail blueprint."""
from datetime import date, datetime

from flask import Blueprint, abort, render_template

from web.extensions import get_db
from src.services.client_service import ClientService

bp = Blueprint("clients", __name__, url_prefix="/clients")


@bp.route("/<client_name>")
def detail(client_name):
    data = ClientService(get_db()).get_client_detail(client_name)
    if not data:
        abort(404)
    return render_template(
        "clients/detail.html",
        **data,
        today=date.today(),
        generated_at=datetime.now().strftime("%b %-d, %Y at %-I:%M %p"),
    )
