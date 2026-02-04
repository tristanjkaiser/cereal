# Cereal Skills

This folder contains Claude Skills that extend Cereal's capabilities by combining data from multiple MCP servers.

## Available Skills

### client-agenda.md

Generates focused meeting agendas by synthesizing Linear tickets and recent Cereal meeting notes.

**Triggers:**
- "agenda for [client]"
- "prep for meeting with [client]"
- "what should we discuss with [client]"
- "client meeting prep"
- "prepare for [client] call"

**What it does:**
1. Identifies the client from your request
2. Fetches active Linear projects and issues (Next/In Progress states)
3. Retrieves recent Cereal meetings and client context
4. Generates a structured agenda with status updates, discussion items, and open questions
5. Saves the agenda as a markdown file

**Requirements:**
- Both Cereal and Linear MCP servers configured in Claude Desktop
- Client must be linked to a Linear team (use `link_client_to_linear_team`)

## Using Skills in Claude Desktop

Skills are reusable prompt templates that guide Claude through complex workflows. To use a skill:

1. Copy the skill file (`.md`) to Claude Desktop's skills directory:
   ```bash
   cp skills/client-agenda.md ~/Library/Application\ Support/Claude/skills/
   ```

2. Restart Claude Desktop to load the skill

3. Trigger the skill by using one of the trigger phrases in your conversation:
   ```
   "Generate an agenda for my ClientA meeting"
   ```

## Creating Your Own Skills

Skills are markdown files with frontmatter defining:
- `name` - unique identifier
- `description` - what the skill does and when to trigger it
- `TRIGGERS` - phrases that should activate this skill

The body contains the workflow Claude should follow.

**Example structure:**
```markdown
---
name: my-skill
description: |
  What this skill does.
  TRIGGERS: "trigger phrase 1", "trigger phrase 2"
---

# Skill Name

[Detailed instructions for Claude to follow]
```

## Skill Ideas

Here are some other skills you could create for Cereal:

- **weekly-summary** - Summarize all client meetings from the past week
- **project-retrospective** - Analyze completed Linear projects with meeting context
- **client-onboarding** - Create a comprehensive context doc when starting with a new client
- **action-items** - Extract and track action items across all recent meetings
- **client-report** - Generate a client-facing progress report from tickets and notes
