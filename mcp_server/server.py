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


# Internal domain for detecting external attendees
INTERNAL_DOMAIN = os.getenv("INTERNAL_DOMAIN", "gojilabs.com")


def detect_client_from_meeting(
    title: str,
    attendees: List[dict],
    known_clients: List[str],
    aliases: Optional[dict] = None
) -> Optional[str]:
    """
    Detect client from meeting title and attendee data.

    Detection priority:
    0. Alias match (highest priority - user-defined mappings)
    1. Known client name appears in title
    2. Title patterns like "Client x Goji", "Client:", "Record Client"
    3. External attendee company name (if only one external company)

    Args:
        title: Meeting title
        attendees: List of attendee dicts with 'email' and 'company' keys
        known_clients: List of known client names from database
        aliases: Dict mapping alias (lowercase) → canonical client name

    Returns:
        Client name if detected, None otherwise
    """
    if not title:
        return None
    title_lower = title.lower()

    # 0. Check aliases FIRST (highest priority - user-defined mappings)
    if aliases:
        for alias, canonical in aliases.items():
            if alias in title_lower:
                return canonical

    # 1. Known client match (case-insensitive)
    for client in known_clients:
        if client.lower() in title_lower:
            return client

    # 2. Title pattern extraction
    patterns = [
        r'^([A-Za-z0-9]+)\s+x\s+Goji',       # "NGynS x Goji"
        r'^([A-Za-z0-9]+):',                  # "GS1: ..."
        r'^Record\s+([A-Za-z0-9]+)',          # "Record NB44 ..."
    ]
    for pattern in patterns:
        match = re.match(pattern, title, re.IGNORECASE)
        if match:
            return match.group(1)

    # 3. External attendee detection
    external_companies = set()
    for att in attendees:
        email = att.get('email', '')
        if email and not email.endswith(f'@{INTERNAL_DOMAIN}'):
            company = att.get('company')
            if company and company.lower() not in ['unknown', 'goji labs', 'gojilabs']:
                external_companies.add(company)

    if len(external_companies) == 1:
        return external_companies.pop()

    return None


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

    return format_meeting_details(meeting, include_transcript=True)


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

    # Get known client names for matching
    try:
        known_clients = db.get_client_names()
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

            # Archive to database with client
            db.archive_meeting(
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

            # Track details for response
            client_note = f" → {detected_client}" if detected_client else ""
            archived_details.append(f"- {title[:50]}{client_note}")
            logger.info(f"Archived: {title[:50]} (client: {detected_client or 'none'})")

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

    if archived_details:
        lines.append("\n## Archived Meetings")
        lines.extend(archived_details)

    if errors:
        lines.append(f"\n**Errors:** {len(errors)}")
        for error in errors[:3]:
            lines.append(f"  - {error}")

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


if __name__ == "__main__":
    logger.info("Starting MCP server...")
    try:
        mcp.run()
    except Exception as e:
        logger.exception(f"MCP server error: {e}")
        raise
