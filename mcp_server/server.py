#!/usr/bin/env python3
"""
Cereal - MCP Server for Granola Meeting Archives.

Query your Granola meeting transcripts directly from Claude Desktop
using MCP (Model Context Protocol).

Usage:
    # Development mode
    uv run mcp dev server.py

    # Production (via run_server.sh)
    ./run_server.sh
"""
import json
import logging
import os
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Set up logging to file for debugging
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(log_dir / "mcp_server.log"),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    from mcp.server.fastmcp import FastMCP

    # Load environment variables from parent directory
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded .env from {env_path}")
    else:
        load_dotenv()
        logger.info("Loaded .env from default location")

    # Add parent directory to path for database imports
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.database import DatabaseManager
    from src.granola_client import GranolaClient
    from src.services.client_detection import detect_client_from_meeting
    from src.services.client_service import ClientService, INTERNAL_CLIENT_NAME
    from src.services.todo_service import TodoService
    from src.services.todo_extraction_service import TodoExtractionService
    from src.services.activity_log_service import ActivityLogService
    logger.info("Successfully imported DatabaseManager and GranolaClient")

except Exception as e:
    logger.exception(f"Error during imports: {e}")
    raise

# Initialize MCP server
logger.info("Initializing FastMCP server...")
mcp = FastMCP("Cereal")
logger.info("FastMCP server initialized")

# Database connection (lazy initialization)
_db: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """Get or create database connection."""
    global _db
    if _db is None:
        database_url = os.getenv("DATABASE_URL")
        logger.info(f"DATABASE_URL present: {bool(database_url)}")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")
        logger.info("Connecting to database...")
        _db = DatabaseManager(database_url)
        logger.info("Database connected successfully")
        ClientService(_db).ensure_internal_client()
    return _db



def format_meeting_summary(meeting: dict) -> str:
    """Format a meeting for display."""
    date_str = meeting['meeting_date'].strftime('%Y-%m-%d')
    client = meeting.get('client_name') or 'No client'
    return f"[{meeting['id']}] {date_str} - {meeting['title']} ({client})"


def format_meeting_details(meeting: dict, include_transcript: bool = False) -> str:
    """Format full meeting details."""
    parts = []
    parts.append(f"# {meeting['title']}")
    parts.append(f"**Date:** {meeting['meeting_date'].strftime('%Y-%m-%d %H:%M')}")

    if meeting.get('client_name'):
        parts.append(f"**Client:** {meeting['client_name']}")

    if meeting.get('meeting_type') and meeting['meeting_type'] != 'general':
        parts.append(f"**Type:** {meeting['meeting_type']}")

    parts.append(f"**Meeting ID:** {meeting['id']}")
    parts.append("")

    if meeting.get('summary_overview'):
        parts.append("## Summary")
        parts.append(meeting['summary_overview'])
        parts.append("")

    if meeting.get('enhanced_notes'):
        parts.append("## Notes")
        parts.append(meeting['enhanced_notes'][:10000])
        parts.append("")

    if include_transcript and meeting.get('transcript'):
        parts.append("## Transcript")
        transcript = meeting['transcript']
        # Truncate very long transcripts
        if len(transcript) > 50000:
            transcript = transcript[:50000] + "\n\n[Transcript truncated - use get_meeting_transcript for full text]"
        parts.append(transcript)

    return "\n".join(parts)


@mcp.tool()
def list_clients() -> str:
    """List all clients with their meeting counts.

    Returns a list of all clients you have meetings with,
    sorted by number of meetings.
    """
    db = get_db()
    clients = db.get_clients_with_meeting_counts()

    if not clients:
        return "No clients found. Meetings may not be tagged with clients yet."

    # Separate Internal from real clients
    real_clients = [c for c in clients if c['name'] != INTERNAL_CLIENT_NAME]
    internal = [c for c in clients if c['name'] == INTERNAL_CLIENT_NAME]

    lines = ["# Clients\n"]
    for client in real_clients:
        lines.append(f"- **{client['name']}**: {client['meeting_count']} meetings")

    if internal:
        lines.append("")
        lines.append(f"- **{INTERNAL_CLIENT_NAME}** *(internal/non-client items)*")

    return "\n".join(lines)


@mcp.tool()
def list_recent_meetings(days: int = 7) -> str:
    """Get meetings from the last N days.

    Args:
        days: Number of days to look back (default 7)

    Returns a list of recent meetings with dates and clients.
    """
    db = get_db()
    meetings = db.get_recent_meetings(days=days)

    if not meetings:
        return f"No meetings found in the last {days} days."

    lines = [f"# Meetings from last {days} days\n"]
    for m in meetings:
        lines.append(f"- {format_meeting_summary(m)}")

    return "\n".join(lines)


@mcp.tool()
def get_client_meetings(client_name: str, limit: int = 20) -> str:
    """Get all meetings for a specific client.

    Args:
        client_name: Name of the client (e.g., "NGynS", "Mothership", "NB44")
        limit: Maximum number of meetings to return (default 20)

    Returns a list of meetings for this client with summaries.
    """
    db = get_db()
    meetings = db.get_meetings_by_client(client_name, limit=limit)

    if not meetings:
        # Try fuzzy match
        all_clients = db.get_all_clients()
        suggestions = [c['name'] for c in all_clients if client_name.lower() in c['name'].lower()]
        if suggestions:
            return f"No meetings found for '{client_name}'. Did you mean: {', '.join(suggestions)}?"
        return f"No meetings found for client '{client_name}'."

    lines = [f"# Meetings for {client_name} ({len(meetings)} total)\n"]

    for m in meetings:
        lines.append(f"## {m['meeting_date'].strftime('%Y-%m-%d')} - {m['title']}")
        lines.append(f"*Meeting ID: {m['id']}*\n")
        if m.get('summary_overview'):
            lines.append(m['summary_overview'])
        elif m.get('enhanced_notes'):
            lines.append(m['enhanced_notes'][:500] + "..." if len(m.get('enhanced_notes', '')) > 500 else m['enhanced_notes'])
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def search_meetings(query: str, limit: int = 10) -> str:
    """Search across all meeting transcripts and notes.

    Args:
        query: Search term to find in transcripts and notes
        limit: Maximum number of results (default 10)

    Returns matching meetings with relevant excerpts.
    """
    db = get_db()
    meetings = db.search_meetings(query, limit=limit)

    if not meetings:
        return f"No meetings found matching '{query}'."

    lines = [f"# Search results for '{query}' ({len(meetings)} matches)\n"]

    for m in meetings:
        lines.append(f"## {format_meeting_summary(m)}")
        lines.append(f"*Relevance: {m.get('rank', 0):.2f}*\n")

        # Show relevant excerpt
        if m.get('summary_overview'):
            lines.append(f"**Summary:** {m['summary_overview'][:300]}...")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_meeting_details(meeting_id: int) -> str:
    """Get full details for a specific meeting including notes.

    Args:
        meeting_id: Database ID of the meeting (shown in brackets in listings)

    Returns the meeting's full notes, summary, and metadata.
    Does NOT include transcript - use get_meeting_transcript for that.
    """
    db = get_db()
    meeting = db.get_meeting_by_id(meeting_id)

    if not meeting:
        return f"Meeting with ID {meeting_id} not found."

    return format_meeting_details(meeting, include_transcript=False)


@mcp.tool()
def get_meeting_transcript(meeting_id: int) -> str:
    """Get the full transcript for a specific meeting.

    Args:
        meeting_id: Database ID of the meeting

    Returns the full meeting transcript with speaker labels.
    Use this when you need the complete word-for-word record.
    """
    db = get_db()
    meeting = db.get_meeting_by_id(meeting_id)

    if not meeting:
        return f"Meeting with ID {meeting_id} not found."

    if not meeting.get('transcript'):
        return f"No transcript available for meeting '{meeting['title']}'."

    lines = [
        f"# Transcript: {meeting['title']}",
        f"**Date:** {meeting['meeting_date'].strftime('%Y-%m-%d')}",
        "",
        meeting['transcript']
    ]

    return "\n".join(lines)


@mcp.tool()
def find_meeting_by_title(title_search: str) -> str:
    """Find meetings by title (partial match).

    Args:
        title_search: Part of the meeting title to search for

    Returns matching meetings so you can get their IDs for detailed queries.
    """
    db = get_db()
    meetings = db.get_meeting_by_title(title_search, limit=10)

    if not meetings:
        return f"No meetings found with title containing '{title_search}'."

    lines = [f"# Meetings matching '{title_search}'\n"]
    for m in meetings:
        lines.append(f"- {format_meeting_summary(m)}")

    lines.append("\nUse get_meeting_details(meeting_id) to see full details.")

    return "\n".join(lines)


@mcp.tool()
def get_meeting_stats() -> str:
    """Get overall statistics about your meeting archive.

    Returns counts of meetings, clients, and date ranges.
    """
    db = get_db()

    total_meetings = db.get_archived_count()
    clients = db.get_clients_with_meeting_counts()
    recent = db.get_recent_meetings(days=30)

    # Exclude Internal from stats
    real_clients = [c for c in clients if c['name'] != INTERNAL_CLIENT_NAME]

    lines = [
        "# Meeting Archive Statistics\n",
        f"**Total meetings archived:** {total_meetings}",
        f"**Total clients:** {len(real_clients)}",
        f"**Meetings in last 30 days:** {len(recent)}",
        "",
        "## Top Clients by Meeting Count"
    ]

    for client in real_clients[:5]:
        lines.append(f"- {client['name']}: {client['meeting_count']} meetings")

    return "\n".join(lines)


@mcp.tool()
def archive_new_meetings(limit: int = 50) -> str:
    """Archive new meetings from Granola to the database.

    Fetches recent meetings from Granola and archives any that aren't
    already in the database. Automatically detects and assigns clients
    based on meeting titles and attendee data.

    Args:
        limit: Maximum number of meetings to check (default 50)

    Returns:
        Summary of what was archived with client detection results.
    """
    logger.info(f"archive_new_meetings called with limit={limit}")

    db = get_db()

    # Get already archived document IDs
    try:
        archived_ids = db.get_archived_document_ids()
        logger.info(f"Found {len(archived_ids)} already archived meetings")
    except Exception as e:
        logger.exception(f"Error querying archived IDs: {e}")
        return f"Error querying database: {e}"

    # Get known client names for matching (exclude Internal to avoid false matches)
    try:
        known_clients = [c for c in db.get_client_names() if c != INTERNAL_CLIENT_NAME]
        logger.info(f"Found {len(known_clients)} known clients for matching")
    except Exception as e:
        logger.exception(f"Error fetching client names: {e}")
        known_clients = []

    # Get client aliases for matching
    try:
        aliases = db.get_client_aliases()
        logger.info(f"Found {len(aliases)} client aliases for matching")
    except Exception as e:
        logger.exception(f"Error fetching client aliases: {e}")
        aliases = {}

    # Initialize Granola client
    try:
        granola = GranolaClient()
        logger.info("Granola client initialized")
    except Exception as e:
        logger.exception(f"Error connecting to Granola: {e}")
        return f"Error connecting to Granola: {e}"

    # Fetch recent documents
    try:
        documents = granola.get_documents(limit=limit)
        logger.info(f"Fetched {len(documents)} documents from Granola")
    except Exception as e:
        logger.exception(f"Error fetching documents: {e}")
        return f"Error fetching from Granola: {e}"

    # Filter to unarchived meetings
    new_documents = []
    for doc in documents:
        doc_id = doc.get('id') or doc.get('document_id')
        if doc_id and doc_id not in archived_ids:
            new_documents.append(doc)

    if not new_documents:
        return f"All {len(documents)} recent meetings are already archived. Nothing new to add."

    # Archive each new meeting with auto-client detection
    archived_count = 0
    errors = []
    archived_details = []  # Track what was archived with client info

    for doc in new_documents:
        doc_id = doc.get('id') or doc.get('document_id')
        title = doc.get('title') or 'Untitled'
        meeting_date = doc.get('created_at') or doc.get('createdAt')

        try:
            # Get content parts
            content = granola.get_document_content_parts(doc, debug=False)

            # Extract attendees for client detection
            attendees = granola.get_document_attendees(doc)

            # Detect client from title and attendees
            detected_client = detect_client_from_meeting(
                title=title,
                attendees=attendees,
                known_clients=known_clients,
                aliases=aliases
            )

            # Get or create client ID if detected
            client_id = None
            if detected_client:
                client_id = db.get_or_create_client(detected_client)
                # Add to known clients for subsequent matches
                if detected_client not in known_clients:
                    known_clients.append(detected_client)
                    activity = ActivityLogService(db)
                    activity.log("client_created", f"New client created: {detected_client}",
                                 {"source": "mcp", "client": detected_client})

            # Archive to database with client
            meeting_id = db.archive_meeting(
                granola_document_id=doc_id,
                title=title,
                meeting_date=meeting_date,
                transcript=content.get('transcript'),
                enhanced_notes=content.get('enhanced_notes'),
                manual_notes=content.get('manual_notes'),
                combined_markdown=content.get('combined_markdown'),
                client_id=client_id
            )
            archived_count += 1

            # Activity log
            activity = ActivityLogService(db)
            if detected_client:
                activity.log("meeting_archived", f'Archived "{title}" \u2192 {detected_client}',
                             {"source": "mcp", "meeting_id": meeting_id, "client": detected_client})
            else:
                activity.log("meeting_archived", f'Archived "{title}" \u2014 no client detected',
                             {"source": "mcp", "meeting_id": meeting_id})

            # Track details for response (and for extraction)
            client_note = f" → {detected_client}" if detected_client else ""
            archived_details.append({
                "label": f"- {title[:50]}{client_note}",
                "meeting_id": meeting_id,
                "client_id": client_id,
                "title": title,
                "enhanced_notes": content.get('enhanced_notes'),
                "transcript": content.get('transcript'),
            })
            logger.info(f"Archived: {title[:50]} (client: {detected_client or 'none'})")

        except Exception as e:
            logger.exception(f"Error archiving {title}: {e}")
            errors.append(f"{title[:30]}: {e}")

    # AI todo extraction (post-archival, never blocks)
    extraction_lines = []
    activity = ActivityLogService(db)
    if TodoExtractionService.is_enabled() and archived_details:
        extractor = TodoExtractionService(db)
        for info in archived_details:
            if info["client_id"] is None:
                continue
            try:
                ext_result = extractor.extract_todos_from_meeting(
                    meeting_id=info["meeting_id"],
                    client_id=info["client_id"],
                    title=info["title"],
                    enhanced_notes=info.get("enhanced_notes"),
                    transcript=info.get("transcript"),
                )
                if not ext_result["skipped"] and not ext_result["error"]:
                    if ext_result["new_count"] or ext_result["completed_count"]:
                        extraction_lines.append(
                            f"- {info['title'][:50]}: +{ext_result['new_count']} new, "
                            f"{ext_result['completed_count']} completed"
                        )
                    activity.log("todos_extracted",
                                 f'Extracted todos from "{info["title"]}" \u2014 {ext_result["new_count"]} new, {ext_result["completed_count"]} completed',
                                 {"source": "mcp", "meeting_id": info["meeting_id"],
                                  "new_count": ext_result["new_count"], "completed_count": ext_result["completed_count"]})
                elif ext_result["error"]:
                    logger.warning(f"Extraction issue for {info['title'][:40]}: {ext_result['error']}")
                    activity.log("extraction_error", f'Extraction failed for "{info["title"]}"',
                                 {"source": "mcp", "meeting_id": info["meeting_id"], "error": ext_result["error"]})
            except Exception as e:
                logger.error(f"Todo extraction error for {info['title'][:40]}: {e}")
                activity.log("extraction_error", f'Extraction failed for "{info["title"]}"',
                             {"source": "mcp", "meeting_id": info["meeting_id"], "error": str(e)})

    # Build response
    lines = [
        "# Archive Results\n",
        f"**Checked:** {len(documents)} meetings",
        f"**Already archived:** {len(documents) - len(new_documents)}",
        f"**Newly archived:** {archived_count}",
    ]

    if archived_details:
        lines.append("\n## Archived Meetings")
        lines.extend(info["label"] for info in archived_details)

    if extraction_lines:
        lines.append("\n## AI Todo Extraction")
        lines.extend(extraction_lines)

    if errors:
        lines.append(f"\n**Errors:** {len(errors)}")
        for error in errors[:3]:
            lines.append(f"  - {error}")

    activity.log("archive_run",
                 f"Archive completed \u2014 {archived_count} archived, {len(errors)} errors",
                 {"source": "mcp", "archived": archived_count, "errors": len(errors)})

    return "\n".join(lines)


# Client Context Tools

@mcp.tool()
def add_client_context(
    client_name: str,
    title: str,
    content: str,
    context_type: str = "note",
    source_url: str = None
) -> str:
    """Add a context document for a client (PRD, estimate, outcome, etc.).

    Args:
        client_name: Name of the client (e.g., "NGynS", "Mothership")
        title: Title of the document (e.g., "Q1 2026 Estimate", "PRD v2")
        content: Full content/text of the document
        context_type: Type of document - prd, estimate, outcome, contract, or note (default: note)
        source_url: Optional URL link to original document (Google Doc, Notion, etc.)

    Returns:
        Confirmation with the created context ID.
    """
    db = get_db()

    # Get or create client
    client = db.get_client_by_name(client_name)
    if not client:
        client_id = db.get_or_create_client(client_name)
    else:
        client_id = client['id']

    context_id = db.add_client_context(
        client_id=client_id,
        title=title,
        content=content,
        context_type=context_type,
        source_url=source_url
    )

    return f"Saved '{title}' ({context_type}) for {client_name}. Context ID: {context_id}"


@mcp.tool()
def list_client_context(client_name: str) -> str:
    """List all context documents for a client.

    Args:
        client_name: Name of the client

    Returns:
        List of context documents with titles, types, and IDs.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"No client found with name '{client_name}'."

    contexts = db.list_client_context(client['id'])

    if not contexts:
        return f"No context documents found for {client_name}."

    lines = [f"# Context Documents for {client_name}\n"]
    for ctx in contexts:
        date_str = ctx['updated_at'].strftime('%Y-%m-%d')
        url_note = f" ([link]({ctx['source_url']}))" if ctx.get('source_url') else ""
        lines.append(f"- **[{ctx['id']}]** {ctx['title']} ({ctx['context_type']}) - {date_str}{url_note}")

    lines.append(f"\nUse `get_client_context(id)` to retrieve full content.")

    return "\n".join(lines)


@mcp.tool()
def get_client_context(context_id: int) -> str:
    """Get the full content of a specific context document.

    Args:
        context_id: Database ID of the context document (shown in brackets in list)

    Returns:
        Full content of the document with metadata.
    """
    db = get_db()

    ctx = db.get_client_context_by_id(context_id)

    if not ctx:
        return f"Context document with ID {context_id} not found."

    lines = [
        f"# {ctx['title']}",
        f"**Client:** {ctx['client_name']}",
        f"**Type:** {ctx['context_type']}",
        f"**Updated:** {ctx['updated_at'].strftime('%Y-%m-%d %H:%M')}",
    ]

    if ctx.get('source_url'):
        lines.append(f"**Source:** {ctx['source_url']}")

    lines.append("")
    lines.append(ctx['content'])

    return "\n".join(lines)


@mcp.tool()
def search_client_context(query: str, client_name: str = None) -> str:
    """Search across all client context documents.

    Args:
        query: Search term to find in context documents
        client_name: Optional - limit search to a specific client

    Returns:
        Matching documents with content previews.
    """
    db = get_db()

    client_id = None
    if client_name:
        client = db.get_client_by_name(client_name)
        if client:
            client_id = client['id']

    results = db.search_client_context(query, client_id=client_id)

    if not results:
        scope = f" for {client_name}" if client_name else ""
        return f"No context documents found matching '{query}'{scope}."

    lines = [f"# Search Results for '{query}'\n"]

    for ctx in results:
        lines.append(f"## [{ctx['id']}] {ctx['title']}")
        lines.append(f"*Client: {ctx['client_name']} | Type: {ctx['context_type']} | Relevance: {ctx['rank']:.2f}*\n")
        if ctx.get('content_preview'):
            lines.append(f"{ctx['content_preview']}...")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def update_client_context(
    context_id: int,
    content: str = None,
    title: str = None,
    context_type: str = None
) -> str:
    """Update an existing context document.

    Args:
        context_id: Database ID of the context to update
        content: New content (replaces existing)
        title: New title (optional)
        context_type: New type (optional)

    Returns:
        Confirmation of update.
    """
    db = get_db()

    # Verify it exists
    ctx = db.get_client_context_by_id(context_id)
    if not ctx:
        return f"Context document with ID {context_id} not found."

    success = db.update_client_context(
        context_id=context_id,
        title=title,
        content=content,
        context_type=context_type
    )

    if success:
        return f"Updated context document [{context_id}] '{ctx['title']}' for {ctx['client_name']}."
    else:
        return "No changes made (no update fields provided)."


@mcp.tool()
def delete_client_context(context_id: int) -> str:
    """Delete a context document.

    Args:
        context_id: Database ID of the context to delete

    Returns:
        Confirmation of deletion.
    """
    db = get_db()

    # Get info before deleting
    ctx = db.get_client_context_by_id(context_id)
    if not ctx:
        return f"Context document with ID {context_id} not found."

    success = db.delete_client_context(context_id)

    if success:
        return f"Deleted '{ctx['title']}' ({ctx['context_type']}) from {ctx['client_name']}."
    else:
        return f"Failed to delete context document {context_id}."


# To-Do Tools

PRIORITY_LABELS = {0: "None", 1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}


def _format_todos_table(todos: list, overdue_mode: bool = False) -> str:
    """Format a list of to-dos as a markdown table.

    Args:
        todos: List of todo dicts (must all be for the same client group or ungrouped).
        overdue_mode: If True, tag overdue items in the Due column.

    Returns:
        Markdown table string.
    """
    status_icons = {"pending": "\u2610", "in_progress": "\u25d1", "done": "\u2713", "archived": "\u2014"}
    priority_labels = {0: "", 1: "\U0001f534 Urgent", 2: "\U0001f7e0 High", 3: "Normal", 4: "Low"}

    header = "| Status | ID | Title | Priority | Category | Due | Source |"
    separator = "|--------|-----|-------|----------|----------|-----|--------|"
    rows = [header, separator]

    today = datetime.now().date()

    for todo in todos:
        icon = status_icons.get(todo['status'], "\u2610")
        pri = priority_labels.get(todo.get('priority', 0), "")
        cat = todo.get('category') or ""

        # Format due date compactly
        due = ""
        if todo.get('due_date'):
            try:
                due_date = todo['due_date']
                if isinstance(due_date, str):
                    due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
                due = due_date.strftime("%b %-d")
                if overdue_mode or (due_date < today and todo['status'] not in ('done', 'archived')):
                    due = f"\u26a0\ufe0f {due}"
            except (ValueError, TypeError):
                due = str(todo['due_date'])

        # Source column: meeting ref or source_context, truncated
        source = ""
        if todo.get('meeting_id'):
            source = f"mtg #{todo['meeting_id']}"
        elif todo.get('source_context'):
            ctx = todo['source_context']
            source = ctx if len(ctx) <= 20 else ctx[:18] + ".."

        rows.append(f"| {icon} | {todo['id']} | {todo['title']} | {pri} | {cat} | {due} | {source} |")

    return "\n".join(rows)


@mcp.tool()
def add_todo(
    client_name: str,
    title: str,
    description: str = None,
    priority: int = 0,
    due_date: str = None,
    category: str = None,
    meeting_id: int = None,
    source_context: str = None
) -> str:
    """Create a to-do item for a client.

    Args:
        client_name: Name of the client (e.g., "NGynS", "Mothership")
        title: Short actionable title for the to-do
        description: Optional longer description or details
        priority: 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low (matches Linear)
        due_date: Optional due date in ISO format (YYYY-MM-DD)
        category: Optional tag like "design", "follow-up", "billing"
        meeting_id: Optional meeting ID this to-do came from
        source_context: Optional provenance like "from workshop 2", "per Slack thread"

    Returns:
        Confirmation with the created to-do ID.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    todo = db.create_todo(
        client_id=client['id'],
        title=title,
        description=description,
        priority=priority,
        due_date=due_date,
        category=category,
        meeting_id=meeting_id,
        source_context=source_context
    )

    return f"Created to-do [{todo['id']}] for {client_name}: {title}"


@mcp.tool()
def add_todos_batch(
    client_name: str,
    items: list,
    meeting_id: int = None,
    source_context: str = None
) -> str:
    """Create multiple to-dos at once for a client.

    Use this when extracting action items from a meeting or conversation.
    Each item needs at minimum a 'title' key.

    Args:
        client_name: Name of the client
        items: List of items, each with: title (required), description, priority, due_date, category
        meeting_id: Optional meeting ID to link all items to
        source_context: Optional provenance for all items (e.g., "from weekly sync 2026-03-01")

    Returns:
        Summary of created to-dos with their IDs.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    if not items:
        return "No items provided."

    created = db.batch_create_todos(
        client_id=client['id'],
        items=items,
        meeting_id=meeting_id,
        source_context=source_context
    )

    lines = [f"# Created {len(created)} to-dos for {client_name}\n"]
    lines.append(_format_todos_table(created))

    return "\n".join(lines)


@mcp.tool()
def list_todos(
    client_name: str = None,
    status: str = None,
    category: str = None,
    include_done: bool = False,
    limit: int = 50
) -> str:
    """List to-do items with filtering.

    With no args, returns all open to-dos across all clients — the default dashboard view.

    Args:
        client_name: Optional - filter to a specific client
        status: Optional - filter by status: pending, in_progress, done, archived
        category: Optional - filter by category tag
        include_done: If true, include completed/archived items (default false)
        limit: Maximum number of results (default 50)

    Returns:
        Formatted list of to-dos grouped by client.
    """
    db = get_db()

    client_id = None
    if client_name:
        client = db.get_client_by_name(client_name)
        if not client:
            return f"Client '{client_name}' not found."
        client_id = client['id']

    todos = db.list_todos(
        client_id=client_id,
        status=status,
        category=category,
        include_done=include_done,
        limit=limit
    )

    if not todos:
        scope = f" for {client_name}" if client_name else ""
        return f"No to-dos found{scope}."

    # Group by client, Internal last
    by_client = {}
    for todo in todos:
        cname = todo['client_name']
        if cname not in by_client:
            by_client[cname] = []
        by_client[cname].append(todo)

    if INTERNAL_CLIENT_NAME in by_client:
        internal_todos = by_client.pop(INTERNAL_CLIENT_NAME)
        by_client[INTERNAL_CLIENT_NAME] = internal_todos

    lines = []
    for cname, client_todos in by_client.items():
        lines.append(f"## {cname} ({len(client_todos)} open)\n")
        lines.append(_format_todos_table(client_todos))
        lines.append("")

    lines.append(f"*{len(todos)} items shown*")
    return "\n".join(lines)


@mcp.tool()
def update_todo(
    todo_id: int,
    title: str = None,
    description: str = None,
    status: str = None,
    priority: int = None,
    due_date: str = None,
    category: str = None,
    meeting_id: int = None,
    source_context: str = None
) -> str:
    """Update any fields on a to-do item.

    Only provided fields are changed. Setting status to 'done' auto-sets completed_at.
    Reopening (status='pending' or 'in_progress') clears completed_at.

    Args:
        todo_id: Database ID of the to-do (shown in brackets in listings)
        title: New title
        description: New description
        status: New status: pending, in_progress, done, archived
        priority: New priority: 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low
        due_date: New due date (ISO YYYY-MM-DD)
        category: New category tag
        meeting_id: Link to a meeting ID
        source_context: Update provenance text

    Returns:
        Confirmation of update.
    """
    db = get_db()

    todo = db.get_todo(todo_id)
    if not todo:
        return f"To-do with ID {todo_id} not found."

    success = db.update_todo(
        todo_id=todo_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        due_date=due_date,
        category=category,
        meeting_id=meeting_id,
        source_context=source_context
    )

    if success:
        return f"Updated to-do [{todo_id}] '{todo['title']}' for {todo['client_name']}."
    else:
        return "No changes made (no update fields provided)."


@mcp.tool()
def complete_todo(todo_id: int) -> str:
    """Mark a to-do as done.

    Args:
        todo_id: Database ID of the to-do (shown in brackets in listings)

    Returns:
        Confirmation of completion.
    """
    db = get_db()

    todo = db.get_todo(todo_id)
    if not todo:
        return f"To-do with ID {todo_id} not found."

    success = db.complete_todo(todo_id)

    if success:
        return f"Completed to-do [{todo_id}] '{todo['title']}' for {todo['client_name']}."
    else:
        return f"Failed to complete to-do {todo_id}."


@mcp.tool()
def delete_todo(todo_id: int) -> str:
    """Permanently remove a to-do item.

    Args:
        todo_id: Database ID of the to-do to delete

    Returns:
        Confirmation of deletion.
    """
    db = get_db()

    todo = db.get_todo(todo_id)
    if not todo:
        return f"To-do with ID {todo_id} not found."

    success = db.delete_todo(todo_id)

    if success:
        return f"Deleted to-do [{todo_id}] '{todo['title']}' from {todo['client_name']}."
    else:
        return f"Failed to delete to-do {todo_id}."


@mcp.tool()
def list_overdue_todos(client_name: str = None, limit: int = 50) -> str:
    """Show overdue to-do items across all clients.

    Returns open to-dos where the due date has passed — useful for
    proactively surfacing what needs attention.

    Args:
        client_name: Optional - filter to a specific client
        limit: Maximum number of results (default 50)

    Returns:
        List of overdue to-dos grouped by client.
    """
    db = get_db()

    client_id = None
    if client_name:
        client = db.get_client_by_name(client_name)
        if not client:
            return f"Client '{client_name}' not found."
        client_id = client['id']

    todos = db.list_todos(
        client_id=client_id,
        overdue_only=True,
        limit=limit
    )

    if not todos:
        scope = f" for {client_name}" if client_name else ""
        return f"No overdue to-dos{scope}."

    by_client = {}
    for todo in todos:
        cname = todo['client_name']
        if cname not in by_client:
            by_client[cname] = []
        by_client[cname].append(todo)

    if INTERNAL_CLIENT_NAME in by_client:
        internal_todos = by_client.pop(INTERNAL_CLIENT_NAME)
        by_client[INTERNAL_CLIENT_NAME] = internal_todos

    lines = [f"# Overdue To-Dos\n"]
    for cname, client_todos in by_client.items():
        lines.append(f"## {cname} ({len(client_todos)} overdue)\n")
        lines.append(_format_todos_table(client_todos, overdue_mode=True))
        lines.append("")

    lines.append(f"*{len(todos)} overdue items*")
    return "\n".join(lines)


@mcp.tool()
def view_todos(client_name: str = None, include_done: bool = False) -> str:
    """Open the to-do dashboard in the browser.

    If the persistent dashboard is running (localhost:5555), opens that.
    Otherwise falls back to generating a static HTML snapshot.

    Args:
        client_name: Optional - filter to a specific client
        include_done: If true, include completed/archived items (default false)

    Returns:
        Confirmation message with item count.
    """
    import webbrowser
    import urllib.request

    # Try the persistent dashboard first
    dashboard_port = os.getenv("DASHBOARD_PORT", "5555")
    dashboard_url = f"http://localhost:{dashboard_port}/todos/"
    qs_parts = []
    if client_name:
        qs_parts.append(f"client={urllib.parse.quote(client_name)}")
    if include_done:
        qs_parts.append("done=1")
    if qs_parts:
        dashboard_url += "?" + "&".join(qs_parts)

    try:
        urllib.request.urlopen(f"http://localhost:{dashboard_port}/", timeout=1)
        webbrowser.open(dashboard_url)
        return f"Opened live dashboard at {dashboard_url}"
    except Exception:
        pass

    # Fallback: static HTML snapshot
    db = get_db()

    client_id = None
    if client_name:
        client = db.get_client_by_name(client_name)
        if not client:
            return f"Client '{client_name}' not found."
        client_id = client['id']

    todos = db.list_todos(
        client_id=client_id,
        include_done=include_done,
        limit=200
    )

    if not todos:
        scope = f" for {client_name}" if client_name else ""
        return f"No to-dos found{scope}."

    # Group by client
    by_client = {}
    for todo in todos:
        cname = todo['client_name']
        if cname not in by_client:
            by_client[cname] = []
        by_client[cname].append(todo)

    today = datetime.now().date()
    generated_at = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")

    # Build HTML
    html = _build_todos_html(by_client, today, generated_at)

    out_path = "/tmp/cereal-todos.html"
    with open(out_path, "w") as f:
        f.write(html)

    webbrowser.open(f"file://{out_path}")

    total = len(todos)
    client_count = len(by_client)
    return f"Opened static snapshot in browser with {total} items across {client_count} client{'s' if client_count != 1 else ''}."


def _build_todos_html(by_client: dict, today, generated_at: str) -> str:
    """Build self-contained HTML for the to-do dashboard."""
    priority_colors = {1: "#dc2626", 2: "#ea580c", 3: "#6b7280", 4: "#3b82f6"}
    priority_labels = {0: "", 1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}
    status_icons = {"pending": "&#9744;", "in_progress": "&#9684;", "done": "&#10003;", "archived": "&mdash;"}

    cards_html = ""
    for cname, todos in by_client.items():
        open_count = sum(1 for t in todos if t['status'] not in ('done', 'archived'))
        rows = ""
        for todo in todos:
            icon = status_icons.get(todo['status'], "&#9744;")
            done_class = " done" if todo['status'] in ('done', 'archived') else ""

            # Priority badge
            pri_val = todo.get('priority', 0)
            pri_label = priority_labels.get(pri_val, "")
            pri_color = priority_colors.get(pri_val, "#6b7280")
            pri_html = f'<span class="badge" style="background:{pri_color}">{pri_label}</span>' if pri_label else ""

            # Category pill
            cat = todo.get('category') or ""
            cat_html = f'<span class="cat">{cat}</span>' if cat else ""

            # Due date
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

            # Source
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

        cards_html += f"""<div class="client-card">
  <h2>{_html_escape(cname)} <span class="count">{open_count} open</span></h2>
  <table>
    <thead>
      <tr><th>Status</th><th>ID</th><th>Title</th><th>Priority</th><th>Category</th><th>Due</th><th>Source</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cereal &mdash; To-Dos</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8f9fa; color: #1a1a2e; padding: 2rem; }}
  .header {{ max-width: 960px; margin: 0 auto 1.5rem; display: flex; justify-content: space-between; align-items: baseline; }}
  .header h1 {{ font-size: 1.5rem; font-weight: 700; }}
  .header .timestamp {{ font-size: 0.8rem; color: #6b7280; }}
  .client-card {{ max-width: 960px; margin: 0 auto 1.5rem; background: #fff; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); padding: 1.25rem 1.5rem; }}
  .client-card h2 {{ font-size: 1.1rem; font-weight: 600; margin-bottom: 0.75rem; }}
  .client-card h2 .count {{ font-weight: 400; font-size: 0.85rem; color: #6b7280; }}
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
  <span class="timestamp">Snapshot: {generated_at}</span>
</div>
{cards_html}
</body>
</html>"""


def _html_escape(text: str) -> str:
    """Minimal HTML escaping for user content."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_LINEAR_KEY_RE = re.compile(r'\b([A-Z][A-Z0-9]+-\d+)\b')


def _linkify_linear(text: str) -> str:
    """HTML-escape text, then wrap Linear issue keys as clickable links."""
    escaped = _html_escape(text)
    return _LINEAR_KEY_RE.sub(
        r'<a href="https://linear.app/issue/\1" target="_blank">\1</a>',
        escaped
    )


def _match_todos(todos: list, search: str) -> list:
    return TodoService.match_todos(todos, search)


@mcp.tool()
def batch_update_todos(
    client_name: str,
    operations: list,
    source_context: str = None
) -> str:
    """Apply multiple to-do operations in one call — complete, update, and add.

    Designed for voice workflows where a single narration produces several
    changes. Matches existing to-dos by title substring (no ID lookup needed).

    Args:
        client_name: Name of the client (e.g., "NGynS", "Mothership")
        operations: List of operations, each a dict with an "action" key:
            - complete: {"action": "complete", "search": "<title substring>"}
            - update:   {"action": "update", "search": "<title substring>", ...fields to change}
                        Updatable fields: title, description, priority, due_date, category, status
            - add:      {"action": "add", "title": "...", "priority": 0, "due_date": "...", "category": "..."}
        source_context: Optional provenance applied to all add/update operations

    Returns:
        Markdown summary table of results per operation.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    if not operations:
        return "No operations provided."

    # Load open todos once for matching
    open_todos = db.list_todos(client_id=client['id'], include_done=False, limit=200)

    results = []
    for i, op in enumerate(operations, 1):
        action = op.get('action', '').lower()

        if action == 'add':
            title = op.get('title')
            if not title:
                results.append((i, 'add', 'error', '', '', 'missing title'))
                continue
            todo = db.create_todo(
                client_id=client['id'],
                title=title,
                description=op.get('description'),
                priority=op.get('priority', 0),
                due_date=op.get('due_date'),
                category=op.get('category'),
                meeting_id=op.get('meeting_id'),
                source_context=op.get('source_context', source_context)
            )
            # Add to open_todos so subsequent ops can match it
            todo['client_name'] = client_name
            open_todos.append(todo)
            results.append((i, 'add', 'created', todo['id'], todo['title'], ''))

        elif action in ('complete', 'update'):
            search = op.get('search', '')
            if not search:
                results.append((i, action, 'error', '', '', 'missing search'))
                continue
            matches = _match_todos(open_todos, search)
            if len(matches) == 0:
                results.append((i, action, 'no_match', '', search, f'no open todo matching "{search}"'))
            elif len(matches) > 1:
                candidates = ", ".join(f"[{m['id']}] {m['title']}" for m in matches[:5])
                results.append((i, action, 'ambiguous', '', search, f'{len(matches)} matches: {candidates}'))
            else:
                todo = matches[0]
                if action == 'complete':
                    db.complete_todo(todo['id'])
                    # Remove from open_todos so it won't match again
                    open_todos = [t for t in open_todos if t['id'] != todo['id']]
                    results.append((i, 'complete', 'done', todo['id'], todo['title'], ''))
                else:
                    fields = {}
                    for key in ('title', 'description', 'status', 'priority', 'due_date', 'category'):
                        if key in op:
                            fields[key] = op[key]
                    if source_context and 'source_context' not in op:
                        fields['source_context'] = source_context
                    elif 'source_context' in op:
                        fields['source_context'] = op['source_context']
                    details = ", ".join(f"{k}={v}" for k, v in fields.items())
                    db.update_todo(todo_id=todo['id'], **fields)
                    results.append((i, 'update', 'done', todo['id'], todo['title'], details))
        else:
            results.append((i, action or '?', 'error', '', '', f'unknown action "{action}"'))

    # Build summary
    ok = sum(1 for r in results if r[2] in ('done', 'created'))
    total = len(results)
    lines = [f"# Batch Update: {client_name} ({total} operations)\n"]
    lines.append("| # | Action | Result | ID | Title | Details |")
    lines.append("|---|--------|--------|----|-------|---------|")
    for num, action, result, tid, title, details in results:
        tid_str = str(tid) if tid else ""
        lines.append(f"| {num} | {action} | {result} | {tid_str} | {title} | {details} |")
    lines.append(f"\n*{ok}/{total} operations successful*")
    return "\n".join(lines)


# Client Management Tools

@mcp.tool()
def merge_clients(source_name: str, target_name: str) -> str:
    """Merge one client into another, reassigning all meetings and context.

    Use this to consolidate duplicate clients (e.g., "NB44 - Intuit" into "NB44").
    Creates an alias so future auto-detection recognizes the old name.

    Args:
        source_name: Client to merge FROM (will be deleted)
        target_name: Client to merge INTO (will be kept)

    Returns:
        Summary of what was merged and the alias created.
    """
    db = get_db()

    # Get source client
    source = db.get_client_by_name(source_name)
    if not source:
        return f"Source client '{source_name}' not found."

    # Get or create target client
    target = db.get_client_by_name(target_name)
    if not target:
        target_id = db.get_or_create_client(target_name)
    else:
        target_id = target['id']

    try:
        result = db.merge_clients(source['id'], target_id)

        lines = [
            f"# Merged \"{source_name}\" into \"{target_name}\"\n",
            f"- Reassigned {result['meetings_moved']} meetings",
            f"- Reassigned {result['context_moved']} context documents",
            f"- Created alias: \"{source_name}\" → \"{target_name}\"",
            f"- Deleted client \"{source_name}\"",
            "",
            f"Future meetings mentioning \"{source_name}\" will be assigned to \"{target_name}\"."
        ]
        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"Error merging clients: {e}")
        return f"Error merging clients: {e}"


@mcp.tool()
def rename_client(old_name: str, new_name: str) -> str:
    """Rename a client and create an alias for the old name.

    Future auto-detection will recognize both names and map to the new name.

    Args:
        old_name: Current client name
        new_name: New name for the client

    Returns:
        Confirmation of the rename.
    """
    db = get_db()

    client = db.get_client_by_name(old_name)
    if not client:
        return f"Client '{old_name}' not found."

    # Check if new name already exists
    existing = db.get_client_by_name(new_name)
    if existing:
        return f"Client '{new_name}' already exists. Use merge_clients instead."

    success = db.rename_client(client['id'], new_name)

    if success:
        return (
            f"Renamed \"{old_name}\" to \"{new_name}\".\n"
            f"Created alias: \"{old_name}\" → \"{new_name}\""
        )
    else:
        return f"Failed to rename client '{old_name}'."


@mcp.tool()
def add_client_alias(alias: str, client_name: str) -> str:
    """Add an alias that maps to an existing client.

    Future auto-detection will treat the alias as the client name.
    Use this to teach the system alternate names without merging.

    Args:
        alias: The alternate name to recognize (e.g., "Acme Corp")
        client_name: The canonical client name to map to (e.g., "Acme")

    Returns:
        Confirmation of the alias creation.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found. Create the client first."

    db.add_client_alias(alias, client['id'])

    return (
        f"Created alias: \"{alias}\" → \"{client_name}\"\n"
        f"Future meetings mentioning \"{alias}\" will be assigned to \"{client_name}\"."
    )


@mcp.tool()
def list_client_aliases(client_name: str = None) -> str:
    """List all client aliases, optionally filtered by client.

    Args:
        client_name: Optional - show aliases for this client only

    Returns:
        List of configured aliases.
    """
    db = get_db()

    if client_name:
        client = db.get_client_by_name(client_name)
        if not client:
            return f"Client '{client_name}' not found."

        aliases = db.get_aliases_for_client(client['id'])
        if not aliases:
            return f"No aliases configured for '{client_name}'."

        lines = [f"# Aliases for {client_name}\n"]
        for alias in aliases:
            lines.append(f"- \"{alias}\" → \"{client_name}\"")
        return "\n".join(lines)

    else:
        aliases = db.get_client_aliases()
        if not aliases:
            return "No aliases configured."

        lines = ["# All Client Aliases\n"]
        for alias, canonical in sorted(aliases.items()):
            lines.append(f"- \"{alias}\" → \"{canonical}\"")
        return "\n".join(lines)


@mcp.tool()
def delete_client_alias(alias: str) -> str:
    """Delete a client alias.

    Args:
        alias: The alias to remove

    Returns:
        Confirmation of deletion.
    """
    db = get_db()

    success = db.delete_client_alias(alias)

    if success:
        return f"Deleted alias \"{alias}\"."
    else:
        return f"Alias \"{alias}\" not found."


@mcp.tool()
def assign_meeting_to_client(meeting_id: int, client_name: str) -> str:
    """Assign a meeting to a client.

    Use this to manually associate a meeting with a client when
    auto-detection didn't work or the meeting was archived without a client.

    Args:
        meeting_id: Database ID of the meeting (shown in brackets in listings)
        client_name: Name of the client to assign to

    Returns:
        Confirmation of the assignment.
    """
    db = get_db()

    # Verify meeting exists
    meeting = db.get_meeting_by_id(meeting_id)
    if not meeting:
        return f"Meeting with ID {meeting_id} not found."

    # Get or create client
    client = db.get_client_by_name(client_name)
    if not client:
        client_id = db.get_or_create_client(client_name)
    else:
        client_id = client['id']

    # Assign the meeting
    success = db.assign_meeting_to_client(meeting_id, client_id)

    if success:
        return (
            f"Assigned meeting [{meeting_id}] \"{meeting['title']}\" to {client_name}."
        )
    else:
        return f"Failed to assign meeting {meeting_id}."


# Client Integration Tools (Linear teams, Slack channels, etc.)

@mcp.tool()
def link_client_to_linear_team(
    client_name: str,
    linear_team_id: str,
    linear_team_name: str = None,
    linear_team_key: str = None
) -> str:
    """Link a Cereal client to a Linear team for cross-system correlation.

    Use this to establish a mapping between a Cereal client and a Linear team.
    Once linked, Claude can correlate data across both systems using the ID.

    Args:
        client_name: Name of the Cereal client
        linear_team_id: Linear team ID (e.g., "team_abc123")
        linear_team_name: Optional human-readable team name
        linear_team_key: Optional team key/prefix used in issue IDs (e.g., "WANDER" from "WANDER-504")

    Returns:
        Confirmation of the link.
    """
    db = get_db()

    # Get or create client
    client = db.get_client_by_name(client_name)
    if not client:
        client_id = db.get_or_create_client(client_name)
    else:
        client_id = client['id']

    # Check if this Linear team is already linked to another client
    existing = db.get_client_by_integration('linear_team', linear_team_id)
    if existing and existing['id'] != client_id:
        return (
            f"Linear team '{linear_team_id}' is already linked to client "
            f"'{existing['name']}'. Unlink it first."
        )

    metadata = {}
    if linear_team_key:
        metadata['team_key'] = linear_team_key

    # Create the link
    db.set_client_integration(
        client_id=client_id,
        integration_type='linear_team',
        external_id=linear_team_id,
        external_name=linear_team_name,
        metadata=metadata
    )

    name_note = f" ({linear_team_name})" if linear_team_name else ""
    key_note = f" [key: {linear_team_key}]" if linear_team_key else ""
    return (
        f"Linked client \"{client_name}\" to Linear team {linear_team_id}{name_note}{key_note}.\n"
        f"Claude can now correlate meetings and issues across both systems."
    )


@mcp.tool()
def get_client_linear_team(client_name: str) -> str:
    """Get the Linear team linked to a client.

    Args:
        client_name: Name of the client

    Returns:
        Linear team info if linked, or a message if not linked.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    integration = db.get_client_integration(client['id'], 'linear_team')

    if not integration:
        return f"Client '{client_name}' is not linked to a Linear team."

    name_note = f" ({integration['external_name']})" if integration['external_name'] else ""
    metadata = integration.get('metadata') or {}
    team_key = metadata.get('team_key')

    lines = [
        f"# Linear Team for {client_name}\n",
        f"**Team ID:** {integration['external_id']}{name_note}",
    ]
    if team_key:
        lines.append(f"**Team Key:** {team_key}")
    lines.append(f"**Linked:** {integration['created_at'].strftime('%Y-%m-%d')}")

    return "\n".join(lines)


@mcp.tool()
def list_integration_status() -> str:
    """Show all clients and their integration mappings.

    Lists all clients with their linked integrations (Linear teams,
    Slack channels, etc.), plus clients that are not yet linked.
    Useful for identifying unmapped clients.

    Returns:
        Status of all client integrations.
    """
    db = get_db()

    # Get all clients with meeting counts
    clients = db.get_clients_with_meeting_counts()

    # Get all integrations (all types)
    integrations = db.list_client_integrations()
    integration_map = {}
    for i in integrations:
        integration_map.setdefault(i['client_id'], []).append(i)

    linked = []
    unlinked = []

    for client in clients:
        client_integrations = integration_map.get(client['id'], [])
        if client_integrations:
            parts = [f"- **{client['name']}** ({client['meeting_count']} meetings)"]
            for ci in client_integrations:
                metadata = ci.get('metadata') or {}
                itype = ci['integration_type']

                if itype == 'linear_team':
                    name_note = f" ({ci['external_name']})" if ci['external_name'] else ""
                    key_note = f" [key: {metadata.get('team_key')}]" if metadata.get('team_key') else ""
                    parts.append(f"  - Linear: {ci['external_id']}{name_note}{key_note}")
                elif itype == 'slack':
                    ext_id = metadata.get('external_channel_id')
                    ext_note = f", external: {ext_id}" if ext_id else ""
                    parts.append(f"  - Slack: internal: {ci['external_id']}{ext_note}")
                else:
                    name_note = f" ({ci['external_name']})" if ci['external_name'] else ""
                    parts.append(f"  - {itype}: {ci['external_id']}{name_note}")

            linked.append("\n".join(parts))
        else:
            unlinked.append(
                f"- **{client['name']}** ({client['meeting_count']} meetings)"
            )

    lines = ["# Client Integration Status\n"]

    if linked:
        lines.append("## Linked\n")
        lines.extend(linked)
        lines.append("")

    if unlinked:
        lines.append("## Not Linked\n")
        lines.extend(unlinked)

    if not linked and not unlinked:
        lines.append("No clients found.")

    return "\n".join(lines)


@mcp.tool()
def unlink_client_integration(client_name: str, integration_type: str = "linear_team") -> str:
    """Remove an integration link from a client.

    Args:
        client_name: Name of the client to unlink
        integration_type: Type of integration to remove (default: "linear_team")

    Returns:
        Confirmation of the unlink.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    # Check if integration exists
    integration = db.get_client_integration(client['id'], integration_type)
    if not integration:
        return f"Client '{client_name}' is not linked to a {integration_type.replace('_', ' ')}."

    success = db.delete_client_integration(client['id'], integration_type)

    if success:
        return (
            f"Unlinked '{client_name}' from {integration_type.replace('_', ' ')} "
            f"'{integration['external_id']}'."
        )
    else:
        return f"Failed to unlink client '{client_name}'."


@mcp.tool()
def link_client_to_slack(
    client_name: str,
    internal_channel_id: str,
    external_channel_id: str = None
) -> str:
    """Link a Cereal client to Slack channels.

    Each client has an internal Slack channel (required) and optionally
    an external/shared channel for client-facing communication.

    Args:
        client_name: Name of the Cereal client
        internal_channel_id: Slack channel ID for the internal team channel
        external_channel_id: Optional Slack channel ID for the external/shared channel

    Returns:
        Confirmation of the link.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        client_id = db.get_or_create_client(client_name)
    else:
        client_id = client['id']

    metadata = {}
    if external_channel_id:
        metadata['external_channel_id'] = external_channel_id

    db.set_client_integration(
        client_id=client_id,
        integration_type='slack',
        external_id=internal_channel_id,
        metadata=metadata
    )

    lines = [f"Linked client \"{client_name}\" to Slack:"]
    lines.append(f"  Internal: {internal_channel_id}")
    if external_channel_id:
        lines.append(f"  External: {external_channel_id}")

    return "\n".join(lines)


@mcp.tool()
def get_client_slack(client_name: str) -> str:
    """Get the Slack channels linked to a client.

    Args:
        client_name: Name of the client

    Returns:
        Slack channel IDs if linked, or a message if not linked.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    integration = db.get_client_integration(client['id'], 'slack')

    if not integration:
        return f"Client '{client_name}' is not linked to Slack channels."

    metadata = integration.get('metadata') or {}

    lines = [
        f"# Slack Channels for {client_name}\n",
        f"**Internal:** {integration['external_id']}",
    ]

    ext_id = metadata.get('external_channel_id')
    if ext_id:
        lines.append(f"**External:** {ext_id}")

    lines.append(f"**Linked:** {integration['created_at'].strftime('%Y-%m-%d')}")

    return "\n".join(lines)


@mcp.tool()
def get_client_config(client_name: str) -> str:
    """Get all integration data for a client in one call.

    Returns Linear team (ID, name, key), Slack channels, and any other
    configured integrations. Use this instead of calling get_client_linear_team
    and get_client_slack separately.

    Args:
        client_name: Name of the client

    Returns:
        All integration data for the client.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    integrations = db.list_client_integrations(client_id=client['id'])

    if not integrations:
        return f"Client '{client_name}' has no integrations configured."

    lines = [f"# Configuration for {client_name}\n"]

    for integration in integrations:
        itype = integration['integration_type']
        metadata = integration.get('metadata') or {}

        if itype == 'linear_team':
            name_note = f" ({integration['external_name']})" if integration['external_name'] else ""
            lines.append("## Linear Team")
            lines.append(f"**Team ID:** {integration['external_id']}{name_note}")
            team_key = metadata.get('team_key')
            if team_key:
                lines.append(f"**Team Key:** {team_key}")
            lines.append("")

        elif itype == 'slack':
            lines.append("## Slack Channels")
            lines.append(f"**Internal:** {integration['external_id']}")
            ext_id = metadata.get('external_channel_id')
            if ext_id:
                lines.append(f"**External:** {ext_id}")
            lines.append("")

        else:
            name_note = f" ({integration['external_name']})" if integration['external_name'] else ""
            lines.append(f"## {itype.replace('_', ' ').title()}")
            lines.append(f"**ID:** {integration['external_id']}{name_note}")
            if metadata:
                for k, v in metadata.items():
                    lines.append(f"**{k.replace('_', ' ').title()}:** {v}")
            lines.append("")

    return "\n".join(lines)


# Timeline Tools

@mcp.tool()
def create_timeline(
    client_name: str,
    project_name: str,
    sow_signed_date: str = None,
    design_weeks_low: float = None,
    design_weeks_high: float = None,
    dev_weeks_low: float = None,
    dev_weeks_high: float = None,
    overall_weeks_low: float = None,
    overall_weeks_high: float = None,
    auto_create_phases: bool = True
) -> str:
    """Create a new project timeline for a client.

    Creates the timeline and optionally the standard Goji phase structure:
    Strategy Sprint (with 4 workshops), Design Phase (with 5 subphases), Dev Phase.

    Args:
        client_name: Client name (e.g., "NGynS", "Ways2Wander")
        project_name: Project name (e.g., "Physician Directory v2")
        sow_signed_date: Optional ISO date when SOW was signed
        design_weeks_low: Estimated design phase duration (low end)
        design_weeks_high: Estimated design phase duration (high end)
        dev_weeks_low: Estimated dev phase duration (low end)
        dev_weeks_high: Estimated dev phase duration (high end)
        overall_weeks_low: Estimated overall duration (low end)
        overall_weeks_high: Estimated overall duration (high end)
        auto_create_phases: If true, create standard Goji phase structure (default true)

    Returns:
        Timeline ID and summary of what was created.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        client_id = db.get_or_create_client(client_name)
    else:
        client_id = client['id']

    timeline_id = db.create_timeline(
        client_id=client_id,
        project_name=project_name,
        sow_signed_date=sow_signed_date,
        estimated_design_weeks_low=design_weeks_low,
        estimated_design_weeks_high=design_weeks_high,
        estimated_dev_weeks_low=dev_weeks_low,
        estimated_dev_weeks_high=dev_weeks_high,
        estimated_overall_weeks_low=overall_weeks_low,
        estimated_overall_weeks_high=overall_weeks_high
    )

    lines = [
        f"# Timeline Created\n",
        f"**Timeline ID:** {timeline_id}",
        f"**Client:** {client_name}",
        f"**Project:** {project_name}",
    ]

    if sow_signed_date:
        lines.append(f"**SOW Signed:** {sow_signed_date}")

    estimates = []
    if design_weeks_low and design_weeks_high:
        estimates.append(f"Design: {design_weeks_low}-{design_weeks_high} weeks")
    if dev_weeks_low and dev_weeks_high:
        estimates.append(f"Dev: {dev_weeks_low}-{dev_weeks_high} weeks")
    if overall_weeks_low and overall_weeks_high:
        estimates.append(f"Overall: {overall_weeks_low}-{overall_weeks_high} weeks")
    if estimates:
        lines.append(f"**Estimates:** {', '.join(estimates)}")

    if auto_create_phases:
        # Strategy Sprint
        strategy_id = db.create_phase(
            timeline_id=timeline_id,
            name="Strategy Sprint",
            phase_type="strategy",
            sort_order=0
        )
        # Create 4 workshops
        for i in range(1, 5):
            db.create_workshop(phase_id=strategy_id, workshop_number=i)

        # Design Phase
        design_id = db.create_phase(
            timeline_id=timeline_id,
            name="Design Phase",
            phase_type="design",
            sort_order=1,
            planned_duration_weeks_low=design_weeks_low,
            planned_duration_weeks_high=design_weeks_high
        )
        # Design subphases
        design_subphases = [
            "User Flow IA + Low-fis",
            "UI Exploration",
            "Design System",
            "High-fis",
            "Revisions / Hand-off"
        ]
        for i, subphase_name in enumerate(design_subphases):
            db.create_phase(
                timeline_id=timeline_id,
                name=subphase_name,
                phase_type="design_subphase",
                sort_order=i,
                parent_phase_id=design_id
            )

        # Dev Phase
        db.create_phase(
            timeline_id=timeline_id,
            name="Dev Phase",
            phase_type="dev",
            sort_order=2,
            planned_duration_weeks_low=dev_weeks_low,
            planned_duration_weeks_high=dev_weeks_high
        )

        lines.append("")
        lines.append("## Auto-created Phases")
        lines.append("- Strategy Sprint (4 workshops)")
        lines.append("- Design Phase")
        lines.append("  - User Flow IA + Low-fis")
        lines.append("  - UI Exploration")
        lines.append("  - Design System")
        lines.append("  - High-fis")
        lines.append("  - Revisions / Hand-off")
        lines.append("- Dev Phase")

    return "\n".join(lines)


@mcp.tool()
def get_timeline(
    client_name: str,
    project_name: str = None,
    include_linear_status: bool = False
) -> str:
    """Get a client's project timeline with phases, milestones, and status.

    Args:
        client_name: Client name
        project_name: Specific project name (if client has multiple timelines)
        include_linear_status: If true, include Linear project IDs for cross-referencing

    Returns:
        Full timeline structure with phase statuses.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    timelines = db.get_timelines_for_client(client['id'])
    if not timelines:
        return f"No timelines found for '{client_name}'."

    # Find the right timeline
    timeline = None
    if project_name:
        for t in timelines:
            if t['project_name'].lower() == project_name.lower():
                timeline = t
                break
        if not timeline:
            names = [t['project_name'] for t in timelines]
            return f"No timeline '{project_name}' for {client_name}. Available: {', '.join(names)}"
    else:
        # Default to most recent active timeline
        active = [t for t in timelines if t['status'] == 'active']
        timeline = active[0] if active else timelines[0]

    # Build the response
    lines = [f"# {timeline['project_name']} — {client_name}\n"]
    lines.append(f"**Status:** {timeline['status']}")
    lines.append(f"**Timeline ID:** {timeline['id']}")

    if timeline.get('sow_signed_date'):
        lines.append(f"**SOW Signed:** {timeline['sow_signed_date']}")

    estimates = []
    if timeline.get('estimated_design_weeks_low') and timeline.get('estimated_design_weeks_high'):
        estimates.append(f"Design: {timeline['estimated_design_weeks_low']}-{timeline['estimated_design_weeks_high']} weeks")
    if timeline.get('estimated_dev_weeks_low') and timeline.get('estimated_dev_weeks_high'):
        estimates.append(f"Dev: {timeline['estimated_dev_weeks_low']}-{timeline['estimated_dev_weeks_high']} weeks")
    if timeline.get('estimated_overall_weeks_low') and timeline.get('estimated_overall_weeks_high'):
        estimates.append(f"Overall: {timeline['estimated_overall_weeks_low']}-{timeline['estimated_overall_weeks_high']} weeks")
    if estimates:
        lines.append(f"**Estimates:** {', '.join(estimates)}")

    if timeline.get('notes'):
        lines.append(f"**Notes:** {timeline['notes']}")

    # Get phases
    phases = db.get_phases_for_timeline(timeline['id'])
    top_level = [p for p in phases if p['parent_phase_id'] is None]

    lines.append("\n## Phases\n")

    for phase in top_level:
        status_icon = {"upcoming": "⏳", "in_progress": "🔄", "completed": "✅", "skipped": "⏭️"}.get(phase['status'], "")
        lines.append(f"### {status_icon} {phase['name']} ({phase['status']})")
        lines.append(f"*Phase ID: {phase['id']} | Type: {phase['phase_type']}*")

        if phase.get('actual_start_date'):
            lines.append(f"Started: {phase['actual_start_date']}")
        if phase.get('actual_end_date'):
            lines.append(f"Ended: {phase['actual_end_date']}")
        if phase.get('planned_duration_weeks_low') and phase.get('planned_duration_weeks_high'):
            lines.append(f"Planned: {phase['planned_duration_weeks_low']}-{phase['planned_duration_weeks_high']} weeks")
        if phase.get('linear_project_id') and include_linear_status:
            lines.append(f"Linear Project: {phase['linear_project_id']}")

        # Subphases
        subphases = [p for p in phases if p['parent_phase_id'] == phase['id']]
        if subphases:
            for sub in sorted(subphases, key=lambda s: s['sort_order']):
                sub_icon = {"upcoming": "⏳", "in_progress": "🔄", "completed": "✅", "skipped": "⏭️"}.get(sub['status'], "")
                lines.append(f"  - {sub_icon} {sub['name']} ({sub['status']}) [ID: {sub['id']}]")

        # Workshops (for strategy phases)
        if phase['phase_type'] == 'strategy':
            workshops = db.get_workshops_for_phase(phase['id'])
            if workshops:
                lines.append("  **Workshops:**")
                for w in workshops:
                    w_icon = {"scheduled": "📅", "completed": "✅", "cancelled": "❌", "rescheduled": "🔄"}.get(w['status'], "")
                    date_str = ""
                    if w.get('actual_date'):
                        date_str = f" ({w['actual_date']})"
                    elif w.get('scheduled_date'):
                        date_str = f" (scheduled: {w['scheduled_date']})"
                    meeting_note = f" — Meeting ID: {w['meeting_id']}" if w.get('meeting_id') else ""
                    lines.append(f"  - {w_icon} Workshop {w['workshop_number']}: {w['status']}{date_str}{meeting_note}")

        # Milestones
        milestones = db.get_milestones_for_phase(phase['id'])
        if milestones:
            lines.append("  **Milestones:**")
            for m in milestones:
                m_icon = {"pending": "⏳", "achieved": "✅", "missed": "❌", "deferred": "↩️"}.get(m['status'], "")
                date_str = ""
                if m.get('actual_date'):
                    date_str = f" (achieved: {m['actual_date']})"
                elif m.get('target_date'):
                    date_str = f" (target: {m['target_date']})"
                lines.append(f"  - {m_icon} {m['name']}: {m['status']}{date_str} [ID: {m['id']}]")

        lines.append("")

    # Linear mappings
    if include_linear_status:
        mappings = db.get_linear_mappings_for_timeline(timeline['id'])
        if mappings:
            lines.append("## Linear Mappings\n")
            for mapping in mappings:
                target = mapping.get('phase_name') or mapping.get('milestone_name') or 'Unknown'
                lines.append(f"- **{target}** → Linear Project: {mapping['linear_project_id']}")
                if mapping.get('linear_project_name'):
                    lines.append(f"  Name: {mapping['linear_project_name']}")

    return "\n".join(lines)


@mcp.tool()
def list_timelines(
    client_name: str = None,
    status: str = None
) -> str:
    """List all project timelines, optionally filtered by client or status.

    Args:
        client_name: Optional - filter to a specific client
        status: Optional - filter by timeline status (active, completed, paused, cancelled)

    Returns:
        Summary list of timelines with current phase and health.
    """
    db = get_db()

    if client_name:
        client = db.get_client_by_name(client_name)
        if not client:
            return f"Client '{client_name}' not found."
        timelines = db.get_timelines_for_client(client['id'], status=status)
    else:
        timelines = db.list_timelines(status=status)

    if not timelines:
        scope = f" for {client_name}" if client_name else ""
        status_note = f" with status '{status}'" if status else ""
        return f"No timelines found{scope}{status_note}."

    lines = ["# Project Timelines\n"]

    for t in timelines:
        lines.append(f"## {t['client_name']} — {t['project_name']}")
        lines.append(f"*Timeline ID: {t['id']} | Status: {t['status']}*")

        estimates = []
        if t.get('estimated_overall_weeks_low') and t.get('estimated_overall_weeks_high'):
            estimates.append(f"Overall: {t['estimated_overall_weeks_low']}-{t['estimated_overall_weeks_high']} weeks")
        if estimates:
            lines.append(f"Estimates: {', '.join(estimates)}")

        # Find current active phase
        phases = db.get_phases_for_timeline(t['id'])
        active_phases = [p for p in phases if p['status'] == 'in_progress' and p['parent_phase_id'] is None]
        if active_phases:
            phase = active_phases[0]
            lines.append(f"Current phase: **{phase['name']}**")
            # Check for active subphase
            active_subs = [p for p in phases if p['status'] == 'in_progress' and p['parent_phase_id'] == phase['id']]
            if active_subs:
                lines.append(f"Current subphase: {active_subs[0]['name']}")

        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def update_phase(
    phase_id: int,
    status: str = None,
    actual_start_date: str = None,
    actual_end_date: str = None,
    linear_project_id: str = None,
    notes: str = None
) -> str:
    """Update a timeline phase's status, dates, or notes.

    Args:
        phase_id: Phase ID
        status: New status (upcoming, in_progress, completed, skipped)
        actual_start_date: ISO date when phase actually started
        actual_end_date: ISO date when phase actually ended
        linear_project_id: Link to a Linear project UUID
        notes: Phase notes

    Returns:
        Updated phase details.
    """
    db = get_db()

    phase = db.get_phase(phase_id)
    if not phase:
        return f"Phase {phase_id} not found."

    kwargs = {}
    if status is not None:
        kwargs['status'] = status
    if actual_start_date is not None:
        kwargs['actual_start_date'] = actual_start_date
    if actual_end_date is not None:
        kwargs['actual_end_date'] = actual_end_date
    if linear_project_id is not None:
        kwargs['linear_project_id'] = linear_project_id
    if notes is not None:
        kwargs['notes'] = notes

    if not kwargs:
        return "No updates provided."

    success = db.update_phase(phase_id, **kwargs)

    if success:
        updated = db.get_phase(phase_id)
        lines = [
            f"# Updated Phase: {updated['name']}\n",
            f"**Status:** {updated['status']}",
        ]
        if updated.get('actual_start_date'):
            lines.append(f"**Started:** {updated['actual_start_date']}")
        if updated.get('actual_end_date'):
            lines.append(f"**Ended:** {updated['actual_end_date']}")
        if updated.get('linear_project_id'):
            lines.append(f"**Linear Project:** {updated['linear_project_id']}")
        if updated.get('notes'):
            lines.append(f"**Notes:** {updated['notes']}")
        return "\n".join(lines)
    else:
        return f"Failed to update phase {phase_id}."


@mcp.tool()
def add_milestone(
    phase_id: int,
    name: str,
    description: str = None,
    target_date: str = None,
    linear_issue_id: str = None,
    linear_project_id: str = None
) -> str:
    """Add a new milestone to a timeline phase.

    Args:
        phase_id: Phase to add the milestone to
        name: Milestone name (e.g., "Low-fi Approval", "Beta Launch")
        description: Optional description
        target_date: Optional target date (ISO format)
        linear_issue_id: Optional link to a Linear issue
        linear_project_id: Optional link to a Linear project

    Returns:
        Created milestone details.
    """
    db = get_db()

    phase = db.get_phase(phase_id)
    if not phase:
        return f"Phase {phase_id} not found."

    milestone_id = db.create_milestone(
        phase_id=phase_id,
        name=name,
        description=description,
        target_date=target_date,
        linear_issue_id=linear_issue_id,
        linear_project_id=linear_project_id
    )

    lines = [
        f"# Milestone Created\n",
        f"**ID:** {milestone_id}",
        f"**Name:** {name}",
        f"**Phase:** {phase['name']}",
    ]
    if target_date:
        lines.append(f"**Target:** {target_date}")
    if description:
        lines.append(f"**Description:** {description}")

    return "\n".join(lines)


@mcp.tool()
def update_milestone(
    milestone_id: int,
    status: str = None,
    actual_date: str = None,
    meeting_id: int = None,
    linear_issue_id: str = None
) -> str:
    """Update a milestone's status and dates.

    Args:
        milestone_id: Milestone ID
        status: New status (pending, achieved, missed, deferred)
        actual_date: ISO date when milestone was achieved
        meeting_id: Link to a Cereal meeting
        linear_issue_id: Link to a Linear issue

    Returns:
        Updated milestone details.
    """
    db = get_db()

    milestone = db.get_milestone(milestone_id)
    if not milestone:
        return f"Milestone {milestone_id} not found."

    kwargs = {}
    if status is not None:
        kwargs['status'] = status
    if actual_date is not None:
        kwargs['actual_date'] = actual_date
    if meeting_id is not None:
        kwargs['meeting_id'] = meeting_id
    if linear_issue_id is not None:
        kwargs['linear_issue_id'] = linear_issue_id

    if not kwargs:
        return "No updates provided."

    success = db.update_milestone(milestone_id, **kwargs)

    if success:
        updated = db.get_milestone(milestone_id)
        lines = [
            f"# Updated Milestone: {updated['name']}\n",
            f"**Status:** {updated['status']}",
        ]
        if updated.get('target_date'):
            lines.append(f"**Target:** {updated['target_date']}")
        if updated.get('actual_date'):
            lines.append(f"**Achieved:** {updated['actual_date']}")
        return "\n".join(lines)
    else:
        return f"Failed to update milestone {milestone_id}."


@mcp.tool()
def record_workshop(
    phase_id: int,
    workshop_number: int,
    date: str = None,
    meeting_id: int = None
) -> str:
    """Record a Strategy Sprint workshop completion.

    Args:
        phase_id: The Strategy Sprint phase ID
        workshop_number: Workshop number (1-4)
        date: Date of the workshop (ISO format, defaults to today)
        meeting_id: Optional link to Cereal meeting record

    Returns:
        Updated workshop details.
    """
    db = get_db()

    phase = db.get_phase(phase_id)
    if not phase:
        return f"Phase {phase_id} not found."

    if phase['phase_type'] != 'strategy':
        return f"Phase {phase_id} ({phase['name']}) is not a Strategy Sprint phase."

    workshops = db.get_workshops_for_phase(phase_id)
    target = None
    for w in workshops:
        if w['workshop_number'] == workshop_number:
            target = w
            break

    if not target:
        return f"Workshop {workshop_number} not found for phase {phase_id}."

    today = datetime.now().strftime('%Y-%m-%d')
    kwargs = {
        'status': 'completed',
        'actual_date': date or today
    }
    if meeting_id is not None:
        kwargs['meeting_id'] = meeting_id

    db.update_workshop(target['id'], **kwargs)

    return (
        f"Recorded Workshop {workshop_number} as completed on {kwargs['actual_date']}."
        + (f" Linked to meeting ID {meeting_id}." if meeting_id else "")
    )


@mcp.tool()
def map_linear_to_phase(
    phase_id: int,
    linear_project_id: str,
    linear_project_name: str = None
) -> str:
    """Connect a Linear project to a timeline phase for progress tracking.

    Args:
        phase_id: Timeline phase ID
        linear_project_id: Linear project UUID
        linear_project_name: Optional human-readable project name

    Returns:
        Confirmation of mapping.
    """
    db = get_db()

    phase = db.get_phase(phase_id)
    if not phase:
        return f"Phase {phase_id} not found."

    # Also set on the phase itself for quick access
    db.update_phase(phase_id, linear_project_id=linear_project_id)

    mapping_id = db.create_linear_mapping(
        timeline_id=phase['timeline_id'],
        phase_id=phase_id,
        linear_project_id=linear_project_id,
        linear_project_name=linear_project_name
    )

    name_note = f" ({linear_project_name})" if linear_project_name else ""
    return (
        f"Mapped Linear project {linear_project_id}{name_note} "
        f"to phase \"{phase['name']}\" (mapping ID: {mapping_id})."
    )


@mcp.tool()
def map_linear_to_milestone(
    milestone_id: int,
    linear_issue_id: str = None,
    linear_project_id: str = None
) -> str:
    """Connect a Linear issue or project to a timeline milestone.

    Args:
        milestone_id: Timeline milestone ID
        linear_issue_id: Optional Linear issue UUID
        linear_project_id: Optional Linear project UUID

    Returns:
        Confirmation of mapping.
    """
    db = get_db()

    milestone = db.get_milestone(milestone_id)
    if not milestone:
        return f"Milestone {milestone_id} not found."

    if not linear_issue_id and not linear_project_id:
        return "Provide at least one of linear_issue_id or linear_project_id."

    # Update the milestone itself
    update_kwargs = {}
    if linear_issue_id:
        update_kwargs['linear_issue_id'] = linear_issue_id
    if linear_project_id:
        update_kwargs['linear_project_id'] = linear_project_id
    db.update_milestone(milestone_id, **update_kwargs)

    # Get the phase to find the timeline_id
    phase = db.get_phase(milestone['phase_id'])

    mapping_id = db.create_linear_mapping(
        timeline_id=phase['timeline_id'],
        milestone_id=milestone_id,
        linear_project_id=linear_project_id,
        linear_milestone_id=linear_issue_id
    )

    parts = []
    if linear_issue_id:
        parts.append(f"issue {linear_issue_id}")
    if linear_project_id:
        parts.append(f"project {linear_project_id}")

    return (
        f"Mapped Linear {' and '.join(parts)} "
        f"to milestone \"{milestone['name']}\" (mapping ID: {mapping_id})."
    )


@mcp.tool()
def assess_project_health(
    client_name: str,
    project_name: str = None,
    save_snapshot: bool = True
) -> str:
    """Assess project health by cross-referencing timeline, meetings, and Linear data.

    Returns timeline status, time elapsed vs estimated, Linear project IDs for
    cross-referencing, and recent meeting context. Claude should use the returned
    Linear project IDs to query Linear MCP for ticket breakdowns, then synthesize
    the full picture.

    Args:
        client_name: Client name
        project_name: Specific project (defaults to active timeline)
        save_snapshot: Whether to persist the assessment (default true)

    Returns:
        Structured assessment data including Linear project IDs for cross-referencing.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    # Find timeline
    timelines = db.get_timelines_for_client(client['id'])
    if not timelines:
        return f"No timelines found for '{client_name}'. Create one with create_timeline."

    timeline = None
    if project_name:
        for t in timelines:
            if t['project_name'].lower() == project_name.lower():
                timeline = t
                break
        if not timeline:
            return f"No timeline '{project_name}' found for {client_name}."
    else:
        active = [t for t in timelines if t['status'] == 'active']
        timeline = active[0] if active else timelines[0]

    # Gather timeline data
    phases = db.get_phases_for_timeline(timeline['id'])
    top_phases = [p for p in phases if p['parent_phase_id'] is None]
    active_phase = None
    active_subphase = None

    for p in top_phases:
        if p['status'] == 'in_progress':
            active_phase = p
            subs = [s for s in phases if s['parent_phase_id'] == p['id'] and s['status'] == 'in_progress']
            if subs:
                active_subphase = subs[0]
            break

    # Time calculations
    today = datetime.now().date()
    time_info = []

    if active_phase and active_phase.get('actual_start_date'):
        start = active_phase['actual_start_date']
        if hasattr(start, 'date'):
            start = start.date() if hasattr(start, 'date') else start
        elapsed_days = (today - start).days
        elapsed_weeks = round(elapsed_days / 7, 1)
        time_info.append(f"Phase started: {start}")
        time_info.append(f"Weeks elapsed: {elapsed_weeks}")

        if active_phase.get('planned_duration_weeks_low') and active_phase.get('planned_duration_weeks_high'):
            low = float(active_phase['planned_duration_weeks_low'])
            high = float(active_phase['planned_duration_weeks_high'])
            pct_of_low = round((elapsed_weeks / low) * 100, 0) if low > 0 else 0
            pct_of_high = round((elapsed_weeks / high) * 100, 0) if high > 0 else 0
            time_info.append(f"Planned duration: {low}-{high} weeks")
            time_info.append(f"Time used: {pct_of_low}% of low estimate, {pct_of_high}% of high estimate")

    if timeline.get('sow_signed_date'):
        sow_date = timeline['sow_signed_date']
        if hasattr(sow_date, 'date'):
            sow_date = sow_date.date() if hasattr(sow_date, 'date') else sow_date
        total_elapsed = (today - sow_date).days
        total_weeks = round(total_elapsed / 7, 1)
        time_info.append(f"Total weeks since SOW: {total_weeks}")
        if timeline.get('estimated_overall_weeks_low') and timeline.get('estimated_overall_weeks_high'):
            time_info.append(f"Overall estimate: {timeline['estimated_overall_weeks_low']}-{timeline['estimated_overall_weeks_high']} weeks")

    # Collect Linear project IDs for cross-referencing
    linear_ids = []
    mappings = db.get_linear_mappings_for_timeline(timeline['id'])
    for m in mappings:
        if m.get('linear_project_id'):
            target = m.get('phase_name') or m.get('milestone_name') or 'Unknown'
            linear_ids.append({
                'project_id': m['linear_project_id'],
                'name': m.get('linear_project_name', ''),
                'target': target
            })

    # Also check phases directly
    for p in phases:
        if p.get('linear_project_id'):
            already = any(l['project_id'] == p['linear_project_id'] for l in linear_ids)
            if not already:
                linear_ids.append({
                    'project_id': p['linear_project_id'],
                    'name': '',
                    'target': p['name']
                })

    # Get client integration for Linear team ID
    integration = db.get_client_integration(client['id'], 'linear_team')

    # Recent meetings
    recent_meetings = db.get_meetings_by_client(client_name, limit=5)

    # Build response
    lines = [f"# Project Health Assessment: {timeline['project_name']} ({client_name})\n"]

    lines.append(f"**Timeline Status:** {timeline['status']}")

    if active_phase:
        lines.append(f"**Current Phase:** {active_phase['name']}")
        if active_subphase:
            lines.append(f"**Current Subphase:** {active_subphase['name']}")
    else:
        completed = [p for p in top_phases if p['status'] == 'completed']
        upcoming = [p for p in top_phases if p['status'] == 'upcoming']
        if completed and upcoming:
            lines.append(f"**Last Completed:** {completed[-1]['name']}")
            lines.append(f"**Next Up:** {upcoming[0]['name']}")

    if time_info:
        lines.append("\n## Time Tracking")
        for info in time_info:
            lines.append(f"- {info}")

    # Phase summary
    lines.append("\n## Phase Status")
    for p in top_phases:
        lines.append(f"- **{p['name']}**: {p['status']}")

    if linear_ids:
        lines.append("\n## Linear Projects (query these for ticket breakdown)")
        for lid in linear_ids:
            name_note = f" — {lid['name']}" if lid['name'] else ""
            lines.append(f"- **{lid['target']}**: `{lid['project_id']}`{name_note}")

    if integration:
        metadata = integration.get('metadata') or {}
        lines.append(f"\n**Linear Team:** {integration['external_id']}")
        if metadata.get('team_key'):
            lines.append(f"**Team Key:** {metadata['team_key']}")

    if recent_meetings:
        lines.append("\n## Recent Meetings")
        for m in recent_meetings[:5]:
            date_str = m['meeting_date'].strftime('%Y-%m-%d')
            lines.append(f"- [{m['id']}] {date_str} — {m['title']}")
            if m.get('summary_overview'):
                lines.append(f"  {m['summary_overview'][:200]}")

    # Workshops status
    strategy_phases = [p for p in top_phases if p['phase_type'] == 'strategy']
    for sp in strategy_phases:
        workshops = db.get_workshops_for_phase(sp['id'])
        if workshops:
            completed_w = sum(1 for w in workshops if w['status'] == 'completed')
            lines.append(f"\n**Strategy Workshops:** {completed_w}/4 completed")

    lines.append("\n---")
    lines.append("*Use the Linear project IDs above to query Linear MCP for detailed ticket breakdowns.*")
    lines.append("*Use get_client_slack to find Slack channels for additional context.*")

    return "\n".join(lines)


@mcp.tool()
def get_project_snapshots(
    client_name: str,
    project_name: str = None,
    limit: int = 10,
    since: str = None
) -> str:
    """Retrieve historical health assessments for a project.

    Args:
        client_name: Client name
        project_name: Specific project (optional)
        limit: Maximum number of snapshots to return (default 10)
        since: Optional ISO date - only return snapshots after this date

    Returns:
        List of snapshots showing project health trajectory.
    """
    db = get_db()

    client = db.get_client_by_name(client_name)
    if not client:
        return f"Client '{client_name}' not found."

    timelines = db.get_timelines_for_client(client['id'])
    if not timelines:
        return f"No timelines found for '{client_name}'."

    timeline = None
    if project_name:
        for t in timelines:
            if t['project_name'].lower() == project_name.lower():
                timeline = t
                break
    else:
        active = [t for t in timelines if t['status'] == 'active']
        timeline = active[0] if active else timelines[0]

    if not timeline:
        return f"No matching timeline found for '{client_name}'."

    snapshots = db.get_snapshots(timeline['id'], limit=limit, since=since)

    if not snapshots:
        return f"No health snapshots found for '{timeline['project_name']}'."

    lines = [f"# Health History: {timeline['project_name']} ({client_name})\n"]

    for s in snapshots:
        health_icon = {"on_track": "🟢", "at_risk": "🟡", "off_track": "🔴"}.get(s['health'], "⚪")
        date_str = s['snapshot_date'].strftime('%Y-%m-%d %H:%M')
        lines.append(f"## {health_icon} {date_str} — {s['health'].replace('_', ' ').title()}")
        lines.append(f"*Phase: {s['current_phase']} | Triggered by: {s.get('triggered_by', 'unknown')}*\n")
        lines.append(s['summary'])

        if s.get('linear_stats'):
            stats = s['linear_stats']
            lines.append(f"\nLinear: {json.dumps(stats)}")

        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    logger.info("Starting MCP server...")
    try:
        mcp.run()
    except Exception as e:
        logger.exception(f"MCP server error: {e}")
        raise
