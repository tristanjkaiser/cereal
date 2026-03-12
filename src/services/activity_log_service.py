"""Activity log service — fire-and-forget pipeline event logging."""
import logging
from collections import OrderedDict
from datetime import date

logger = logging.getLogger(__name__)


class ActivityLogService:
    def __init__(self, db):
        self.db = db

    def log(self, event_type, summary, details=None):
        """Write an activity log entry. Never raises — errors swallowed with warning."""
        try:
            self.db.log_activity(event_type, summary, details)
        except Exception:
            logger.warning("Failed to write activity log", exc_info=True)

    def get_log_grouped_by_day(self, days=1):
        """Return OrderedDict of {date: [entries]}, newest day first."""
        rows = self.db.get_activity_log(days=days)
        grouped = OrderedDict()
        for row in rows:
            day = row["created_at"].date() if hasattr(row["created_at"], "date") else row["created_at"]
            grouped.setdefault(day, []).append(row)
        return grouped
