"""Shared service layer used by MCP server, Flask web app, and auto_archive."""

from src.services.client_detection import detect_client_from_meeting
from src.services.todo_service import TodoService
from src.services.client_service import ClientService
from src.services.dashboard_service import DashboardService

__all__ = [
    "detect_client_from_meeting",
    "TodoService",
    "ClientService",
    "DashboardService",
]
