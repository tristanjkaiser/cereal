"""
Database module for PM Agent.

Handles PostgreSQL connection and meeting archival operations.
"""
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    from psycopg2.pool import ThreadedConnectionPool
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


class DatabaseManager:
    """Manages PostgreSQL database connections and operations."""

    def __init__(self, database_url: Optional[str] = None, pool_size: Optional[int] = None):
        """
        Initialize database manager.

        Args:
            database_url: PostgreSQL connection string.
                         If None, reads from DATABASE_URL env var.
            pool_size: If set, use a threaded connection pool of this size.
                      None (default) uses single connections (existing behavior).
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

        self._pool = None
        if pool_size:
            self._pool = ThreadedConnectionPool(1, pool_size, self.database_url)

    @contextmanager
    def get_connection(self):
        """Get a database connection as a context manager."""
        if self._pool:
            conn = self._pool.getconn()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._pool.putconn(conn)
        else:
            conn = psycopg2.connect(self.database_url)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def close(self):
        """Shut down the connection pool if active."""
        if self._pool:
            self._pool.closeall()

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
                logger.warning(f"Failed to parse meeting_date '{meeting_date}', using current time")
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

    # Client integration methods (Linear teams, Slack channels, etc.)

    def set_client_integration(
        self,
        client_id: int,
        integration_type: str,
        external_id: str,
        external_name: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> int:
        """
        Link a client to an external system (Linear team, Slack channel, etc.).

        Args:
            client_id: The client to link
            integration_type: Type of integration ('linear_team', 'slack', etc.)
            external_id: ID in the external system
            external_name: Human-readable name in external system
            metadata: Additional structured data (e.g., team_key, external_channel_id)

        Returns:
            The database ID of the created integration
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO client_integrations (client_id, integration_type, external_id, external_name, metadata)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (client_id, integration_type) DO UPDATE SET
                    external_id = EXCLUDED.external_id,
                    external_name = EXCLUDED.external_name,
                    metadata = EXCLUDED.metadata
                RETURNING id
            """, (client_id, integration_type, external_id, external_name,
                  Json(metadata) if metadata else Json({})))
            result = cursor.fetchone()
            return result['id'] if result else None

    def get_client_integration(
        self,
        client_id: int,
        integration_type: str
    ) -> Optional[Dict]:
        """
        Get integration for a client by type.

        Args:
            client_id: The client to look up
            integration_type: Type of integration ('linear_team', etc.)

        Returns:
            Integration record or None if not linked
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT ci.*, c.name as client_name
                FROM client_integrations ci
                JOIN clients c ON ci.client_id = c.id
                WHERE ci.client_id = %s AND ci.integration_type = %s
            """, (client_id, integration_type))
            return cursor.fetchone()

    def get_client_by_integration(
        self,
        integration_type: str,
        external_id: str
    ) -> Optional[Dict]:
        """
        Reverse lookup: find client by external system ID.

        Args:
            integration_type: Type of integration ('linear_team', etc.)
            external_id: ID in the external system

        Returns:
            Client record or None if not found
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT c.*, ci.external_id, ci.external_name
                FROM clients c
                JOIN client_integrations ci ON c.id = ci.client_id
                WHERE ci.integration_type = %s AND ci.external_id = %s
            """, (integration_type, external_id))
            return cursor.fetchone()

    def list_client_integrations(
        self,
        client_id: Optional[int] = None,
        integration_type: Optional[str] = None
    ) -> List[Dict]:
        """
        List all integrations, optionally filtered by client or type.

        Args:
            client_id: Optional filter by client
            integration_type: Optional filter by type

        Returns:
            List of integration records with client names
        """
        query = """
            SELECT ci.*, c.name as client_name
            FROM client_integrations ci
            JOIN clients c ON ci.client_id = c.id
            WHERE 1=1
        """
        params: List[Any] = []

        if client_id is not None:
            query += " AND ci.client_id = %s"
            params.append(client_id)

        if integration_type is not None:
            query += " AND ci.integration_type = %s"
            params.append(integration_type)

        query += " ORDER BY c.name, ci.integration_type"

        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def delete_client_integration(
        self,
        client_id: int,
        integration_type: str
    ) -> bool:
        """
        Remove an integration link.

        Args:
            client_id: The client to unlink
            integration_type: Type of integration to remove

        Returns:
            True if the integration was found and deleted
        """
        with self.get_cursor() as cursor:
            cursor.execute(
                "DELETE FROM client_integrations WHERE client_id = %s AND integration_type = %s",
                (client_id, integration_type)
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
            return result['id'] if result else None

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

    def get_client_dashboard_summary(self) -> List[Dict]:
        """Get all clients with meeting counts and last meeting date."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT c.id, c.name, c.slug, c.notes, c.created_at,
                       COUNT(m.id) as meeting_count,
                       MAX(m.meeting_date) as last_meeting_date
                FROM clients c
                LEFT JOIN meetings m ON c.id = m.client_id
                GROUP BY c.id
                ORDER BY c.name
            """)
            return cursor.fetchall()

    def get_todo_counts_by_client(self) -> List[Dict]:
        """Get open and overdue todo counts per client."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT t.client_id,
                       COUNT(*) FILTER (WHERE t.status NOT IN ('done','archived')) as open_count,
                       COUNT(*) FILTER (WHERE t.status NOT IN ('done','archived') AND t.due_date < CURRENT_DATE) as overdue_count
                FROM client_todos t
                GROUP BY t.client_id
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
            WHERE m.meeting_date >= NOW() - (%s * INTERVAL '1 day')
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

    # To-do methods

    def create_todo(
        self,
        client_id: int,
        title: str,
        description: Optional[str] = None,
        priority: int = 0,
        due_date: Optional[str] = None,
        category: Optional[str] = None,
        meeting_id: Optional[int] = None,
        source_context: Optional[str] = None
    ) -> Dict:
        """Create a single to-do item. Returns the created row."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO client_todos
                    (client_id, title, description, priority, due_date, category, meeting_id, source_context)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (client_id, title, description, priority, due_date, category, meeting_id, source_context))
            return cursor.fetchone()

    def batch_create_todos(
        self,
        client_id: int,
        items: List[Dict],
        meeting_id: Optional[int] = None,
        source_context: Optional[str] = None
    ) -> List[Dict]:
        """
        Create multiple to-do items in one transaction.

        Args:
            client_id: Client to create items for
            items: List of dicts with keys: title (required), description, priority, due_date, category
            meeting_id: Optional meeting to link all items to
            source_context: Optional provenance for all items

        Returns:
            List of created rows
        """
        created = []
        with self.get_cursor() as cursor:
            for item in items:
                cursor.execute("""
                    INSERT INTO client_todos
                        (client_id, title, description, priority, due_date, category, meeting_id, source_context)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (
                    client_id,
                    item['title'],
                    item.get('description'),
                    item.get('priority', 0),
                    item.get('due_date'),
                    item.get('category'),
                    item.get('meeting_id', meeting_id),
                    item.get('source_context', source_context)
                ))
                created.append(cursor.fetchone())
        return created

    def get_todo(self, todo_id: int) -> Optional[Dict]:
        """Get a single to-do by ID with client name."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT t.*, c.name as client_name
                FROM client_todos t
                JOIN clients c ON t.client_id = c.id
                WHERE t.id = %s
            """, (todo_id,))
            return cursor.fetchone()

    def list_todos(
        self,
        client_id: Optional[int] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        category: Optional[str] = None,
        include_done: bool = False,
        overdue_only: bool = False,
        limit: int = 50
    ) -> List[Dict]:
        """
        List to-dos with flexible filtering.

        Args:
            client_id: Filter by client
            status: Filter by status (pending, in_progress, done, archived)
            priority: Filter by priority level
            category: Filter by category
            include_done: If True, include done/archived items (default False)
            overdue_only: If True, only items past due_date that aren't done
            limit: Max results

        Returns:
            List of to-do items with client names
        """
        query = """
            SELECT t.*, c.name as client_name,
                   m.title as meeting_title, m.meeting_date as meeting_date_ref
            FROM client_todos t
            JOIN clients c ON t.client_id = c.id
            LEFT JOIN meetings m ON t.meeting_id = m.id
            WHERE 1=1
        """
        params: List[Any] = []

        if client_id is not None:
            query += " AND t.client_id = %s"
            params.append(client_id)

        if status is not None:
            query += " AND t.status = %s"
            params.append(status)
        elif not include_done:
            query += " AND t.status NOT IN ('done', 'archived')"

        if priority is not None:
            query += " AND t.priority = %s"
            params.append(priority)

        if category is not None:
            query += " AND t.category = %s"
            params.append(category)

        if overdue_only:
            query += " AND t.due_date < CURRENT_DATE AND t.status NOT IN ('done', 'archived')"

        query += " ORDER BY t.sort_order ASC, t.priority ASC NULLS LAST, t.due_date ASC NULLS LAST, t.created_at DESC"
        query += " LIMIT %s"
        params.append(limit)

        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def update_todo_sort_order(self, ordered_ids: list) -> int:
        """Set sort_order based on position in the list. Returns count updated."""
        updated = 0
        with self.get_cursor() as cursor:
            for i, todo_id in enumerate(ordered_ids):
                cursor.execute(
                    "UPDATE client_todos SET sort_order = %s WHERE id = %s",
                    (i, todo_id),
                )
                updated += cursor.rowcount
        return updated

    def get_todo(self, todo_id: int) -> Optional[Dict]:
        """Get a single todo by ID with client name and meeting info."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT t.*, c.name as client_name,
                       m.title as meeting_title, m.meeting_date as meeting_date_ref
                FROM client_todos t
                JOIN clients c ON t.client_id = c.id
                LEFT JOIN meetings m ON t.meeting_id = m.id
                WHERE t.id = %s
            """, (todo_id,))
            return cursor.fetchone()

    def update_todo(
        self,
        todo_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        due_date: Optional[str] = None,
        category: Optional[str] = None,
        meeting_id: Optional[int] = None,
        source_context: Optional[str] = None
    ) -> bool:
        """
        Update a to-do item. Only provided fields are changed.
        Auto-sets completed_at when status transitions to 'done',
        clears it if reopened.

        Returns:
            True if update was successful
        """
        updates = []
        params = []

        if title is not None:
            updates.append("title = %s")
            params.append(title)
        if description is not None:
            updates.append("description = %s")
            params.append(description)
        if status is not None:
            updates.append("status = %s")
            params.append(status)
            if status == 'done':
                updates.append("completed_at = NOW()")
            elif status in ('pending', 'in_progress'):
                updates.append("completed_at = NULL")
        if priority is not None:
            updates.append("priority = %s")
            params.append(priority)
        if due_date is not None:
            updates.append("due_date = %s")
            params.append(due_date)
        if category is not None:
            updates.append("category = %s")
            params.append(category)
        if meeting_id is not None:
            updates.append("meeting_id = %s")
            params.append(meeting_id)
        if source_context is not None:
            updates.append("source_context = %s")
            params.append(source_context)

        if not updates:
            return False

        updates.append("updated_at = NOW()")
        params.append(todo_id)

        with self.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE client_todos
                SET {', '.join(updates)}
                WHERE id = %s
            """, params)
            return cursor.rowcount > 0

    def complete_todo(self, todo_id: int) -> bool:
        """Mark a single to-do as done. Returns True if successful."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                UPDATE client_todos
                SET status = 'done', completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """, (todo_id,))
            return cursor.rowcount > 0

    def bulk_complete_todos(self, todo_ids: List[int]) -> int:
        """Mark multiple to-dos as done. Returns count of updated rows."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                UPDATE client_todos
                SET status = 'done', completed_at = NOW(), updated_at = NOW()
                WHERE id = ANY(%s)
            """, (todo_ids,))
            return cursor.rowcount

    def delete_todo(self, todo_id: int) -> bool:
        """Hard delete a to-do. Returns True if deleted."""
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM client_todos WHERE id = %s", (todo_id,))
            return cursor.rowcount > 0

    def search_todos(self, query: str, client_id: Optional[int] = None, limit: int = 20) -> List[Dict]:
        """
        Search to-dos by title/description using ILIKE.

        Args:
            query: Search term
            client_id: Optional filter by client
            limit: Max results

        Returns:
            Matching to-do items with client names
        """
        search_pattern = f"%{query}%"
        sql = """
            SELECT t.*, c.name as client_name
            FROM client_todos t
            JOIN clients c ON t.client_id = c.id
            WHERE (t.title ILIKE %s OR t.description ILIKE %s)
        """
        params: List[Any] = [search_pattern, search_pattern]

        if client_id is not None:
            sql += " AND t.client_id = %s"
            params.append(client_id)

        sql += " ORDER BY t.created_at DESC LIMIT %s"
        params.append(limit)

        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    # Timeline methods

    def create_timeline(
        self,
        client_id: int,
        project_name: str,
        sow_signed_date: Optional[str] = None,
        estimated_design_weeks_low: Optional[float] = None,
        estimated_design_weeks_high: Optional[float] = None,
        estimated_dev_weeks_low: Optional[float] = None,
        estimated_dev_weeks_high: Optional[float] = None,
        estimated_overall_weeks_low: Optional[float] = None,
        estimated_overall_weeks_high: Optional[float] = None,
        notes: Optional[str] = None
    ) -> int:
        """Create a new project timeline. Returns timeline ID."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO timelines (
                    client_id, project_name, sow_signed_date,
                    estimated_design_weeks_low, estimated_design_weeks_high,
                    estimated_dev_weeks_low, estimated_dev_weeks_high,
                    estimated_overall_weeks_low, estimated_overall_weeks_high,
                    notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                client_id, project_name, sow_signed_date,
                estimated_design_weeks_low, estimated_design_weeks_high,
                estimated_dev_weeks_low, estimated_dev_weeks_high,
                estimated_overall_weeks_low, estimated_overall_weeks_high,
                notes
            ))
            result = cursor.fetchone()
            return result['id']

    def get_timeline(self, timeline_id: int) -> Optional[Dict]:
        """Get a timeline by ID."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT t.*, c.name as client_name
                FROM timelines t
                JOIN clients c ON t.client_id = c.id
                WHERE t.id = %s
            """, (timeline_id,))
            return cursor.fetchone()

    def get_timelines_for_client(self, client_id: int, status: Optional[str] = None) -> List[Dict]:
        """Get all timelines for a client, optionally filtered by status."""
        query = """
            SELECT t.*, c.name as client_name
            FROM timelines t
            JOIN clients c ON t.client_id = c.id
            WHERE t.client_id = %s
        """
        params: List[Any] = [client_id]
        if status:
            query += " AND t.status = %s"
            params.append(status)
        query += " ORDER BY t.created_at DESC"
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def list_timelines(self, status: Optional[str] = None) -> List[Dict]:
        """List all timelines, optionally filtered by status."""
        query = """
            SELECT t.*, c.name as client_name
            FROM timelines t
            JOIN clients c ON t.client_id = c.id
        """
        params: List[Any] = []
        if status:
            query += " WHERE t.status = %s"
            params.append(status)
        query += " ORDER BY c.name, t.created_at DESC"
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def update_timeline(self, timeline_id: int, **kwargs) -> bool:
        """Update timeline fields. Pass any column name as keyword arg."""
        allowed = {
            'project_name', 'sow_signed_date', 'status', 'notes',
            'estimated_design_weeks_low', 'estimated_design_weeks_high',
            'estimated_dev_weeks_low', 'estimated_dev_weeks_high',
            'estimated_overall_weeks_low', 'estimated_overall_weeks_high'
        }
        updates = []
        params = []
        for key, value in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = %s")
                params.append(value)
        if not updates:
            return False
        updates.append("updated_at = NOW()")
        params.append(timeline_id)
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE timelines SET {', '.join(updates)} WHERE id = %s
            """, params)
            return cursor.rowcount > 0

    # Phase methods

    def create_phase(
        self,
        timeline_id: int,
        name: str,
        phase_type: str,
        sort_order: int = 0,
        parent_phase_id: Optional[int] = None,
        planned_start_date: Optional[str] = None,
        planned_end_date: Optional[str] = None,
        planned_duration_weeks_low: Optional[float] = None,
        planned_duration_weeks_high: Optional[float] = None,
        notes: Optional[str] = None
    ) -> int:
        """Create a timeline phase. Returns phase ID."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO timeline_phases (
                    timeline_id, parent_phase_id, name, phase_type, sort_order,
                    planned_start_date, planned_end_date,
                    planned_duration_weeks_low, planned_duration_weeks_high, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                timeline_id, parent_phase_id, name, phase_type, sort_order,
                planned_start_date, planned_end_date,
                planned_duration_weeks_low, planned_duration_weeks_high, notes
            ))
            result = cursor.fetchone()
            return result['id']

    def get_phases_for_timeline(self, timeline_id: int) -> List[Dict]:
        """Get all phases for a timeline, ordered by sort_order."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM timeline_phases
                WHERE timeline_id = %s
                ORDER BY sort_order, id
            """, (timeline_id,))
            return cursor.fetchall()

    def get_phase(self, phase_id: int) -> Optional[Dict]:
        """Get a phase by ID."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM timeline_phases WHERE id = %s", (phase_id,))
            return cursor.fetchone()

    def update_phase(self, phase_id: int, **kwargs) -> bool:
        """Update phase fields."""
        allowed = {
            'name', 'status', 'planned_start_date', 'planned_end_date',
            'actual_start_date', 'actual_end_date', 'linear_project_id', 'notes',
            'planned_duration_weeks_low', 'planned_duration_weeks_high'
        }
        updates = []
        params = []
        for key, value in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = %s")
                params.append(value)
        if not updates:
            return False
        updates.append("updated_at = NOW()")
        params.append(phase_id)
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE timeline_phases SET {', '.join(updates)} WHERE id = %s
            """, params)
            return cursor.rowcount > 0

    # Milestone methods

    def create_milestone(
        self,
        phase_id: int,
        name: str,
        description: Optional[str] = None,
        target_date: Optional[str] = None,
        linear_issue_id: Optional[str] = None,
        linear_project_id: Optional[str] = None
    ) -> int:
        """Create a milestone. Returns milestone ID."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO timeline_milestones (
                    phase_id, name, description, target_date,
                    linear_issue_id, linear_project_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (phase_id, name, description, target_date,
                  linear_issue_id, linear_project_id))
            result = cursor.fetchone()
            return result['id']

    def get_milestones_for_phase(self, phase_id: int) -> List[Dict]:
        """Get all milestones for a phase."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM timeline_milestones
                WHERE phase_id = %s
                ORDER BY target_date NULLS LAST, id
            """, (phase_id,))
            return cursor.fetchall()

    def update_milestone(self, milestone_id: int, **kwargs) -> bool:
        """Update milestone fields."""
        allowed = {
            'name', 'description', 'status', 'target_date', 'actual_date',
            'linear_issue_id', 'linear_project_id', 'meeting_id'
        }
        updates = []
        params = []
        for key, value in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = %s")
                params.append(value)
        if not updates:
            return False
        updates.append("updated_at = NOW()")
        params.append(milestone_id)
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE timeline_milestones SET {', '.join(updates)} WHERE id = %s
            """, params)
            return cursor.rowcount > 0

    def get_milestone(self, milestone_id: int) -> Optional[Dict]:
        """Get a milestone by ID."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM timeline_milestones WHERE id = %s", (milestone_id,))
            return cursor.fetchone()

    # Workshop methods

    def create_workshop(
        self,
        phase_id: int,
        workshop_number: int,
        scheduled_date: Optional[str] = None
    ) -> int:
        """Create a workshop record. Returns workshop ID."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO timeline_workshops (phase_id, workshop_number, scheduled_date)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (phase_id, workshop_number, scheduled_date))
            result = cursor.fetchone()
            return result['id']

    def get_workshops_for_phase(self, phase_id: int) -> List[Dict]:
        """Get all workshops for a phase, ordered by number."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM timeline_workshops
                WHERE phase_id = %s
                ORDER BY workshop_number
            """, (phase_id,))
            return cursor.fetchall()

    def update_workshop(self, workshop_id: int, **kwargs) -> bool:
        """Update workshop fields."""
        allowed = {
            'scheduled_date', 'actual_date', 'meeting_id', 'status', 'notes'
        }
        updates = []
        params = []
        for key, value in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = %s")
                params.append(value)
        if not updates:
            return False
        updates.append("updated_at = NOW()")
        params.append(workshop_id)
        with self.get_cursor() as cursor:
            cursor.execute(f"""
                UPDATE timeline_workshops SET {', '.join(updates)} WHERE id = %s
            """, params)
            return cursor.rowcount > 0

    # Snapshot methods

    def save_snapshot(
        self,
        timeline_id: int,
        health: str,
        current_phase: str,
        summary: str,
        linear_stats: Optional[Dict] = None,
        details: Optional[Dict] = None,
        triggered_by: str = 'manual'
    ) -> int:
        """Save a project health snapshot. Returns snapshot ID."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO timeline_snapshots (
                    timeline_id, health, current_phase, summary,
                    linear_stats, details, triggered_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                timeline_id, health, current_phase, summary,
                Json(linear_stats) if linear_stats else None,
                Json(details) if details else None,
                triggered_by
            ))
            result = cursor.fetchone()
            return result['id']

    def get_snapshots(
        self,
        timeline_id: int,
        limit: int = 10,
        since: Optional[str] = None
    ) -> List[Dict]:
        """Get health snapshots for a timeline."""
        query = """
            SELECT * FROM timeline_snapshots
            WHERE timeline_id = %s
        """
        params: List[Any] = [timeline_id]
        if since:
            query += " AND snapshot_date >= %s"
            params.append(since)
        query += " ORDER BY snapshot_date DESC LIMIT %s"
        params.append(limit)
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    # Linear mapping methods

    def create_linear_mapping(
        self,
        timeline_id: int,
        phase_id: Optional[int] = None,
        milestone_id: Optional[int] = None,
        linear_project_id: Optional[str] = None,
        linear_project_name: Optional[str] = None,
        linear_milestone_id: Optional[str] = None
    ) -> int:
        """Create a Linear-to-timeline mapping. Returns mapping ID."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO timeline_linear_mappings (
                    timeline_id, phase_id, milestone_id,
                    linear_project_id, linear_project_name, linear_milestone_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                timeline_id, phase_id, milestone_id,
                linear_project_id, linear_project_name, linear_milestone_id
            ))
            result = cursor.fetchone()
            return result['id']

    def get_linear_mappings_for_timeline(self, timeline_id: int) -> List[Dict]:
        """Get all Linear mappings for a timeline."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT tlm.*,
                       tp.name as phase_name,
                       tm.name as milestone_name
                FROM timeline_linear_mappings tlm
                LEFT JOIN timeline_phases tp ON tlm.phase_id = tp.id
                LEFT JOIN timeline_milestones tm ON tlm.milestone_id = tm.id
                WHERE tlm.timeline_id = %s
                ORDER BY tlm.id
            """, (timeline_id,))
            return cursor.fetchall()

    def get_linear_mappings_for_phase(self, phase_id: int) -> List[Dict]:
        """Get Linear mappings for a specific phase."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM timeline_linear_mappings
                WHERE phase_id = %s
            """, (phase_id,))
            return cursor.fetchall()

    # Dismissed alerts methods

    def dismiss_alert(self, alert_type: str, reference_id: int, recheck_after=None) -> int:
        """Dismiss an alert so it won't reappear (until recheck_after if set)."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO dismissed_alerts (alert_type, reference_id, recheck_after)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
            """, (alert_type, reference_id, recheck_after))
            result = cursor.fetchone()
            return result["id"] if result else 0

    def get_dismissed_alert_ids(self, alert_type: str) -> set:
        """Get set of reference_ids currently dismissed for a given alert type."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT reference_id FROM dismissed_alerts
                WHERE alert_type = %s
                  AND (recheck_after IS NULL OR recheck_after > NOW())
            """, (alert_type,))
            return {row["reference_id"] for row in cursor.fetchall()}

    def undismiss_alert(self, alert_type: str, reference_id: int) -> bool:
        """Remove a dismissal."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                DELETE FROM dismissed_alerts
                WHERE alert_type = %s AND reference_id = %s
            """, (alert_type, reference_id))
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
