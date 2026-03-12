"""Attention service — generates prioritized alerts needing PM action."""
from datetime import date, timedelta

URGENCY_HIGH = 0
URGENCY_MEDIUM = 1
URGENCY_LOW = 2

URGENCY_LABELS = {URGENCY_HIGH: "high", URGENCY_MEDIUM: "medium", URGENCY_LOW: "low"}


class AttentionService:
    def __init__(self, db):
        self.db = db

    def get_alerts(self) -> list:
        """Generate all alerts, filter dismissed, sort by urgency then recency."""
        alerts = []
        alerts.extend(self._overdue_todos())
        alerts.extend(self._stale_clients())
        alerts.extend(self._approaching_milestones())
        alerts.extend(self._phase_overruns())
        alerts.extend(self._unassigned_meetings())

        alerts.sort(key=lambda a: (a["urgency"], a.get("sort_date") or date.min))
        return alerts

    def get_alert_count(self) -> int:
        """Quick count for nav badge — avoids building full alert objects."""
        return len(self.get_alerts())

    # ── Alert generators ──

    def _overdue_todos(self) -> list:
        dismissed = self.db.get_dismissed_alert_ids("overdue_todo")
        todos = self.db.list_todos(overdue_only=True, limit=100)
        alerts = []
        for t in todos:
            if t["id"] in dismissed:
                continue
            alerts.append({
                "type": "overdue_todo",
                "urgency": URGENCY_HIGH,
                "urgency_label": "high",
                "description": t["title"],
                "client_name": t.get("client_name", ""),
                "reference_id": t["id"],
                "sort_date": t.get("due_date") or date.min,
                "action_url": None,
                "action_label": "View todos",
            })
        return alerts

    def _stale_clients(self) -> list:
        dismissed = self.db.get_dismissed_alert_ids("stale_client")
        clients = self.db.get_client_dashboard_summary()
        timelines = self.db.list_timelines(status="active")
        active_client_ids = {t["client_id"] for t in timelines}
        today = date.today()
        stale_threshold = today - timedelta(days=10)
        alerts = []
        for c in clients:
            if c["id"] in dismissed:
                continue
            if c["id"] not in active_client_ids:
                continue
            last = c.get("last_meeting_date")
            if last is None:
                continue
            if hasattr(last, "date"):
                last = last.date()
            if last >= stale_threshold:
                continue
            days_ago = (today - last).days
            alerts.append({
                "type": "stale_client",
                "urgency": URGENCY_MEDIUM,
                "urgency_label": "medium",
                "description": f"No meetings in {days_ago} days (active timeline)",
                "client_name": c["name"],
                "reference_id": c["id"],
                "sort_date": last,
                "action_url": None,
                "action_label": "View client",
            })
        return alerts

    def _approaching_milestones(self) -> list:
        dismissed = self.db.get_dismissed_alert_ids("approaching_milestone")
        timelines = self.db.list_timelines(status="active")
        today = date.today()
        horizon = today + timedelta(days=5)
        alerts = []
        for tl in timelines:
            phases = self.db.get_phases_for_timeline(tl["id"])
            for p in phases:
                milestones = self.db.get_milestones_for_phase(p["id"])
                for m in milestones:
                    if m["id"] in dismissed:
                        continue
                    if m.get("status") in ("completed", "done"):
                        continue
                    td = m.get("target_date")
                    if td is None:
                        continue
                    if hasattr(td, "date"):
                        td = td.date()
                    if today <= td <= horizon:
                        days_left = (td - today).days
                        alerts.append({
                            "type": "approaching_milestone",
                            "urgency": URGENCY_MEDIUM,
                            "urgency_label": "medium",
                            "description": f"{m['name']} due in {days_left}d",
                            "client_name": tl.get("client_name", ""),
                            "reference_id": m["id"],
                            "sort_date": td,
                            "action_url": None,
                            "action_label": "View timeline",
                        })
        return alerts

    def _phase_overruns(self) -> list:
        dismissed = self.db.get_dismissed_alert_ids("phase_overrun")
        timelines = self.db.list_timelines(status="active")
        today = date.today()
        alerts = []
        for tl in timelines:
            phases = self.db.get_phases_for_timeline(tl["id"])
            for p in phases:
                if p["id"] in dismissed:
                    continue
                if p.get("status") != "in_progress":
                    continue
                end = p.get("planned_end_date")
                if end is None:
                    continue
                if hasattr(end, "date"):
                    end = end.date()
                if end >= today:
                    continue
                days_over = (today - end).days
                alerts.append({
                    "type": "phase_overrun",
                    "urgency": URGENCY_HIGH,
                    "urgency_label": "high",
                    "description": f"{p['name']} overdue by {days_over}d",
                    "client_name": tl.get("client_name", ""),
                    "reference_id": p["id"],
                    "sort_date": end,
                    "action_url": None,
                    "action_label": "View timeline",
                })
        return alerts

    def _unassigned_meetings(self) -> list:
        dismissed = self.db.get_dismissed_alert_ids("unassigned_meeting")
        cutoff = date.today() - timedelta(days=14)
        meetings = self.db.get_untagged_meetings(limit=50)
        alerts = []
        for m in meetings:
            if m["id"] in dismissed:
                continue
            md = m.get("meeting_date")
            if md is None:
                continue
            if hasattr(md, "date"):
                md = md.date()
            if md < cutoff:
                continue
            alerts.append({
                "type": "unassigned_meeting",
                "urgency": URGENCY_LOW,
                "urgency_label": "low",
                "description": m.get("title") or "Untitled meeting",
                "client_name": "",
                "reference_id": m["id"],
                "sort_date": md,
                "action_url": None,
                "action_label": "Assign",
            })
        return alerts
