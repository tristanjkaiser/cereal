"""Cereal web application factory."""
import re

from flask import Flask

from web.config import Config
from web.extensions import init_db

_LINEAR_KEY_RE = re.compile(r'\b([A-Z][A-Z0-9]+-\d+)\b')


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def linkify_linear(text: str) -> str:
    """Jinja filter: HTML-escape text, then wrap Linear issue keys as links."""
    escaped = _html_escape(text)
    return _LINEAR_KEY_RE.sub(
        r'<a href="https://linear.app/issue/\1" target="_blank">\1</a>',
        escaped,
    )


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    init_db(app)

    # Jinja filters
    app.jinja_env.filters["linkify_linear"] = linkify_linear

    # Blueprints
    from web.routes.dashboard import bp as dashboard_bp
    from web.routes.todos import bp as todos_bp
    from web.routes.clients import bp as clients_bp
    from web.routes.attention import bp as attention_bp
    from web.routes.timelines import bp as timelines_bp
    from web.routes.activity import bp as activity_bp
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(todos_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(attention_bp)
    app.register_blueprint(timelines_bp)
    app.register_blueprint(activity_bp)

    # Make alert count and client list available to all templates (for sidebar)
    @app.context_processor
    def inject_nav_globals():
        try:
            from src.services.attention_service import AttentionService
            from src.services.client_service import ClientService, INTERNAL_CLIENT_NAME
            from web.extensions import get_db
            db = get_db()
            count = AttentionService(db).get_alert_count()
            nav_clients = [c for c in ClientService(db).get_all_clients()
                           if c['name'] != INTERNAL_CLIENT_NAME]
        except Exception:
            count = 0
            nav_clients = []
        return {"attention_count": count, "nav_clients": nav_clients}

    return app
