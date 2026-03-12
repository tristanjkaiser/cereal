"""Shared service layer used by MCP server, Flask web app, and auto_archive."""

from src.services.client_detection import detect_client_from_meeting
from src.services.todo_service import TodoService
from src.services.client_service import ClientService, INTERNAL_CLIENT_NAME
from src.services.dashboard_service import DashboardService
from src.services.todo_extraction_service import TodoExtractionService
from src.services.activity_log_service import ActivityLogService

__all__ = [
    "detect_client_from_meeting",
    "TodoService",
    "ClientService",
    "INTERNAL_CLIENT_NAME",
    "DashboardService",
    "TodoExtractionService",
    "ActivityLogService",
]
