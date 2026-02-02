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
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

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

    lines = ["# Clients\n"]
    for client in clients:
        lines.append(f"- **{client['name']}**: {client['meeting_count']} meetings")

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

    lines = [
        "# Meeting Archive Statistics\n",
        f"**Total meetings archived:** {total_meetings}",
        f"**Total clients:** {len(clients)}",
        f"**Meetings in last 30 days:** {len(recent)}",
        "",
        "## Top Clients by Meeting Count"
    ]

    for client in clients[:5]:
        lines.append(f"- {client['name']}: {client['meeting_count']} meetings")

    return "\n".join(lines)


@mcp.tool()
def archive_new_meetings(limit: int = 50) -> str:
    """Archive new meetings from Granola to the database.

    Fetches recent meetings from Granola and archives any that aren't
    already in the database. Use this to sync your latest meetings.

    Args:
        limit: Maximum number of meetings to check (default 50)

    Returns:
        Summary of what was archived.
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

    # Archive each new meeting
    archived_count = 0
    errors = []

    for doc in new_documents:
        doc_id = doc.get('id') or doc.get('document_id')
        title = doc.get('title', 'Untitled')
        meeting_date = doc.get('created_at') or doc.get('createdAt')

        try:
            # Get content parts
            content = granola.get_document_content_parts(doc, debug=False)

            # Archive to database
            db.archive_meeting(
                granola_document_id=doc_id,
                title=title,
                meeting_date=meeting_date,
                transcript=content.get('transcript'),
                enhanced_notes=content.get('enhanced_notes'),
                manual_notes=content.get('manual_notes'),
                combined_markdown=content.get('combined_markdown')
            )
            archived_count += 1
            logger.info(f"Archived: {title[:50]}")

        except Exception as e:
            logger.exception(f"Error archiving {title}: {e}")
            errors.append(f"{title[:30]}: {e}")

    # Build response
    lines = [
        "# Archive Results\n",
        f"**Checked:** {len(documents)} meetings",
        f"**Already archived:** {len(documents) - len(new_documents)}",
        f"**Newly archived:** {archived_count}",
    ]

    if errors:
        lines.append(f"**Errors:** {len(errors)}")
        for error in errors[:3]:
            lines.append(f"  - {error}")

    return "\n".join(lines)


if __name__ == "__main__":
    logger.info("Starting MCP server...")
    try:
        mcp.run()
    except Exception as e:
        logger.exception(f"MCP server error: {e}")
        raise
