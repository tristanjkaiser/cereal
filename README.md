# Cereal

> Your Granola meetings, now part of your second brain.

Query your [Granola](https://granola.ai) meeting transcripts directly from Claude using MCP (Model Context Protocol).

## Features

- **Search** across all meeting transcripts and notes
- **Query by client** - find all meetings with a specific client
- **Full transcripts** - get complete meeting details on demand
- **Archive from Claude** - tell Claude to "archive my recent meetings"
- **Auto-client detection** - automatically assigns clients based on meeting titles and attendees
- **Client context** - store PRDs, estimates, and other docs per client
- **Linear integration** - pair with Linear MCP for project/issue context
- **Slack integration** - link clients to internal and external Slack channels

## Prerequisites

- [PostgreSQL](https://www.postgresql.org/) database
- [Granola](https://granola.ai) account with meetings
- [Claude Desktop](https://claude.ai/download) with MCP support
- [uv](https://github.com/astral-sh/uv) package manager

## Quick Start

### 1. Clone and setup

```bash
git clone https://github.com/tristanjkaiser/cereal.git
cd cereal
```

### 2. Create database

```bash
# Using Postgres.app or psql
createdb cereal

# Run schema
psql cereal < scripts/setup_database.sql
psql cereal < scripts/timeline_migration.sql
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 4. Install MCP server dependencies

```bash
cd mcp_server
uv sync
cd ..
```

### 5. Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

### 6. Restart Claude Desktop

Quit and reopen Claude Desktop. You should see the MCP server indicator.

### 7. Archive your meetings

Ask Claude: "Archive my recent meetings from Granola"

## MCP Tools

### Meeting Tools

| Tool | Description |
|------|-------------|
| `archive_new_meetings` | Archive new meetings from Granola (auto-detects clients) |
| `list_clients` | List all clients with meeting counts |
| `list_recent_meetings` | Get meetings from last N days |
| `get_client_meetings` | Get all meetings for a client |
| `search_meetings` | Full-text search across transcripts |
| `get_meeting_details` | Get notes for a specific meeting |
| `get_meeting_transcript` | Get full transcript |
| `find_meeting_by_title` | Find meetings by title |
| `get_meeting_stats` | Archive statistics |
| `assign_meeting_to_client` | Manually assign a meeting to a client |

### Client Context Tools

| Tool | Description |
|------|-------------|
| `add_client_context` | Save PRDs, estimates, outcomes for a client |
| `list_client_context` | List all context docs for a client |
| `get_client_context` | Get full content of a context doc |
| `search_client_context` | Search across all client context |
| `update_client_context` | Update an existing context doc |
| `delete_client_context` | Delete a context doc |

### Client Management Tools

| Tool | Description |
|------|-------------|
| `merge_clients` | Merge duplicate clients (e.g., "ClientB - BigCo" → "ClientB") |
| `rename_client` | Rename a client and create alias for old name |
| `add_client_alias` | Add alias without merging |
| `list_client_aliases` | Show all configured aliases |
| `delete_client_alias` | Remove an alias |

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

### Timeline Tools

| Tool | Description |
|------|-------------|
| `create_timeline` | Create a project timeline for a client |
| `get_timeline` | Get full timeline with phases, milestones, and status |
| `list_timelines` | List all timelines, optionally filtered by client or status |
| `update_phase` | Update phase status, dates, or link to Linear project |
| `add_milestone` | Add a milestone to a phase |
| `update_milestone` | Update milestone status and dates |
| `record_workshop` | Record Strategy Sprint workshop completion |
| `map_linear_to_phase` | Connect a Linear project to a timeline phase |
| `map_linear_to_milestone` | Connect a Linear issue/project to a milestone |
| `assess_project_health` | Cross-reference timeline + meetings + Linear for health assessment |
| `get_project_snapshots` | Historical health assessments for a project |

## Example Conversations

Once configured, you can ask Claude things like:

**Meetings:**
- "Archive my recent meetings"
- "What clients do I have meetings with?"
- "Search my meetings for authentication"
- "What did we discuss with [Client] last week?"
- "Get the transcript for meeting ID 42"

**Client Context:**
- "Save this PRD for ClientA: [paste content]"
- "What context docs do we have for ClientC?"
- "Search client docs for pricing requirements"
- "Update the ClientA estimate with the latest numbers"

**Client Management:**
- "Merge 'ClientB - BigCo' into 'ClientB'" - consolidates duplicates
- "Rename 'ClientE Corp' to 'ClientE'" - renames with alias
- "Add an alias 'Project Alpha' for client 'ClientC'"
- "Show me all client aliases"

**Integrations:**
- "Help me map my clients to Linear teams"
- "Link client ClientA to Linear team [team_id]"
- "Link client ClientA to Slack channel C0A20JC8A3V"
- "Show me integration status for all clients"
- "What Linear team is ClientC linked to?"

## Project Structure

```
cereal/
├── mcp_server/               # MCP server for Claude Desktop
│   ├── server.py             # FastMCP server with tools
│   ├── pyproject.toml        # Dependencies
│   └── run_server.sh         # Launcher script
├── src/                      # Core modules
│   ├── database.py           # PostgreSQL operations
│   └── granola_client.py     # Granola API client
├── scripts/
│   ├── setup_database.sql    # Core database schema
│   ├── timeline_migration.sql # Timeline tables
│   ├── auto_archive.py       # Automated meeting archival
│   └── auto_archive_ctl.sh   # Enable/disable auto-archive schedule
├── skills/                   # Claude Code skill prompts
├── docs/                     # Architecture and design docs
├── .env.example
└── README.md
```

## How It Works

1. **Granola** stores your meeting transcripts locally
2. **Cereal** fetches transcripts via Granola's local API
3. Meetings are archived to **PostgreSQL** with full-text search
4. **Claude** queries your archive via MCP tools

## Auto-Client Detection

When archiving meetings, Cereal automatically detects and assigns clients using:

1. **Client aliases** (highest priority) - User-defined mappings like "ClientB - BigCo" → "ClientB"
2. **Known client match** - If an existing client name appears in the title
3. **Title patterns** - Extracts client from patterns like:
   - `ClientA x Goji Design Check-in` → ClientA
   - `ClientD: Review Next Cycle` → ClientD
   - `Record ClientB admin tool` → ClientB
4. **External attendees** - Uses company info from non-internal attendees

New clients are created automatically when detected. Internal meetings (no external attendees or client patterns) remain unassigned.

Configure the internal domain via `INTERNAL_DOMAIN` env var (default: `gojilabs.com`).

## Slack Integration (Optional)

Link clients to their Slack channels so Claude can correlate meeting notes with the right communication channels:

```
"Link client ClientA to Slack channel C0A20JC8A3V"
"Link client ClientA to Slack channel C0A20JC8A3V with external channel C08029VUGS0"
"What Slack channels are linked to ClientA?"
```

Each client can have an **internal** channel (team-only) and optionally an **external** channel (shared with the client). These mappings are stored in Cereal's database for cross-referencing.

## Auto-Archive (Optional)

Instead of manually telling Claude to archive meetings, you can run a background script that archives automatically every 30 minutes using macOS launchd.

**How it works:** Meetings are archived after a 2-hour settling period (to ensure Granola has finalized AI notes). Meetings older than 3 hours are left alone. Everything in the window is upserted, so partial archives self-heal on the next run.

### Setup

```bash
# Install dependencies
cd cereal
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Test it first
venv/bin/python scripts/auto_archive.py --dry-run

# Enable the schedule (runs every 30 min)
bash scripts/auto_archive_ctl.sh enable

# Check status
bash scripts/auto_archive_ctl.sh status

# Disable when no longer needed
bash scripts/auto_archive_ctl.sh disable
```

Logs go to `logs/auto_archive.log`. The settling window is configurable via `AUTO_ARCHIVE_SETTLE_HOURS` and `AUTO_ARCHIVE_FRESHNESS_HOURS` env vars.

## Linear Integration (Optional)

Pair Cereal with [Linear's official MCP server](https://linear.app/docs/mcp-server) for project/issue context alongside meeting notes.

### Setup

Add Linear to your Claude Desktop config:

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

After restarting Claude Desktop, ask Claude to "Authenticate with Linear" to complete the OAuth flow.

### What Linear MCP Provides

- `list_issues` - Filter by team, project, assignee, state
- `get_issue` - Detailed issue info with attachments
- `create_issue`, `update_issue` - Manage issues
- `list_projects`, `get_project` - Project details
- `list_teams` - All your Linear teams
- `post_comment` - Add comments to issues

### Linking Clients to Linear Teams

For reliable cross-system correlation, link your Cereal clients to Linear teams:

```
"Link client ClientA to Linear team team_abc123"
"Show me integration status for all clients"
```

This stores the mapping in Cereal's database, so Claude can reliably match data even when names differ (e.g., "ClientA" in Cereal vs "ClientA Engineering" in Linear).

### Combined Workflow

Claude uses both MCPs together for meeting preparation:

1. "What's on the agenda for my ClientA meeting?"
2. Claude calls Cereal: `get_client_meetings("ClientA")` → finds recent meetings
3. Claude calls Linear: `list_issues(team: "ClientA")` → finds open issues
4. Claude synthesizes both to suggest agenda items

**Example prompts:**
- "What should I discuss in my ClientA meeting tomorrow?"
- "What issues are blocking the ClientB launch?"
- "Summarize last week's progress on Project Alpha"
- "Help me map my clients to Linear teams"

## License

MIT
