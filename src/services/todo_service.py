"""Todo service — grouping, matching, and query helpers.

Shared between MCP server and Flask web app.
"""
from collections import OrderedDict
from datetime import date


class TodoService:
    def __init__(self, db):
        self.db = db

    def get_todos_grouped_by_client(
        self, client_id=None, include_done=False, limit=200
    ) -> OrderedDict:
        """Fetch todos and group by client name, preserving order.

        Returns:
            OrderedDict mapping client_name -> list of todo dicts
        """
        todos = self.db.list_todos(
            client_id=client_id,
            include_done=include_done,
            limit=limit,
        )
        by_client = OrderedDict()
        for todo in todos:
            cname = todo["client_name"]
            if cname not in by_client:
                by_client[cname] = []
            by_client[cname].append(todo)
        return by_client

    def get_my_day_todos(self, client_id=None, limit=200) -> OrderedDict:
        """Todos due today or overdue, grouped by client."""
        todos = self.db.list_todos(
            client_id=client_id,
            include_done=False,
            limit=limit,
        )
        today = date.today()
        filtered = [
            t for t in todos
            if t.get("due_date") is not None and t["due_date"] <= today
        ]
        by_client = OrderedDict()
        for todo in filtered:
            cname = todo["client_name"]
            if cname not in by_client:
                by_client[cname] = []
            by_client[cname].append(todo)
        return by_client

    def get_todos_grouped_by_category(
        self, client_id=None, include_done=False, limit=200
    ) -> OrderedDict:
        """Fetch todos grouped by category instead of client."""
        todos = self.db.list_todos(
            client_id=client_id,
            include_done=include_done,
            limit=limit,
        )
        by_cat = OrderedDict()
        for todo in todos:
            cat = todo.get("category") or "Uncategorized"
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(todo)
        return by_cat

    @staticmethod
    def match_todos(todos: list, search: str) -> list:
        """Match todos by title substring. Exact match takes priority."""
        search_lower = search.lower()
        exact = [t for t in todos if t["title"].lower() == search_lower]
        if exact:
            return exact
        return [t for t in todos if search_lower in t["title"].lower()]
