# Cereal - Project Guide

Cereal archives Granola meeting transcripts to PostgreSQL for querying via Claude Desktop MCP.

## Quick Reference

```bash
# Run MCP server locally (for development)
cd mcp_server && uv run mcp dev server.py

# Database access
psql postgresql://localhost:5432/cereal

# Web dashboard (http://localhost:5555)
python web/run.py --open

# View MCP server logs
tail -f logs/mcp_server.log
```

## Architecture

```
Granola (local app) → GranolaClient → PostgreSQL ← MCP Server → Claude Desktop
                                             ↑
                                        Flask Web App
```

- **Granola** runs locally at `http://localhost:14823` and stores meeting transcripts
- **GranolaClient** (`src/granola_client.py`) fetches documents via Granola's local API
- **DatabaseManager** (`src/database.py`) handles PostgreSQL operations (supports opt-in connection pooling)
- **Service Layer** (`src/services/`) shared business logic used by MCP, Flask, and auto_archive
- **MCP Server** (`mcp_server/server.py`) exposes tools to Claude Desktop via FastMCP
- **Web App** (`web/`) Flask app serving the dashboard at `http://localhost:5555`

## Key Files

| File | Purpose |
|------|---------|
| `mcp_server/server.py` | FastMCP server with all tool definitions |
| `mcp_server/run_server.sh` | Launcher script for Claude Desktop |
| `mcp_server/pyproject.toml` | MCP server dependencies (uses uv) |
| `src/database.py` | DatabaseManager class for PostgreSQL |
| `src/granola_client.py` | GranolaClient for Granola API |
| `scripts/setup_database.sql` | Database schema (core tables) |
| `scripts/timeline_migration.sql` | Timeline tables migration |
| `scripts/auto_archive.py` | Automated meeting archival script |
| `scripts/auto_archive_ctl.sh` | launchd enable/disable/status helper |
| `scripts/todos_migration.sql` | To-do table migration |
| `scripts/todo_extraction_migration.sql` | AI extraction columns migration |
| `scripts/activity_log_migration.sql` | Activity log table migration |
| `src/services/client_detection.py` | Client detection logic (shared) |
| `src/services/todo_service.py` | Todo grouping/matching helpers |
| `src/services/todo_extraction_service.py` | AI todo extraction from transcripts |
| `src/services/client_service.py` | Client lookup helpers |
| `src/services/activity_log_service.py` | Pipeline activity logging |
| `web/__init__.py` | Flask app factory (`create_app()`) |
| `web/config.py` | Flask configuration |
| `web/extensions.py` | DB lifecycle (pooled DatabaseManager) |
| `web/run.py` | Web app entry point (replaces dashboard/serve.py) |
| `web/routes/todos.py` | `/todos` blueprint |
| `web/routes/activity.py` | `/activity` blueprint (pipeline logs) |
| `web/templates/` | Jinja2 templates (base.html, todos/) |
| `web/static/css/style.css` | CSS with design tokens |
| `dashboard/serve.py` | Legacy dashboard (deprecated, kept as fallback) |
| `dashboard/dashboard_ctl.sh` | launchd enable/disable/status for dashboard |

## Database Schema

Core tables: `clients`, `meeting_series`, `meetings`, `client_context`, `client_aliases`, `client_integrations`, `client_todos`, `activity_log`

Timeline tables: `timelines`, `timeline_phases`, `timeline_milestones`, `timeline_workshops`, `timeline_snapshots`, `timeline_linear_mappings`

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
- `alias` - alternate name to recognize (e.g., "ClientB - BigCo")
- `canonical_client_id` - the client this alias maps to

The `client_integrations` table stores:
- `client_id` - foreign key to clients
- `integration_type` - type of integration ('linear_team', 'slack', etc.)
- `external_id` - ID in the external system (e.g., Linear team ID, Slack internal channel ID)
- `external_name` - human-readable name in external system
- `metadata` - JSONB for additional structured data (e.g., `{"team_key": "ACME"}` for Linear, `{"external_channel_id": "..."}` for Slack)

The `client_todos` table stores:
- `client_id` - foreign key to clients
- `title` - short actionable title
- `description` - optional longer details
- `status` - pending, in_progress, done, archived
- `priority` - 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low (matches Linear)
- `due_date` - optional due date
- `completed_at` - auto-managed timestamp (set on done, cleared on reopen)
- `category` - agent-assigned freeform tag ("decision", "deliverable", "follow-up", "billing", "planning", "blocker", "review")
- `meeting_id` - optional link to source meeting
- `source_context` - free-text provenance ("from workshop 2", "per Slack thread")
- `assigned_to` - who owns this item: `us`, `them`, or `unclear` (default: `us`)

The `meetings` table also has:
- `todos_extracted_at` - timestamp set after AI todo extraction runs (prevents re-extraction)

Full-text search indexes exist on transcript, notes, summary, and context fields.

## Auto-Client Detection

When `archive_new_meetings` runs, it automatically detects clients for each meeting:

**Detection priority (in order):**
1. **Client aliases** (highest priority) - user-defined mappings via `merge_clients` or `add_client_alias`
2. Known client name appears in title (case-insensitive)
3. Title pattern extraction:
   - `{Client} x {YourCompany}` → Client
   - `{Client}: ...` → Client
   - `Record {Client} ...` → Client
4. External attendee company (if exactly one external company in attendees)

**Key functions:**
- `detect_client_from_meeting()` in [server.py](mcp_server/server.py) - detection logic
- `get_document_attendees()` in [granola_client.py](src/granola_client.py) - extracts attendee data
- `get_client_names()` in [database.py](src/database.py) - fetches known clients for matching
- `get_client_aliases()` in [database.py](src/database.py) - fetches alias mappings

**Configuration:**
- `INTERNAL_DOMAIN` env var - your company's email domain; emails from this domain are treated as internal

New clients are auto-created via `get_or_create_client()`. Meetings without detected clients have `client_id = NULL`.

## Internal Virtual Client

A reserved client called "Internal" exists for tracking non-client business items (taxes, admin, management tasks). It uses the existing client/todo infrastructure with no schema changes.

**Constant:** `INTERNAL_CLIENT_NAME = "Internal"` in `src/services/client_service.py` — single source of truth, imported everywhere.

**Auto-created:** `ClientService.ensure_internal_client()` runs at MCP server init (in `get_db()`).

**Where it's filtered out:**
- `list_clients` MCP tool — shown at the bottom with *(internal/non-client items)* label
- `get_meeting_stats` MCP tool — excluded from client count and top-clients
- `archive_new_meetings` + `auto_archive.py` — excluded from `known_clients` to prevent false title matches
- Dashboard home page (`DashboardService.get_client_overview()`) — not shown
- Sidebar nav (`web/__init__.py`) — not shown

**Where it appears normally:**
- `add_todo(client_name="Internal", ...)` — works like any client
- `list_todos` / `list_overdue_todos` — Internal group sorted last
- Todo dashboard (`/todos`) — Internal pill separated by `|`, group header shows "(non-client items)"
- Client detail page (`/clients/Internal`) — works normally

**Usage:** `add_todo(client_name="Internal", title="File Q1 taxes")`

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
| `assign_meeting_to_client` | Manually assign a meeting to a client |

### Client Context Tools

| Tool | Description |
|------|-------------|
| `add_client_context` | Save PRD, estimate, outcome, etc. for a client |
| `list_client_context` | List all context docs for a client |
| `get_client_context` | Get full content by context ID |
| `search_client_context` | Full-text search across context docs |
| `update_client_context` | Update existing context doc |
| `delete_client_context` | Delete a context doc |

### To-Do Tools

| Tool | Description |
|------|-------------|
| `add_todo` | Create a to-do for a client (agent infers priority/category) |
| `add_todos_batch` | Create multiple to-dos at once (e.g., action items from a meeting) |
| `list_todos` | List items with filtering; no args = open items across all clients |
| `update_todo` | Update any fields on a to-do |
| `complete_todo` | Mark a to-do as done |
| `delete_todo` | Permanently remove a to-do |
| `list_overdue_todos` | Show overdue items across all clients |
| `view_todos` | Generate HTML dashboard of to-dos and open in browser |
| `batch_update_todos` | Complete, update, and add to-dos in one call (title-based matching, no ID lookup) |

### Client Management Tools

| Tool | Description |
|------|-------------|
| `merge_clients` | Merge duplicate clients, reassign meetings, create alias |
| `rename_client` | Rename client and create alias for old name |
| `add_client_alias` | Add alias without merging |
| `list_client_aliases` | Show all configured aliases |
| `delete_client_alias` | Remove an alias |

**Example:** Merge "ClientB - BigCo" into "ClientB":
```
merge_clients("ClientB - BigCo", "ClientB")
```
This reassigns all meetings/context and creates an alias so future archival recognizes "ClientB - BigCo" as "ClientB".

### Integration Tools

| Tool | Description |
|------|-------------|
| `link_client_to_linear_team` | Link a client to a Linear team ID, name, and key |
| `get_client_linear_team` | Get the Linear team linked to a client |
| `link_client_to_slack` | Link a client to internal (and optional external) Slack channels |
| `get_client_slack` | Get the Slack channels linked to a client |
| `get_client_config` | Get all integration data for a client in one call |
| `list_integration_status` | Show all clients with their integration mappings |
| `unlink_client_integration` | Remove a client's integration link |

**Example:** Link a client to Linear team:
```
link_client_to_linear_team("ClientA", "team_abc123", "ClientA Engineering", "CLNT")
```
This stores the team ID, display name, and key prefix (used in issue IDs like `CLNT-123`).

**Example:** Link a client to Slack channels:
```
link_client_to_slack("ClientA", "C0A20JC8A3V", "C08029VUGS0")
```
First arg is the internal channel ID, second (optional) is the external/client-facing channel.

**Key functions:**
- `set_client_integration()` in [database.py](src/database.py) - creates/updates integration (supports `metadata` JSONB)
- `get_client_by_integration()` in [database.py](src/database.py) - reverse lookup by external ID
- `list_client_integrations()` in [database.py](src/database.py) - list all integrations

**Workflow for mapping clients to Linear teams:**
1. Claude calls Linear MCP `list_teams` → gets all Linear teams
2. Claude calls Cereal `list_integration_status` → gets clients + existing mappings
3. Claude compares names and suggests matches
4. User confirms, Claude calls `link_client_to_linear_team()`

### Timeline Tools

| Tool | Description |
|------|-------------|
| `create_timeline` | Create a project timeline for a client (auto-creates standard phases) |
| `get_timeline` | Get full timeline with phases, milestones, workshops, and status |
| `list_timelines` | List all timelines, optionally filtered by client or status |
| `update_phase` | Update phase status, dates, or link to Linear project |
| `add_milestone` | Add a milestone to a phase |
| `update_milestone` | Update milestone status and dates |
| `record_workshop` | Record Strategy Sprint workshop completion |
| `map_linear_to_phase` | Connect a Linear project to a timeline phase |
| `map_linear_to_milestone` | Connect a Linear issue/project to a milestone |
| `assess_project_health` | Cross-reference timeline + meetings + Linear for health assessment |
| `get_project_snapshots` | Historical health assessments for a project |

**Standard Lifecycle (auto-created with `create_timeline`):**
```
Strategy Sprint (4 workshops)
Design Phase
  └─ User Flow IA + Low-fis
  └─ UI Exploration
  └─ Design System
  └─ High-fis
  └─ Revisions / Hand-off
Dev Phase
```

**"Where are we on [project]?" workflow:**
1. `assess_project_health("ClientName")` — returns timeline status + Linear project IDs
2. Claude queries Linear MCP for ticket breakdowns on mapped projects
3. Claude queries recent meetings via `get_client_meetings`
4. Claude synthesizes a health assessment
5. Snapshot is stored for historical tracking via `get_project_snapshots`

**Timeline Schema:**
- `timelines` — one per client project, stores SOW estimates and status
- `timeline_phases` — phases and subphases (self-referential via `parent_phase_id`)
- `timeline_milestones` — key checkpoints within phases
- `timeline_workshops` — Strategy Sprint workshop tracking (4 per sprint)
- `timeline_snapshots` — point-in-time health assessments (on_track/at_risk/off_track)
- `timeline_linear_mappings` — connects Linear projects to phases/milestones

## Auto-Archive

`scripts/auto_archive.py` runs on a schedule via macOS launchd to automatically archive meetings without user intervention.

**How it works:**
- Fetches recent documents from Granola
- Filters to a **time window**: only meetings where `created_at` is between 2 hours and 3 hours ago
- Upserts all meetings in the window via `db.archive_meeting()` (ON CONFLICT DO UPDATE)
- Runs client detection using the same logic as `archive_new_meetings`

**Time window defaults:**
- `AUTO_ARCHIVE_SETTLE_HOURS=2` — skip meetings likely still in progress
- `AUTO_ARCHIVE_FRESHNESS_HOURS=3` — stop re-archiving finalized meetings

**Key files:**
- `scripts/auto_archive.py` — standalone script (imports `DatabaseManager` and `GranolaClient` directly, avoids FastMCP dependency)
- `scripts/auto_archive_ctl.sh` — enable/disable/status for macOS launchd scheduling (every 30 min)
- `logs/auto_archive.log` — output log

**CLI:**
```bash
python scripts/auto_archive.py --dry-run          # Preview without writing
python scripts/auto_archive.py --limit 100         # Fetch more docs
python scripts/auto_archive.py --settle-hours 1    # Override settle period
```

**Note:** `detect_client_from_meeting()` lives in `src/services/client_detection.py` and is imported by both `server.py` and `auto_archive.py`.

## AI Todo Extraction

After meetings are archived, an AI agent (Claude Haiku by default) reviews the full transcript and extracts action items as to-dos. It also detects if existing open to-dos were discussed as completed and marks them done.

**Opt-in:** Set `CEREAL_TODO_EXTRACTION=1` in `.env`. Disabled by default.

**Migration:** `psql $DATABASE_URL -f scripts/todo_extraction_migration.sql`

**How it works:**
- Both `auto_archive.py` and `archive_new_meetings` MCP tool trigger extraction post-archival
- Sends the full transcript + existing open todos to Claude Haiku
- LLM returns structured JSON with new action items and completed item matches
- New todos are created via `batch_create_todos()` with `source_context="auto-extracted from '...'"` and `assigned_to` set to `us`/`them`/`unclear`
- Completed todos are matched by title substring (exact single match only, skips ambiguous)
- `todos_extracted_at` timestamp on `meetings` prevents duplicate extraction
- Failures never block archival

**Key files:**
- `src/services/todo_extraction_service.py` — core extraction service
- `scripts/todo_extraction_migration.sql` — migration for `assigned_to` and `todos_extracted_at` columns

**Environment variables:**
- `CEREAL_TODO_EXTRACTION` — set to `1`/`true`/`yes` to enable (default: off)
- `CEREAL_EXTRACTION_MODEL` — override model (default: `claude-haiku-4-5-20251001`)
- `ANTHROPIC_API_KEY` — required when extraction is enabled

## Web App

Flask web app at `http://localhost:5555`. Serves the to-do dashboard (and future pages). Uses `src/services/` for business logic shared with MCP.

```bash
python web/run.py --open                    # Start and open browser
python web/run.py --port 8080               # Custom port
python web/run.py --debug                   # Debug mode with auto-reload
./dashboard/dashboard_ctl.sh enable         # Run via launchd (auto-start on login)
./dashboard/dashboard_ctl.sh status         # Check if running
./dashboard/dashboard_ctl.sh disable        # Stop launchd service
```

- Auto-refreshes every 30 seconds
- Filter by client or show/hide completed items via links
- `view_todos` MCP tool opens the dashboard URL if running, falls back to static HTML if not
- Port configurable via `--port` flag or `DASHBOARD_PORT` env var
- Uses connection pooling (`pool_size=5`) for concurrent requests
- `dashboard/serve.py` kept as deprecated fallback

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

### Service layer

Shared business logic lives in `src/services/`. Services accept a `DatabaseManager` instance and are used by MCP tools, Flask routes, and `auto_archive.py`. If logic is needed in more than one consumer, extract it into a service.

### Testing the MCP server

```bash
cd mcp_server
uv run mcp dev server.py
```

This starts an interactive session where you can test tools directly.

## Configuration

### Environment variables

- `DATABASE_URL` - PostgreSQL connection string (default: `postgresql://localhost:5432/cereal`)
- `INTERNAL_DOMAIN` - Your company's email domain for client detection (e.g., `yourcompany.com`)
- `CEREAL_TODO_EXTRACTION` - Enable AI todo extraction (`1`/`true`/`yes`, default: off)
- `CEREAL_EXTRACTION_MODEL` - LLM model for extraction (default: `claude-haiku-4-5-20251001`)
- `ANTHROPIC_API_KEY` - API key for AI todo extraction

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
    },
    "linear": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.linear.app/sse"]
    }
  }
}
```

The Linear MCP is optional but recommended for project/issue correlation with clients.
