"""Timeline service — builds data for Gantt visualizations."""
from datetime import date, timedelta
from typing import Optional


class TimelineService:
    def __init__(self, db):
        self.db = db

    def get_overview(self, status: Optional[str] = None) -> list:
        """Build overview data for all timelines with Gantt positioning."""
        timelines = self.db.list_timelines(status=status)
        result = []
        for tl in timelines:
            phases = self.db.get_phases_for_timeline(tl["id"])
            top_phases = [p for p in phases if p.get("parent_phase_id") is None]
            gantt = self._compute_gantt(tl, top_phases)
            result.append({
                "timeline": tl,
                "phases": top_phases,
                "gantt": gantt,
            })
        return result

    def get_detail(self, timeline_id: int) -> Optional[dict]:
        """Build full detail data for a single timeline."""
        tl = self.db.get_timeline(timeline_id)
        if not tl:
            return None

        phases = self.db.get_phases_for_timeline(timeline_id)
        top_phases = [p for p in phases if p.get("parent_phase_id") is None]

        # Build phase tree with milestones and subphases
        phase_tree = []
        for tp in top_phases:
            subs = [p for p in phases if p.get("parent_phase_id") == tp["id"]]
            milestones = self.db.get_milestones_for_phase(tp["id"])
            # Also get milestones for subphases
            for sp in subs:
                sp["milestones"] = self.db.get_milestones_for_phase(sp["id"])
            phase_tree.append({
                "phase": tp,
                "subphases": subs,
                "milestones": milestones,
            })

        gantt = self._compute_gantt(tl, top_phases)

        # Subphase gantt bars within their parent
        for pt in phase_tree:
            parent_gantt = next(
                (g for g in gantt["bars"] if g["id"] == pt["phase"]["id"]),
                None,
            )
            if parent_gantt and pt["subphases"]:
                pt["sub_gantt"] = self._compute_sub_gantt(
                    parent_gantt, pt["subphases"]
                )
            else:
                pt["sub_gantt"] = []

        # Linear mappings
        linear_mappings = self.db.get_linear_mappings_for_timeline(timeline_id)

        # Health snapshots
        snapshots = self.db.get_snapshots(timeline_id, limit=10)

        # Workshops (from strategy sprint phase if any)
        workshops = []
        for tp in top_phases:
            if "strategy" in tp["name"].lower() or "sprint" in tp["name"].lower():
                workshops = self.db.get_workshops_for_phase(tp["id"])
                break

        return {
            "timeline": tl,
            "phase_tree": phase_tree,
            "gantt": gantt,
            "linear_mappings": linear_mappings,
            "snapshots": snapshots,
            "workshops": workshops,
        }

    def _compute_gantt(self, tl, top_phases) -> dict:
        """Compute Gantt bar positions as percentages of a date range."""
        today = date.today()

        # Determine the overall date range
        range_start, range_end = self._determine_range(tl, top_phases, today)
        total_days = max((range_end - range_start).days, 1)

        # Today marker position
        today_pct = self._clamp_pct((today - range_start).days / total_days * 100)

        # Compute month markers for the header
        months = self._month_markers(range_start, range_end, total_days)

        # Bars for each top-level phase
        bars = []
        for p in top_phases:
            start = _to_date(p.get("actual_start_date") or p.get("planned_start_date"))
            end = _to_date(p.get("actual_end_date") or p.get("planned_end_date"))
            if not start and not end:
                bars.append({
                    "id": p["id"],
                    "name": p["name"],
                    "status": p.get("status", "upcoming"),
                    "left": 0,
                    "width": 0,
                    "visible": False,
                })
                continue

            if not start:
                start = end - timedelta(days=7)
            if not end:
                end = start + timedelta(days=14)

            left = (start - range_start).days / total_days * 100
            width = max((end - start).days / total_days * 100, 1)
            bars.append({
                "id": p["id"],
                "name": p["name"],
                "status": p.get("status", "upcoming"),
                "left": self._clamp_pct(left),
                "width": min(width, 100 - max(left, 0)),
                "start_date": start,
                "end_date": end,
                "visible": True,
            })

        bar_map = {b["id"]: b for b in bars}

        return {
            "range_start": range_start,
            "range_end": range_end,
            "total_days": total_days,
            "today_pct": today_pct,
            "months": months,
            "bars": bars,
            "bar_map": bar_map,
        }

    def _compute_sub_gantt(self, parent_bar, subphases) -> list:
        """Compute sub-bars relative to parent bar's start/end."""
        p_start = parent_bar.get("start_date")
        p_end = parent_bar.get("end_date")
        if not p_start or not p_end:
            return []
        p_days = max((p_end - p_start).days, 1)
        result = []
        for sp in subphases:
            start = _to_date(sp.get("actual_start_date") or sp.get("planned_start_date"))
            end = _to_date(sp.get("actual_end_date") or sp.get("planned_end_date"))
            if not start and not end:
                continue
            if not start:
                start = end - timedelta(days=3)
            if not end:
                end = start + timedelta(days=7)
            left = (start - p_start).days / p_days * 100
            width = max((end - start).days / p_days * 100, 2)
            result.append({
                "id": sp["id"],
                "name": sp["name"],
                "status": sp.get("status", "upcoming"),
                "left": self._clamp_pct(left),
                "width": min(width, 100 - max(left, 0)),
            })
        return result

    def _determine_range(self, tl, phases, today) -> tuple:
        """Find the overall date range for a timeline's Gantt."""
        dates = []

        sow = _to_date(tl.get("sow_signed_date"))
        if sow:
            dates.append(sow)

        for p in phases:
            for field in ("planned_start_date", "planned_end_date",
                          "actual_start_date", "actual_end_date"):
                d = _to_date(p.get(field))
                if d:
                    dates.append(d)

        if not dates:
            # No dates at all — use SOW estimate from today
            overall_weeks = tl.get("estimated_overall_weeks_high") or 12
            return (today - timedelta(days=7), today + timedelta(weeks=int(overall_weeks)))

        range_start = min(dates)
        range_end = max(dates)

        # If SOW has estimated overall weeks, extend range_end
        if sow and tl.get("estimated_overall_weeks_high"):
            est_end = sow + timedelta(weeks=int(tl["estimated_overall_weeks_high"]))
            range_end = max(range_end, est_end)

        # Ensure today is within range (with padding)
        range_start = min(range_start, today - timedelta(days=7))
        range_end = max(range_end, today + timedelta(days=14))

        # Add small padding
        range_start -= timedelta(days=3)
        range_end += timedelta(days=7)

        return (range_start, range_end)

    def _month_markers(self, range_start, range_end, total_days) -> list:
        """Generate month label positions for the Gantt header."""
        markers = []
        d = range_start.replace(day=1)
        if d < range_start:
            if d.month == 12:
                d = d.replace(year=d.year + 1, month=1)
            else:
                d = d.replace(month=d.month + 1)

        while d <= range_end:
            pct = (d - range_start).days / total_days * 100
            if 0 <= pct <= 100:
                markers.append({
                    "label": d.strftime("%b '%y") if d.month == 1 or d == range_start.replace(day=1) else d.strftime("%b"),
                    "pct": pct,
                })
            if d.month == 12:
                d = d.replace(year=d.year + 1, month=1)
            else:
                d = d.replace(month=d.month + 1)
        return markers

    @staticmethod
    def _clamp_pct(v):
        return max(0, min(100, v))


def _to_date(val) -> Optional[date]:
    """Convert a value to a date, handling datetime and string."""
    if val is None:
        return None
    if isinstance(val, date):
        if hasattr(val, "date"):
            return val.date()
        return val
    try:
        from datetime import datetime
        return datetime.strptime(str(val), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
