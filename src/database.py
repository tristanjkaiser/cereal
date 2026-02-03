"""
Database module for PM Agent.

Handles PostgreSQL connection and meeting archival operations.
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


class DatabaseManager:
    """Manages PostgreSQL database connections and operations."""

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize database manager.

        Args:
            database_url: PostgreSQL connection string.
                         If None, reads from DATABASE_URL env var.
        """
        if not PSYCOPG2_AVAILABLE:
            raise ImportError(
                "psycopg2 is required for database functionality. "
                "Install with: pip install psycopg2-binary"
            )

        self.database_url = database_url or os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL not provided. Set DATABASE_URL environment variable "
                "or pass database_url parameter."
            )

    @contextmanager
    def get_connection(self):
        """Get a database connection as a context manager."""
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def get_cursor(self, dict_cursor: bool = True):
        """Get a database cursor as a context manager."""
        with self.get_connection() as conn:
            cursor_factory = RealDictCursor if dict_cursor else None
            cursor = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
            finally:
                cursor.close()

    def setup_schema(self) -> None:
        """Create database tables if they don't exist."""
        schema_path = Path(__file__).parent.parent / "scripts" / "setup_database.sql"

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        with self.get_cursor() as cursor:
            cursor.execute(schema_sql)

        print("Database schema created/verified successfully.")

    def is_archived(self, granola_document_id: str) -> bool:
        """
        Check if a meeting has been archived.

        Args:
            granola_document_id: The Granola document ID

        Returns:
            True if meeting exists in database
        """
        with self.get_cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM meetings WHERE granola_document_id = %s",
                (granola_document_id,)
            )
            return cursor.fetchone() is not None

    def archive_meeting(
        self,
        granola_document_id: str,
        title: str,
        meeting_date: str,
        transcript: Optional[str] = None,
        enhanced_notes: Optional[str] = None,
        manual_notes: Optional[str] = None,
        combined_markdown: Optional[str] = None,
        meeting_type: str = "general",
        meeting_type_confidence: Optional[float] = None,
        summary_overview: Optional[str] = None,
        summary_json: Optional[Dict] = None,
        client_id: Optional[int] = None,
        meeting_series_id: Optional[int] = None,
        processed_at: Optional[str] = None
    ) -> int:
        """
        Archive a meeting to the database.

        Args:
            granola_document_id: Unique Granola document ID
            title: Meeting title
            meeting_date: ISO format meeting date
            transcript: Raw transcript with speaker labels
            enhanced_notes: Granola's AI-generated notes
            manual_notes: User-typed notes
            combined_markdown: Full markdown sent to AI
            meeting_type: Detected meeting type
            meeting_type_confidence: Confidence score 0-1
            summary_overview: AI-generated summary
            summary_json: Full summary structure as dict
            client_id: Optional client foreign key
            meeting_series_id: Optional series foreign key
            processed_at: When the meeting was processed

        Returns:
            The database ID of the archived meeting
        """
        # Parse meeting_date if it's a string
        if isinstance(meeting_date, str):
            try:
                meeting_date_parsed = datetime.fromisoformat(
                    meeting_date.replace('Z', '+00:00')
                )
            except ValueError:
                meeting_date_parsed = datetime.now()
        else:
            meeting_date_parsed = meeting_date

        # Parse processed_at
        processed_at_parsed = None
        if processed_at:
            try:
                processed_at_parsed = datetime.fromisoformat(
                    processed_at.replace('Z', '+00:00')
                )
            except ValueError:
                pass

        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO meetings (
                    granola_document_id, title, meeting_date,
                    transcript, enhanced_notes, manual_notes, combined_markdown,
                    meeting_type, meeting_type_confidence,
                    summary_overview, summary_json,
                    client_id, meeting_series_id, processed_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (granola_document_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    transcript = EXCLUDED.transcript,
                    enhanced_notes = EXCLUDED.enhanced_notes,
                    manual_notes = EXCLUDED.manual_notes,
                    combined_markdown = EXCLUDED.combined_markdown,
                    meeting_type = EXCLUDED.meeting_type,
                    meeting_type_confidence = EXCLUDED.meeting_type_confidence,
                    summary_overview = EXCLUDED.summary_overview,
                    summary_json = EXCLUDED.summary_json,
                    client_id = EXCLUDED.client_id,
                    meeting_series_id = EXCLUDED.meeting_series_id,
                    processed_at = EXCLUDED.processed_at,
                    archived_at = NOW()
                RETURNING id
            """, (
                granola_document_id, title, meeting_date_parsed,
                transcript, enhanced_notes, manual_notes, combined_markdown,
                meeting_type, meeting_type_confidence,
                summary_overview, Json(summary_json) if summary_json else None,
                client_id, meeting_series_id, processed_at_parsed
            ))

            result = cursor.fetchone()
            return result['id'] if result else None

    def get_meeting(self, granola_document_id: str) -> Optional[Dict]:
        """
        Retrieve a meeting by its Granola document ID.

        Args:
            granola_document_id: The Granola document ID

        Returns:
            Meeting record as dictionary, or None if not found
        """
        with self.get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM meetings WHERE granola_document_id = %s",
                (granola_document_id,)
            )
            return cursor.fetchone()

    def get_all_meetings(
        self,
        limit: int = 100,
        offset: int = 0,
        client_id: Optional[int] = None,
        meeting_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve meetings with optional filtering.

        Args:
            limit: Maximum number of meetings to return
            offset: Offset for pagination
            client_id: Filter by client ID
            meeting_type: Filter by meeting type

        Returns:
            List of meeting records
        """
        query = "SELECT * FROM meetings WHERE 1=1"
        params: List[Any] = []

        if client_id is not None:
            query += " AND client_id = %s"
            params.append(client_id)

        if meeting_type is not None:
            query += " AND meeting_type = %s"
            params.append(meeting_type)

        query += " ORDER BY meeting_date DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def get_archived_count(self) -> int:
        """Get total count of archived meetings."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM meetings")
            result = cursor.fetchone()
            return result['count'] if result else 0

    def get_archived_document_ids(self) -> set:
        """Get set of all archived Granola document IDs."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT granola_document_id FROM meetings")
            return {row['granola_document_id'] for row in cursor.fetchall()}

    # Client management methods

    def create_client(self, name: str, slug: Optional[str] = None, notes: Optional[str] = None) -> int:
        """
        Create a new client.

        Args:
            name: Client/company name
            slug: URL-friendly identifier
            notes: Optional notes about the client

        Returns:
            The database ID of the created client
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO clients (name, slug, notes)
                VALUES (%s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    slug = COALESCE(EXCLUDED.slug, clients.slug),
                    notes = COALESCE(EXCLUDED.notes, clients.notes)
                RETURNING id
            """, (name, slug, notes))

            result = cursor.fetchone()
            return result['id'] if result else None

    def get_client_by_name(self, name: str) -> Optional[Dict]:
        """Get a client by name."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM clients WHERE name = %s", (name,))
            return cursor.fetchone()

    def get_all_clients(self) -> List[Dict]:
        """Get all clients."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM clients ORDER BY name")
            return cursor.fetchall()

    def get_client_names(self) -> List[str]:
        """Get list of all client names for matching."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT name FROM clients ORDER BY name")
            return [row['name'] for row in cursor.fetchall()]

    # Client alias methods

    def add_client_alias(self, alias: str, client_id: int) -> int:
        """
        Add an alias that maps to a client.

        Args:
            alias: The alternate name to recognize
            client_id: The canonical client ID to map to

        Returns:
            The database ID of the created alias
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO client_aliases (alias, canonical_client_id)
                VALUES (%s, %s)
                ON CONFLICT (alias) DO UPDATE SET canonical_client_id = EXCLUDED.canonical_client_id
                RETURNING id
            """, (alias.lower(), client_id))
            result = cursor.fetchone()
            return result['id'] if result else None

    def get_client_aliases(self) -> Dict[str, str]:
        """
        Get all client aliases as a mapping.

        Returns:
            Dict mapping alias (lowercase) → canonical client name
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT ca.alias, c.name as canonical_name
                FROM client_aliases ca
                JOIN clients c ON ca.canonical_client_id = c.id
                ORDER BY ca.alias
            """)
            return {row['alias']: row['canonical_name'] for row in cursor.fetchall()}

    def get_aliases_for_client(self, client_id: int) -> List[str]:
        """Get all aliases for a specific client."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT alias FROM client_aliases
                WHERE canonical_client_id = %s
                ORDER BY alias
            """, (client_id,))
            return [row['alias'] for row in cursor.fetchall()]

    def delete_client_alias(self, alias: str) -> bool:
        """Delete a client alias."""
        with self.get_cursor() as cursor:
            cursor.execute(
                "DELETE FROM client_aliases WHERE alias = %s",
                (alias.lower(),)
            )
            return cursor.rowcount > 0

    def rename_client(self, client_id: int, new_name: str) -> bool:
        """
        Rename a client and create an alias for the old name.

        Args:
            client_id: The client to rename
            new_name: The new name for the client

        Returns:
            True if successful
        """
        with self.get_cursor() as cursor:
            # Get the old name first
            cursor.execute("SELECT name FROM clients WHERE id = %s", (client_id,))
            result = cursor.fetchone()
            if not result:
                return False

            old_name = result['name']

            # Update the client name
            cursor.execute(
                "UPDATE clients SET name = %s WHERE id = %s",
                (new_name, client_id)
            )

            # Create alias for old name → new client
            cursor.execute("""
                INSERT INTO client_aliases (alias, canonical_client_id)
                VALUES (%s, %s)
                ON CONFLICT (alias) DO UPDATE SET canonical_client_id = EXCLUDED.canonical_client_id
            """, (old_name.lower(), client_id))

            return True

    def merge_clients(self, source_id: int, target_id: int) -> Dict[str, int]:
        """
        Merge source client into target client.

        Reassigns all meetings and context from source to target,
        creates an alias, and deletes the source client.

        Args:
            source_id: Client to merge FROM (will be deleted)
            target_id: Client to merge INTO (will be kept)

        Returns:
            Dict with counts: meetings_moved, context_moved
        """
        with self.get_cursor() as cursor:
            # Get source client name for alias
            cursor.execute("SELECT name FROM clients WHERE id = %s", (source_id,))
            source = cursor.fetchone()
            if not source:
                raise ValueError(f"Source client {source_id} not found")

            source_name = source['name']

            # Reassign meetings
            cursor.execute(
                "UPDATE meetings SET client_id = %s WHERE client_id = %s",
                (target_id, source_id)
            )
            meetings_moved = cursor.rowcount

            # Reassign client context
            cursor.execute(
                "UPDATE client_context SET client_id = %s WHERE client_id = %s",
                (target_id, source_id)
            )
            context_moved = cursor.rowcount

            # Create alias for source name → target
            cursor.execute("""
                INSERT INTO client_aliases (alias, canonical_client_id)
                VALUES (%s, %s)
                ON CONFLICT (alias) DO UPDATE SET canonical_client_id = EXCLUDED.canonical_client_id
            """, (source_name.lower(), target_id))

            # Delete source client (cascade will delete any remaining aliases)
            cursor.execute("DELETE FROM clients WHERE id = %s", (source_id,))

            return {
                'meetings_moved': meetings_moved,
                'context_moved': context_moved
            }

    def assign_meeting_to_client(self, meeting_id: int, client_id: Optional[int]) -> bool:
        """
        Assign a meeting to a client (or unassign if client_id is None).

        Args:
            meeting_id: The meeting to update
            client_id: The client to assign to (or None to unassign)

        Returns:
            True if the meeting was found and updated
        """
        with self.get_cursor() as cursor:
            cursor.execute(
                "UPDATE meetings SET client_id = %s WHERE id = %s",
                (client_id, meeting_id)
            )
            return cursor.rowcount > 0

    # Meeting series management methods

    def create_meeting_series(
        self,
        name: str,
        client_id: Optional[int] = None,
        meeting_type: Optional[str] = None,
        recurrence_pattern: Optional[str] = None,
        notes: Optional[str] = None
    ) -> int:
        """
        Create a new meeting series.

        Args:
            name: Series name (e.g., "Weekly Standup")
            client_id: Optional client foreign key
            meeting_type: Default meeting type for this series
            recurrence_pattern: weekly, biweekly, monthly, etc.
            notes: Optional notes

        Returns:
            The database ID of the created series
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO meeting_series (name, client_id, meeting_type, recurrence_pattern, notes)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (name, client_id, meeting_type, recurrence_pattern, notes))

            result = cursor.fetchone()
            return result['id'] if result else None

    def get_all_meeting_series(self) -> List[Dict]:
        """Get all meeting series."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT ms.*, c.name as client_name
                FROM meeting_series ms
                LEFT JOIN clients c ON ms.client_id = c.id
                ORDER BY ms.name
            """)
            return cursor.fetchall()


    # Query methods for interactive search

    def get_meeting_by_id(self, meeting_id: int) -> Optional[Dict]:
        """Get a meeting by its database ID."""
        with self.get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM meetings WHERE id = %s",
                (meeting_id,)
            )
            return cursor.fetchone()

    def get_meeting_by_title(self, title_search: str, limit: int = 10) -> List[Dict]:
        """
        Find meetings by title (case-insensitive partial match).

        Args:
            title_search: Search string for title
            limit: Maximum results

        Returns:
            List of matching meetings
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM meetings
                WHERE title ILIKE %s
                ORDER BY meeting_date DESC
                LIMIT %s
            """, (f'%{title_search}%', limit))
            return cursor.fetchall()

    def search_meetings(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Full-text search across meeting transcripts and notes.

        Args:
            query: Search query string
            limit: Maximum results

        Returns:
            List of matching meetings with relevance rank
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT m.*,
                       ts_rank(
                           to_tsvector('english', COALESCE(m.transcript, '') || ' ' ||
                                       COALESCE(m.enhanced_notes, '') || ' ' ||
                                       COALESCE(m.summary_overview, '')),
                           plainto_tsquery('english', %s)
                       ) as rank
                FROM meetings m
                WHERE to_tsvector('english', COALESCE(m.transcript, '') || ' ' ||
                      COALESCE(m.enhanced_notes, '') || ' ' ||
                      COALESCE(m.summary_overview, ''))
                      @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC, meeting_date DESC
                LIMIT %s
            """, (query, query, limit))
            return cursor.fetchall()

    def get_meetings_by_client(
        self,
        client_name: str,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get all meetings for a client by name.

        Args:
            client_name: Client name (case-insensitive)
            limit: Maximum results

        Returns:
            List of meetings for the client
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT m.*, c.name as client_name
                FROM meetings m
                JOIN clients c ON m.client_id = c.id
                WHERE c.name ILIKE %s
                ORDER BY m.meeting_date DESC
                LIMIT %s
            """, (client_name, limit))
            return cursor.fetchall()

    def get_untagged_meetings(self, limit: int = 100) -> List[Dict]:
        """Get meetings without a client assigned."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM meetings
                WHERE client_id IS NULL
                ORDER BY meeting_date DESC
                LIMIT %s
            """, (limit,))
            return cursor.fetchall()

    def update_meeting_client(self, meeting_id: int, client_id: int) -> bool:
        """
        Update the client for a meeting.

        Args:
            meeting_id: Database ID of the meeting
            client_id: Database ID of the client

        Returns:
            True if update was successful
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                UPDATE meetings SET client_id = %s WHERE id = %s
            """, (client_id, meeting_id))
            return cursor.rowcount > 0

    def get_or_create_client(self, name: str) -> int:
        """
        Get existing client or create new one.

        Args:
            name: Client name

        Returns:
            Client ID
        """
        # Generate slug from name
        slug = name.lower().replace(' ', '-').replace('_', '-')

        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO clients (name, slug)
                VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """, (name, slug))
            result = cursor.fetchone()
            return result['id']

    def get_clients_with_meeting_counts(self) -> List[Dict]:
        """Get all clients with their meeting counts."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT c.*, COUNT(m.id) as meeting_count
                FROM clients c
                LEFT JOIN meetings m ON c.id = m.client_id
                GROUP BY c.id
                ORDER BY meeting_count DESC, c.name
            """)
            return cursor.fetchall()

    def get_recent_meetings(
        self,
        days: int = 7,
        client_id: Optional[int] = None
    ) -> List[Dict]:
        """
        Get meetings from the last N days.

        Args:
            days: Number of days to look back
            client_id: Optional client filter

        Returns:
            List of recent meetings
        """
        query = """
            SELECT m.*, c.name as client_name
            FROM meetings m
            LEFT JOIN clients c ON m.client_id = c.id
            WHERE m.meeting_date >= NOW() - INTERVAL '%s days'
        """
        params: List[Any] = [days]

        if client_id is not None:
            query += " AND m.client_id = %s"
            params.append(client_id)

        query += " ORDER BY m.meeting_date DESC"

        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    # Client context methods

    def add_client_context(
        self,
        client_id: int,
        title: str,
        content: str,
        context_type: str = "note",
        source_url: Optional[str] = None
    ) -> int:
        """
        Add a context document for a client.

        Args:
            client_id: Database ID of the client
            title: Title of the document
            content: Full content/text
            context_type: Type (prd, estimate, outcome, contract, note)
            source_url: Optional link to original document

        Returns:
            The database ID of the created context
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO client_context (client_id, title, content, context_type, source_url)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (client_id, title, content, context_type, source_url))
            result = cursor.fetchone()
            return result['id'] if result else None

    def get_client_context_by_id(self, context_id: int) -> Optional[Dict]:
        """Get a context document by its ID."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT cc.*, c.name as client_name
                FROM client_context cc
                JOIN clients c ON cc.client_id = c.id
                WHERE cc.id = %s
            """, (context_id,))
            return cursor.fetchone()

    def list_client_context(self, client_id: int) -> List[Dict]:
        """
        List all context documents for a client.

        Returns list with id, title, context_type, created_at (no content for efficiency).
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, title, context_type, source_url, created_at, updated_at
                FROM client_context
                WHERE client_id = %s
                ORDER BY updated_at DESC
            """, (client_id,))
            return cursor.fetchall()

    def search_client_context(
        self,
        query: str,
        client_id: Optional[int] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Full-text search across client context documents.

        Args:
            query: Search query
            client_id: Optional filter by client
            limit: Maximum results

        Returns:
            List of matching context documents with relevance rank
        """
        with self.get_cursor() as cursor:
            if client_id:
                cursor.execute("""
                    SELECT cc.id, cc.title, cc.context_type, cc.client_id,
                           c.name as client_name,
                           substring(cc.content, 1, 300) as content_preview,
                           ts_rank(
                               to_tsvector('english', COALESCE(cc.title, '') || ' ' || COALESCE(cc.content, '')),
                               plainto_tsquery('english', %s)
                           ) as rank
                    FROM client_context cc
                    JOIN clients c ON cc.client_id = c.id
                    WHERE cc.client_id = %s
                      AND to_tsvector('english', COALESCE(cc.title, '') || ' ' || COALESCE(cc.content, ''))
                          @@ plainto_tsquery('english', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                """, (query, client_id, query, limit))
            else:
                cursor.execute("""
                    SELECT cc.id, cc.title, cc.context_type, cc.client_id,
                           c.name as client_name,
                           substring(cc.content, 1, 300) as content_preview,
                           ts_rank(
                               to_tsvector('english', COALESCE(cc.title, '') || ' ' || COALESCE(cc.content, '')),
                               plainto_tsquery('english', %s)
                           ) as rank
                    FROM client_context cc
                    JOIN clients c ON cc.client_id = c.id
                    WHERE to_tsvector('english', COALESCE(cc.title, '') || ' ' || COALESCE(cc.content, ''))
                          @@ plainto_tsquery('english', %s)
                    ORDER BY rank DESC
                    LIMIT %s
                """, (query, query, limit))
            return cursor.fetchall()

    def update_client_context(
        self,
        context_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        context_type: Optional[str] = None,
        source_url: Optional[str] = None
    ) -> bool:
        """
        Update a context document.

        Args:
            context_id: ID of the context to update
            title: New title (if provided)
            content: New content (if provided)
            context_type: New type (if provided)
            source_url: New URL (if provided)

        Returns:
            True if update was successful
        """
        updates = []
        params = []

        if title is not None:
            updates.append("title = %s")
            params.append(title)
        if content is not None:
            updates.append("content = %s")
            params.append(content)
        if context_type is not None:
            updates.append("context_type = %s")
            params.append(context_type)
        if source_url is not None:
            updates.append("source_url = %s")
            params.append(source_url)

        if not updates:
            return False

        updates.append("updated_at = NOW()")
        params.append(context_id)

        with self.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE client_context
                SET {', '.join(updates)}
                WHERE id = %s
            """, params)
            return cursor.rowcount > 0

    def delete_client_context(self, context_id: int) -> bool:
        """Delete a context document."""
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM client_context WHERE id = %s", (context_id,))
            return cursor.rowcount > 0


def get_database_manager() -> Optional[DatabaseManager]:
    """
    Get a DatabaseManager instance if DATABASE_URL is configured.

    Returns:
        DatabaseManager instance or None if not configured
    """
    if not os.getenv('DATABASE_URL'):
        return None

    if not PSYCOPG2_AVAILABLE:
        print("Warning: psycopg2 not installed. Database features disabled.")
        return None

    try:
        return DatabaseManager()
    except Exception as e:
        print(f"Warning: Could not connect to database: {e}")
        return None
