---
name: client-agenda
description: |
  Generate meeting agendas for client meetings by synthesizing Linear tickets and recent meeting notes from cereal.
  TRIGGERS: "agenda for [client]", "prep for meeting with [client]", "what should we discuss with [client]", "client meeting prep", "generate agenda", "prepare for [client] call"
---

# Client Agenda Generator

Generate focused meeting agendas by pulling together Linear tickets and recent meeting context.

## Workflow

### 1. Identify the Client

If client name is ambiguous or not provided, use `list_clients` (cereal) to show options and confirm.

### 2. Gather Data (parallel)

**Linear** via `list_projects`:
- Filter projects by state: "Next" or "In Progress" only
- For each active project, use `list_issues` to get:
  - States: "Todo", "In Progress", "Blocked"
  - Include: title, assignee, priority, description snippet
- Skip projects in "Completed", "Backlog", or "Cancelled" states

**Cereal**:
- `get_client_meetings` (limit: 5) — recent summaries
- `list_client_context` — PRDs, estimates, outcomes
- `search_meetings` with client name — find open threads

### 3. Generate Agenda

```markdown
# [Client] Meeting Agenda
**Date:** [today]

## Status Updates (In Progress)
[Tickets currently being worked on — what to report]

## Items to Discuss (Todo/Blocked)
[Tickets needing decisions, prioritization, or unblocking]

## Open Questions
[From meeting notes: "to discuss", pending decisions, incomplete action items]

## Quick Context
[2-3 sentence summary of current state from recent notes]
```

### 4. Output

Save as `[client]-agenda-[YYYY-MM-DD].md`

## Tips

- Flag tickets stuck "In Progress" across multiple meetings
- Search notes for: "TODO", "Action item", "Need to discuss", "Blocked", "Question"
- Reference PRD milestones or estimate deliverables when relevant
- Prioritize by urgency when listing items
