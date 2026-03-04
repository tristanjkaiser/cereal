#!/usr/bin/env python3
"""
Cereal To-Do Dashboard — lightweight read-only web UI.

Queries PostgreSQL on each page load and renders todos grouped by client.
Update data via Claude MCP tools; this dashboard is view-only.

Usage:
    python dashboard/serve.py                # Start on default port 5555
    python dashboard/serve.py --port 8080    # Custom port
    python dashboard/serve.py --open         # Auto-open browser on start
"""
import argparse
import logging
import os
import re
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.database import DatabaseManager

# Logging
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_DIR / "dashboard.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

DEFAULT_PORT = 5555

# --- HTML helpers ---

PRIORITY_COLORS = {1: "#dc2626", 2: "#ea580c", 3: "#6b7280", 4: "#3b82f6"}
PRIORITY_LABELS = {0: "", 1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}
STATUS_ICONS = {"pending": "&#9744;", "in_progress": "&#9684;", "done": "&#10003;", "archived": "&mdash;"}


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_LINEAR_KEY_RE = re.compile(r'\b([A-Z][A-Z0-9]+-\d+)\b')


def _linkify_linear(text: str) -> str:
    """HTML-escape text, then wrap Linear issue keys as clickable links."""
    escaped = _html_escape(text)
    return _LINEAR_KEY_RE.sub(
        r'<a href="https://linear.app/issue/\1" target="_blank">\1</a>',
        escaped
    )


def _build_filter_bar(clients: list, active_client: str, show_done: bool) -> str:
    """Build filter links at the top of the page."""
    links = []

    # "All" link
    all_class = ' class="active"' if not active_client else ''
    all_href = "/?done=1" if show_done else "/"
    links.append(f'<a href="{all_href}"{all_class}>All</a>')

    for c in clients:
        is_active = c['name'] == active_client
        cls = ' class="active"' if is_active else ''
        qs = f"?client={_html_escape(c['name'])}"
        if show_done:
            qs += "&done=1"
        links.append(f'<a href="{qs}"{cls}>{_html_escape(c["name"])}</a>')

    done_toggle_qs = f"?client={_html_escape(active_client)}&" if active_client else "?"
    if show_done:
        done_link = f'<a href="{done_toggle_qs.rstrip("&")}" class="toggle">Hide done</a>'
    else:
        done_link = f'<a href="{done_toggle_qs}done=1" class="toggle">Show done</a>'

    return f'<div class="filters"><div class="client-filters">{"".join(links)}</div>{done_link}</div>'


def _build_todo_rows(todos: list, today) -> str:
    rows = ""
    for todo in todos:
        icon = STATUS_ICONS.get(todo['status'], "&#9744;")
        done_class = " done" if todo['status'] in ('done', 'archived') else ""

        pri_val = todo.get('priority', 0)
        pri_label = PRIORITY_LABELS.get(pri_val, "")
        pri_color = PRIORITY_COLORS.get(pri_val, "#6b7280")
        pri_html = f'<span class="badge" style="background:{pri_color}">{pri_label}</span>' if pri_label else ""

        cat = todo.get('category') or ""
        cat_html = f'<span class="cat">{cat}</span>' if cat else ""

        due_html = ""
        overdue = False
        if todo.get('due_date'):
            try:
                due_date = todo['due_date']
                if isinstance(due_date, str):
                    due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
                due_str = due_date.strftime("%b %-d")
                if due_date < today and todo['status'] not in ('done', 'archived'):
                    overdue = True
                    due_html = f'<span class="overdue">&#9888;&#65039; {due_str}</span>'
                else:
                    due_html = due_str
            except (ValueError, TypeError):
                due_html = str(todo['due_date'])

        source = ""
        if todo.get('meeting_id'):
            source = f"mtg #{todo['meeting_id']}"
        elif todo.get('source_context'):
            ctx = todo['source_context']
            source = ctx if len(ctx) <= 25 else ctx[:23] + ".."

        row_class = "overdue-row" if overdue else ""

        rows += f"""<tr class="{row_class}{done_class}">
  <td class="status">{icon}</td>
  <td class="id">{todo['id']}</td>
  <td class="title">{_linkify_linear(todo['title'])}</td>
  <td>{pri_html}</td>
  <td>{cat_html}</td>
  <td class="due">{due_html}</td>
  <td class="source">{_html_escape(source)}</td>
</tr>"""
    return rows


def build_page(db: DatabaseManager, client_filter: str = None, show_done: bool = False) -> str:
    """Query DB and render full HTML page."""
    client_id = None
    if client_filter:
        client = db.get_client_by_name(client_filter)
        if client:
            client_id = client['id']

    todos = db.list_todos(client_id=client_id, include_done=show_done, limit=200)
    today = datetime.now().date()
    generated_at = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")

    # Group by client
    by_client = {}
    for todo in todos:
        cname = todo['client_name']
        if cname not in by_client:
            by_client[cname] = []
        by_client[cname].append(todo)

    # Build client cards
    cards_html = ""
    for cname, client_todos in by_client.items():
        open_count = sum(1 for t in client_todos if t['status'] not in ('done', 'archived'))
        rows = _build_todo_rows(client_todos, today)
        cards_html += f"""<div class="client-card">
  <h2>{_html_escape(cname)} <span class="count">{open_count} open</span></h2>
  <table>
    <thead>
      <tr><th>Status</th><th>ID</th><th>Title</th><th>Priority</th><th>Category</th><th>Due</th><th>Source</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""

    if not todos:
        scope = f" for {_html_escape(client_filter)}" if client_filter else ""
        cards_html = f'<div class="client-card"><p class="empty">No to-dos found{scope}.</p></div>'

    # Get all clients for filter bar
    all_clients = db.get_all_clients()
    filter_bar = _build_filter_bar(all_clients, client_filter or "", show_done)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>Cereal &mdash; To-Dos</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8f9fa; color: #1a1a2e; padding: 2rem; }}
  .header {{ max-width: 960px; margin: 0 auto 1rem; display: flex; justify-content: space-between; align-items: baseline; }}
  .header h1 {{ font-size: 1.5rem; font-weight: 700; }}
  .header .timestamp {{ font-size: 0.8rem; color: #6b7280; }}
  .filters {{ max-width: 960px; margin: 0 auto 1.5rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; }}
  .client-filters {{ display: flex; flex-wrap: wrap; gap: 0.35rem; }}
  .filters a {{ display: inline-block; padding: 0.3rem 0.7rem; border-radius: 999px; background: #e5e7eb; color: #374151; font-size: 0.8rem; font-weight: 500; text-decoration: none; transition: background 0.15s; }}
  .filters a:hover {{ background: #d1d5db; }}
  .filters a.active {{ background: #1a1a2e; color: #fff; }}
  .filters a.toggle {{ background: transparent; border: 1px solid #d1d5db; color: #6b7280; }}
  .filters a.toggle:hover {{ border-color: #9ca3af; color: #374151; }}
  .client-card {{ max-width: 960px; margin: 0 auto 1.5rem; background: #fff; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); padding: 1.25rem 1.5rem; }}
  .client-card h2 {{ font-size: 1.1rem; font-weight: 600; margin-bottom: 0.75rem; }}
  .client-card h2 .count {{ font-weight: 400; font-size: 0.85rem; color: #6b7280; }}
  .empty {{ color: #6b7280; font-size: 0.9rem; padding: 1rem 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  thead th {{ text-align: left; font-weight: 500; color: #6b7280; padding: 0.4rem 0.5rem; border-bottom: 1px solid #e5e7eb; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  tbody td {{ padding: 0.5rem 0.5rem; border-bottom: 1px solid #f3f4f6; vertical-align: middle; }}
  .status {{ font-size: 1.1rem; text-align: center; width: 3rem; }}
  .id {{ color: #9ca3af; font-size: 0.8rem; width: 2.5rem; }}
  .title {{ font-weight: 500; }}
  .title a {{ color: #4338ca; text-decoration: none; border-bottom: 1px solid #c7d2fe; }}
  .title a:hover {{ border-bottom-color: #4338ca; }}
  .due {{ white-space: nowrap; }}
  .source {{ color: #9ca3af; font-size: 0.8rem; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; color: #fff; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }}
  .cat {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; background: #e0e7ff; color: #4338ca; font-size: 0.7rem; font-weight: 500; }}
  .overdue {{ color: #dc2626; font-weight: 600; }}
  .overdue-row {{ background: #fef2f2; }}
  .done {{ opacity: 0.45; }}
  tr.done .title {{ text-decoration: line-through; }}
</style>
</head>
<body>
<div class="header">
  <h1>Cereal &mdash; To-Dos</h1>
  <span class="timestamp">Last refreshed: {generated_at}</span>
</div>
{filter_bar}
{cards_html}
</body>
</html>"""


# --- HTTP Server ---

class DashboardHandler(BaseHTTPRequestHandler):
    db: DatabaseManager = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        params = parse_qs(parsed.query)
        client_filter = params.get("client", [None])[0]
        show_done = "done" in params

        try:
            html = build_page(self.db, client_filter, show_done)
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            logger.exception("Error rendering dashboard")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def log_message(self, format, *args):
        logger.info(format % args)


def main():
    parser = argparse.ArgumentParser(description="Cereal To-Do Dashboard")
    parser.add_argument("--port", type=int, default=int(os.getenv("DASHBOARD_PORT", DEFAULT_PORT)))
    parser.add_argument("--open", action="store_true", help="Open browser on start")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", "postgresql://localhost:5432/cereal")
    db = DatabaseManager(database_url)
    DashboardHandler.db = db

    server = HTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://localhost:{args.port}"
    logger.info(f"Dashboard running at {url}")
    print(f"Dashboard running at {url}")

    if args.open:
        import webbrowser
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
