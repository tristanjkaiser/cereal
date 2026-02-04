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
| `merge_clients` | Merge duplicate clients (e.g., "NB44 - Intuit" → "NB44") |
| `rename_client` | Rename a client and create alias for old name |
| `add_client_alias` | Add alias without merging |
| `list_client_aliases` | Show all configured aliases |
| `delete_client_alias` | Remove an alias |

## Example Conversations

Once configured, you can ask Claude things like:

**Meetings:**
- "Archive my recent meetings"
- "What clients do I have meetings with?"
- "Search my meetings for authentication"
- "What did we discuss with [Client] last week?"
- "Get the transcript for meeting ID 42"

**Client Context:**
- "Save this PRD for NGynS: [paste content]"
- "What context docs do we have for Mothership?"
- "Search client docs for pricing requirements"
- "Update the NGynS estimate with the latest numbers"

**Client Management:**
- "Merge 'NB44 - Intuit' into 'NB44'" - consolidates duplicates
- "Rename 'Acme Corp' to 'Acme'" - renames with alias
- "Add an alias 'Project X' for client 'Mothership'"
- "Show me all client aliases"

## Project Structure

```
cereal/
├── mcp_server/           # MCP server for Claude Desktop
│   ├── server.py         # FastMCP server with tools
│   ├── pyproject.toml    # Dependencies
│   └── run_server.sh     # Launcher script
├── src/                  # Core modules
│   ├── database.py       # PostgreSQL operations
│   └── granola_client.py # Granola API client
├── scripts/
│   └── setup_database.sql
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

1. **Client aliases** (highest priority) - User-defined mappings like "NB44 - Intuit" → "NB44"
2. **Known client match** - If an existing client name appears in the title
3. **Title patterns** - Extracts client from patterns like:
   - `NGynS x Goji Design Check-in` → NGynS
   - `GS1: Review Next Cycle` → GS1
   - `Record NB44 admin tool` → NB44
4. **External attendees** - Uses company info from non-internal attendees

New clients are created automatically when detected. Internal meetings (no external attendees or client patterns) remain unassigned.

Configure the internal domain via `INTERNAL_DOMAIN` env var (default: `gojilabs.com`).

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

### Combined Workflow

Claude uses both MCPs together for meeting preparation:

1. "What's on the agenda for my NGynS meeting?"
2. Claude calls Cereal: `get_client_meetings("NGynS")` → finds recent meetings
3. Claude calls Linear: `list_issues(team: "NGynS")` → finds open issues
4. Claude synthesizes both to suggest agenda items

**Example prompts:**
- "What should I discuss in my Mothership meeting tomorrow?"
- "What issues are blocking the NGynS launch?"
- "Summarize last week's progress on Project X"

## License

MIT
