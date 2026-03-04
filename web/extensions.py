"""Database lifecycle for the Flask app."""
from src.database import DatabaseManager

_db = None


def init_db(app):
    """Initialize a pooled DatabaseManager and register teardown."""
    global _db
    _db = DatabaseManager(
        database_url=app.config["DATABASE_URL"],
        pool_size=app.config["POOL_SIZE"],
    )

    @app.teardown_appcontext
    def _shutdown(exc):
        pass  # pool stays alive across requests; closed on process exit

    return _db


def get_db() -> DatabaseManager:
    """Return the shared DatabaseManager instance."""
    if _db is None:
        raise RuntimeError("Database not initialized — call init_db(app) first")
    return _db
