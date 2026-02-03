# Cereal - Project Guide

Cereal archives Granola meeting transcripts to PostgreSQL for querying via Claude Desktop MCP.

## Quick Reference

```bash
# Run MCP server locally (for development)
cd mcp_server && uv run mcp dev server.py

# Database access
psql postgresql://localhost:5432/cereal

# View MCP server logs
tail -f logs/mcp_server.log
```

## Architecture

```
Granola (local app) → GranolaClient → PostgreSQL ← MCP Server → Claude Desktop
```

- **Granola** runs locally at `http://localhost:14823` and stores meeting transcripts
- **GranolaClient** (`src/granola_client.py`) fetches documents via Granola's local API
- **DatabaseManager** (`src/database.py`) handles PostgreSQL operations
- **MCP Server** (`mcp_server/server.py`) exposes tools to Claude Desktop via FastMCP

## Key Files

| File | Purpose |
|------|---------|
| `mcp_server/server.py` | FastMCP server with all tool definitions |
| `mcp_server/run_server.sh` | Launcher script for Claude Desktop |
| `mcp_server/pyproject.toml` | MCP server dependencies (uses uv) |
| `src/database.py` | DatabaseManager class for PostgreSQL |
| `src/granola_client.py` | GranolaClient for Granola API |
| `scripts/setup_database.sql` | Database schema |

## Database Schema

Five tables: `clients`, `meeting_series`, `meetings`, `client_context`, `client_aliases`

The `meetings` table stores:
- `granola_document_id` - unique ID from Granola
- `title`, `meeting_date`
- `transcript` - full transcript with speaker labels
- `enhanced_notes` - Granola's AI-generated notes
- `summary_overview`, `summary_json` - AI summaries
- `client_id` - foreign key to clients

The `client_context` table stores:
- `client_id` - foreign key to clients
- `title` - document title (e.g., "Q1 Estimate", "PRD v2")
- `context_type` - prd, estimate, outcome, contract, note
- `content` - full text content
- `source_url` - optional link to original doc

The `client_aliases` table stores:
- `alias` - alternate name to recognize (e.g., "NB44 - Intuit")
- `canonical_client_id` - the client this alias maps to

Full-text search indexes exist on transcript, notes, summary, and context fields.

## Auto-Client Detection

When `archive_new_meetings` runs, it automatically detects clients for each meeting:

**Detection priority (in order):**
1. **Client aliases** (highest priority) - user-defined mappings via `merge_clients` or `add_client_alias`
2. Known client name appears in title (case-insensitive)
3. Title pattern extraction:
   - `{Client} x Goji` → Client
   - `{Client}: ...` → Client
   - `Record {Client} ...` → Client
4. External attendee company (if exactly one external company in attendees)

**Key functions:**
- `detect_client_from_meeting()` in [server.py](mcp_server/server.py) - detection logic
- `get_document_attendees()` in [granola_client.py](src/granola_client.py) - extracts attendee data
- `get_client_names()` in [database.py](src/database.py) - fetches known clients for matching
- `get_client_aliases()` in [database.py](src/database.py) - fetches alias mappings

**Configuration:**
- `INTERNAL_DOMAIN` env var (default: `gojilabs.com`) - emails from this domain are internal

New clients are auto-created via `get_or_create_client()`. Meetings without detected clients have `client_id = NULL`.

## MCP Tools

The server exposes these tools to Claude:

### Meeting Tools

| Tool | Description |
|------|-------------|
| `archive_new_meetings` | Sync new meetings from Granola (auto-detects clients) |
| `list_clients` | List clients with meeting counts |
| `list_recent_meetings` | Get meetings from last N days |
| `get_client_meetings` | Get meetings for a specific client |
| `search_meetings` | Full-text search across transcripts |
| `get_meeting_details` | Get notes for a meeting (by ID) |
| `get_meeting_transcript` | Get full transcript (by ID) |
| `find_meeting_by_title` | Search meetings by title |
| `get_meeting_stats` | Archive statistics |

### Client Context Tools

| Tool | Description |
|------|-------------|
| `add_client_context` | Save PRD, estimate, outcome, etc. for a client |
| `list_client_context` | List all context docs for a client |
| `get_client_context` | Get full content by context ID |
| `search_client_context` | Full-text search across context docs |
| `update_client_context` | Update existing context doc |
| `delete_client_context` | Delete a context doc |

### Client Management Tools

| Tool | Description |
|------|-------------|
| `merge_clients` | Merge duplicate clients, reassign meetings, create alias |
| `rename_client` | Rename client and create alias for old name |
| `add_client_alias` | Add alias without merging |
| `list_client_aliases` | Show all configured aliases |
| `delete_client_alias` | Remove an alias |

**Example:** Merge "NB44 - Intuit" into "NB44":
```
merge_clients("NB44 - Intuit", "NB44")
```
This reassigns all meetings/context and creates an alias so future archival recognizes "NB44 - Intuit" as "NB44".

## Development

### Adding a new MCP tool

1. Add the function in `mcp_server/server.py` with the `@mcp.tool()` decorator
2. Include a docstring - this becomes the tool description for Claude
3. Use `get_db()` to get a DatabaseManager instance
4. Return a formatted string (markdown works)

### Adding a database method

1. Add the method to `DatabaseManager` in `src/database.py`
2. Use `with self.get_cursor() as cursor:` for queries
3. Return `Dict` for single rows, `List[Dict]` for multiple

### Testing the MCP server

```bash
cd mcp_server
uv run mcp dev server.py
```

This starts an interactive session where you can test tools directly.

## Configuration

### Environment variables

- `DATABASE_URL` - PostgreSQL connection string (default: `postgresql://localhost:5432/cereal`)
- `INTERNAL_DOMAIN` - Your company's email domain for client detection (default: `gojilabs.com`)

### Claude Desktop config

Located at `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cereal": {
      "command": "/path/to/cereal/mcp_server/run_server.sh",
      "env": {
        "DATABASE_URL": "postgresql://localhost:5432/cereal"
      }
    }
  }
}
```
