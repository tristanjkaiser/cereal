"""To-do dashboard blueprint — enhanced with htmx endpoints."""
from datetime import date, datetime

from flask import Blueprint, abort, jsonify, render_template, request

from web.extensions import get_db
from src.services.todo_service import TodoService
from src.services.client_service import ClientService

bp = Blueprint("todos", __name__, url_prefix="/todos")

VIEWS = ("all", "my_day", "by_category")


@bp.route("/")
def index():
    db = get_db()
    todo_svc = TodoService(db)
    client_svc = ClientService(db)

    client_filter = request.args.get("client")
    show_done = "done" in request.args
    view = request.args.get("view", "all")
    if view not in VIEWS:
        view = "all"

    client_id = None
    if client_filter:
        client_id = client_svc.get_client_id(client_filter)

    if view == "my_day":
        by_group = todo_svc.get_my_day_todos(client_id=client_id)
        group_label = "client"
    elif view == "by_category":
        by_group = todo_svc.get_todos_grouped_by_category(
            client_id=client_id, include_done=show_done
        )
        group_label = "category"
    else:
        by_group = todo_svc.get_todos_grouped_by_client(
            client_id=client_id, include_done=show_done
        )
        group_label = "client"

    all_clients = client_svc.get_all_clients()
    today = date.today()
    generated_at = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")

    return render_template(
        "todos/index.html",
        by_group=by_group,
        group_label=group_label,
        all_clients=all_clients,
        client_filter=client_filter or "",
        show_done=show_done,
        view=view,
        today=today,
        generated_at=generated_at,
    )


@bp.route("/row/<int:todo_id>")
def row(todo_id):
    """Return a single todo row partial (for htmx swap)."""
    db = get_db()
    todo = db.get_todo(todo_id)
    if not todo:
        abort(404)
    return render_template(
        "todos/_todo_row.html",
        todo=todo,
        today=date.today(),
    )


@bp.route("/create", methods=["POST"])
def create():
    """Quick-add a todo via htmx."""
    db = get_db()
    title = request.form.get("title", "").strip()
    client_name = request.form.get("client_name", "").strip()
    if not title or not client_name:
        return "", 400

    client_id = ClientService(db).get_client_id(client_name)
    if not client_id:
        return "", 400

    todo = db.create_todo(client_id=client_id, title=title)
    return render_template(
        "todos/_todo_row.html",
        todo={**todo, "client_name": client_name, "meeting_title": None, "meeting_date_ref": None},
        today=date.today(),
    )


@bp.route("/<int:todo_id>/complete", methods=["POST"])
def complete(todo_id):
    """Toggle todo complete/reopen via htmx."""
    db = get_db()
    todo = db.get_todo(todo_id)
    if not todo:
        abort(404)

    if todo["status"] == "done":
        db.update_todo(todo_id, status="pending")
    else:
        db.complete_todo(todo_id)

    todo = db.get_todo(todo_id)
    return render_template(
        "todos/_todo_row.html",
        todo=todo,
        today=date.today(),
    )


@bp.route("/<int:todo_id>/update", methods=["POST"])
def update(todo_id):
    """Inline update a todo field via htmx."""
    db = get_db()
    todo = db.get_todo(todo_id)
    if not todo:
        abort(404)

    kwargs = {}
    for field in ("title", "category", "status"):
        val = request.form.get(field)
        if val is not None:
            kwargs[field] = val.strip()

    val = request.form.get("priority")
    if val is not None:
        try:
            kwargs["priority"] = int(val)
        except ValueError:
            pass

    val = request.form.get("due_date")
    if val is not None:
        kwargs["due_date"] = val.strip() if val.strip() else None

    if kwargs:
        db.update_todo(todo_id, **kwargs)

    todo = db.get_todo(todo_id)
    return render_template(
        "todos/_todo_row.html",
        todo=todo,
        today=date.today(),
    )


@bp.route("/reorder", methods=["POST"])
def reorder():
    """Persist drag-and-drop order via htmx/JSON."""
    db = get_db()
    data = request.get_json(silent=True)
    if not data or "ids" not in data:
        return "", 400
    try:
        ordered_ids = [int(i) for i in data["ids"]]
    except (ValueError, TypeError):
        return "", 400
    db.update_todo_sort_order(ordered_ids)
    return "", 204


@bp.route("/bulk", methods=["POST"])
def bulk():
    """Bulk actions: complete, set priority, or delete selected todos."""
    db = get_db()
    action = request.form.get("action", "")
    ids_raw = request.form.getlist("todo_ids")
    try:
        todo_ids = [int(i) for i in ids_raw if i]
    except ValueError:
        return "", 400

    if not todo_ids:
        return "", 400

    if action == "complete":
        db.bulk_complete_todos(todo_ids)
    elif action.startswith("priority_"):
        try:
            pri = int(action.split("_", 1)[1])
        except (ValueError, IndexError):
            return "", 400
        for tid in todo_ids:
            db.update_todo(tid, priority=pri)
    elif action == "delete":
        for tid in todo_ids:
            db.delete_todo(tid)

    # Return empty to trigger full page refresh via htmx
    return "", 200
