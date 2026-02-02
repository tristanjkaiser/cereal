# Cereal

> Your Granola meetings, now part of your second brain.

Query your [Granola](https://granola.ai) meeting transcripts directly from Claude using MCP (Model Context Protocol).

## Features

- **Search** across all meeting transcripts and notes
- **Query by client** - find all meetings with a specific client
- **Full transcripts** - get complete meeting details on demand
- **Archive from Claude** - tell Claude to "archive my recent meetings"
- **Client management** - auto-detect clients from meeting titles

## Prerequisites

- [PostgreSQL](https://www.postgresql.org/) database
- [Granola](https://granola.ai) account with meetings
- [Claude Desktop](https://claude.ai/download) with MCP support
- [uv](https://github.com/astral-sh/uv) package manager

## Quick Start

### 1. Clone and setup

```bash
git clone https://github.com/yourusername/cereal.git
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

| Tool | Description |
|------|-------------|
| `archive_new_meetings` | Archive new meetings from Granola |
| `list_clients` | List all clients with meeting counts |
| `list_recent_meetings` | Get meetings from last N days |
| `get_client_meetings` | Get all meetings for a client |
| `search_meetings` | Full-text search across transcripts |
| `get_meeting_details` | Get notes for a specific meeting |
| `get_meeting_transcript` | Get full transcript |
| `find_meeting_by_title` | Find meetings by title |
| `get_meeting_stats` | Archive statistics |

## Example Conversations

Once configured, you can ask Claude things like:

- "Archive my recent meetings"
- "What clients do I have meetings with?"
- "Search my meetings for authentication"
- "What did we discuss with [Client] last week?"
- "Get the transcript for meeting ID 42"

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

## License

MIT
