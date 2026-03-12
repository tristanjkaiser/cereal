"""Client service — lookup helpers shared between MCP and Flask."""
from datetime import date
from typing import Optional

INTERNAL_CLIENT_NAME = "Internal"


class ClientService:
    def __init__(self, db):
        self.db = db

    def get_client_id(self, name: str):
        """Look up a client by name. Returns id or None."""
        client = self.db.get_client_by_name(name)
        return client["id"] if client else None

    def ensure_internal_client(self) -> int:
        """Ensure the 'Internal' virtual client exists. Returns its id."""
        return self.db.get_or_create_client(INTERNAL_CLIENT_NAME)

    def get_all_clients(self) -> list:
        """Return all clients (id + name)."""
        return self.db.get_all_clients()

    def get_client_detail(self, name: str) -> Optional[dict]:
        """Bundle all per-client data for the detail page."""
        client = self.db.get_client_by_name(name)
        if not client:
            return None
        cid = client["id"]

        todos = self.db.list_todos(client_id=cid, include_done=False, limit=20)
        context_docs = self.db.list_client_context(cid)
        integrations = self.db.list_client_integrations(client_id=cid)
        aliases = self.db.get_aliases_for_client(cid)
        timelines = self.db.get_timelines_for_client(cid)

        timeline_info = []
        for tl in timelines:
            phases = self.db.get_phases_for_timeline(tl["id"])
            timeline_info.append({"timeline": tl, "phases": phases})

        open_count = sum(
            1 for t in todos
            if t["status"] not in ("done", "archived")
        )
        overdue_count = sum(
            1 for t in todos
            if t.get("due_date") and t["due_date"] < date.today()
            and t["status"] not in ("done", "archived")
        )

        return {
            "client": client,
            "todos": todos,
            "open_todos": open_count,
            "overdue_todos": overdue_count,
            "context_docs": context_docs,
            "integrations": integrations,
            "aliases": aliases,
            "timelines": timeline_info,
        }
