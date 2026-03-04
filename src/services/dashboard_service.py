"""Dashboard service — assembles client overview for the home page."""
from datetime import date


class DashboardService:
    def __init__(self, db):
        self.db = db

    def get_client_overview(self):
        """Build client overview rows split into (active, inactive) lists.

        Active = has meetings or an active timeline.
        Inactive = neither.

        Returns:
            tuple of (active_clients, inactive_clients)
        """
        clients = self.db.get_client_dashboard_summary()
        todo_rows = self.db.get_todo_counts_by_client()
        todo_map = {r["client_id"]: r for r in todo_rows}

        timelines = self.db.list_timelines()
        timeline_map = {}
        for t in timelines:
            cid = t["client_id"]
            if cid not in timeline_map:
                timeline_map[cid] = t

        # Build phase labels for clients with timelines
        phase_map = {}
        for cid, tl in timeline_map.items():
            phases = self.db.get_phases_for_timeline(tl["id"])
            phase_map[cid] = _current_phase_label(phases)

        today = date.today()
        active = []
        inactive = []

        for c in clients:
            cid = c["id"]
            todos = todo_map.get(cid, {})
            open_todos = todos.get("open_count", 0) or 0
            overdue_todos = todos.get("overdue_count", 0) or 0

            last_meeting = c["last_meeting_date"]
            if last_meeting:
                if hasattr(last_meeting, "date"):
                    last_date = last_meeting.date()
                else:
                    last_date = last_meeting
                days_since = (today - last_date).days
            else:
                days_since = None

            tl = timeline_map.get(cid)
            phase_label = phase_map.get(cid)
            timeline_id = tl["id"] if tl else None

            if overdue_todos > 0:
                health = "at_risk"
            elif tl:
                health = "on_track"
            else:
                health = "no_timeline"

            row = {
                "id": cid,
                "name": c["name"],
                "meeting_count": c["meeting_count"] or 0,
                "last_meeting_date": last_meeting,
                "days_since_meeting": days_since,
                "open_todos": open_todos,
                "overdue_todos": overdue_todos,
                "phase_label": phase_label,
                "health": health,
                "timeline_id": timeline_id,
            }

            has_meetings = (c["meeting_count"] or 0) > 0
            if has_meetings or tl:
                active.append(row)
            else:
                inactive.append(row)

        # Sort active: at_risk first, then by days_since_meeting ascending
        def _sort_key(r):
            risk = 0 if r["health"] == "at_risk" else 1
            days = r["days_since_meeting"] if r["days_since_meeting"] is not None else 9999
            return (risk, days)

        active.sort(key=_sort_key)
        inactive.sort(key=lambda r: r["name"].lower())

        return active, inactive


def _current_phase_label(phases):
    """Derive a label like 'Design Phase > Design System' from phases list."""
    top_level = [p for p in phases if p.get("parent_phase_id") is None]
    current_top = None
    for p in top_level:
        if p["status"] == "in_progress":
            current_top = p
            break

    if not current_top:
        return None

    label = current_top["name"]

    # Look for in-progress subphase
    subs = [p for p in phases if p.get("parent_phase_id") == current_top["id"]]
    for s in subs:
        if s["status"] == "in_progress":
            label += f" \u2192 {s['name']}"
            break

    return label
