# Project Intelligence Agent — Architecture Document

## Overview

This document describes an extension to the **Cereal** system (a Python MCP server backed by PostgreSQL) that adds project timeline tracking, Linear integration for progress analysis, and cross-system synthesis to answer the question: **"Where are we on [project]?"**

The system should be able to answer that question by cross-referencing:
- A structured project timeline with phases and milestones
- Real-time Linear ticket status
- Recent meeting transcripts and notes from Cereal
- Slack channel activity

## Context: Existing Cereal System

Cereal is a Python MCP server that connects to a PostgreSQL database. It currently manages:

### Existing Tables (do not modify)
- **meetings** — Archived meeting transcripts and notes from Granola, with client associations
- **clients** — Client records (e.g., NGynS, Mothership, Ways2Wander, NB44, etc.)
- **client_context** — Freeform documents per client (PRDs, estimates, outcomes, notes) with a `context_type` field
- **client_aliases** — Alternate names that map to canonical client names
- **client_integrations** — Links clients to external systems (Linear team IDs, Slack channel IDs)

### Existing Integration Data
Each client can be linked to:
- A **Linear team** (team ID, team name, team key prefix like "WANDER")
- **Slack channels** (internal channel ID, optional external/client-facing channel ID)

### Existing MCP Tools
Cereal exposes tools like `get_client_meetings`, `search_meetings`, `get_meeting_details`, `get_meeting_transcript`, `add_client_context`, `get_client_config`, etc.

---

## Goji Labs Project Lifecycle

All client projects at Goji follow this lifecycle structure. The timeline system must model this:

### Phase 1: Strategy Sprint
- **Duration:** ~2 weeks
- **Structure:** 4 workshops, each ~1.5 hours
- **Purpose:** Product discovery
- **Trackable artifacts:** Workshop meetings (linkable to Cereal meeting IDs)

### Phase 2: Design Phase
- **Duration:** Variable (estimated in SOW as low/high weeks, e.g., 6-8 weeks)
- **Subphases (sequential):**
  1. User Flow IA + Low-fis
  2. UI Exploration
  3. Design System
  4. High-fis
  5. Revisions / Hand-off
- **Trackable artifacts:** Linear tickets in a "Design Phase" project, design review meetings

### Phase 3: Dev Phase
- **Duration:** Variable (estimated in SOW as low/high weeks, e.g., 8-12 weeks)
- **Structure:** Broken into Linear projects with milestones and tickets
- **Trackable artifacts:** Linear tickets, sprints/cycles, PR activity

### SOW Estimates
When a client signs the Statement of Work, estimates are provided:
- Design phase: low/high weeks (e.g., 6-8 weeks)
- Dev phase: low/high weeks (e.g., 8-12 weeks)  
- Overall project: low/high weeks (e.g., 16-22 weeks)

---

## New Database Schema

### Table: `timelines`

The top-level container. One timeline per client project.

```sql
CREATE TABLE timelines (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    project_name TEXT NOT NULL,               -- e.g., "Physician Directory v2"
    sow_signed_date DATE,                     -- when the SOW was signed
    estimated_design_weeks_low NUMERIC(4,1),  -- e.g., 6.0
    estimated_design_weeks_high NUMERIC(4,1), -- e.g., 8.0
    estimated_dev_weeks_low NUMERIC(4,1),     -- e.g., 8.0
    estimated_dev_weeks_high NUMERIC(4,1),    -- e.g., 12.0
    estimated_overall_weeks_low NUMERIC(4,1), -- e.g., 16.0
    estimated_overall_weeks_high NUMERIC(4,1),-- e.g., 22.0
    status TEXT NOT NULL DEFAULT 'active',     -- active, completed, paused, cancelled
    notes TEXT,                                -- freeform notes about the project
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Table: `timeline_phases`

Tracks each major phase and its subphases.

```sql
CREATE TABLE timeline_phases (
    id SERIAL PRIMARY KEY,
    timeline_id INTEGER NOT NULL REFERENCES timelines(id) ON DELETE CASCADE,
    parent_phase_id INTEGER REFERENCES timeline_phases(id) ON DELETE CASCADE,  -- NULL for top-level phases, set for subphases
    name TEXT NOT NULL,                        -- e.g., "Strategy Sprint", "Design Phase", "UI Exploration"
    phase_type TEXT NOT NULL,                  -- 'strategy', 'design', 'dev', 'design_subphase'
    sort_order INTEGER NOT NULL DEFAULT 0,     -- ordering within siblings
    status TEXT NOT NULL DEFAULT 'upcoming',   -- upcoming, in_progress, completed, skipped
    planned_start_date DATE,
    planned_end_date DATE,
    actual_start_date DATE,
    actual_end_date DATE,
    planned_duration_weeks_low NUMERIC(4,1),   -- for phases with range estimates
    planned_duration_weeks_high NUMERIC(4,1),
    linear_project_id TEXT,                    -- links to a Linear project (UUID)
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Table: `timeline_milestones`

Key checkpoints within phases. Can link to Linear tickets or projects.

```sql
CREATE TABLE timeline_milestones (
    id SERIAL PRIMARY KEY,
    phase_id INTEGER NOT NULL REFERENCES timeline_phases(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                        -- e.g., "Low-fi Approval", "Beta Launch"
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',    -- pending, achieved, missed, deferred
    target_date DATE,
    actual_date DATE,
    linear_issue_id TEXT,                      -- optional link to a specific Linear issue
    linear_project_id TEXT,                    -- optional link to a Linear project
    meeting_id INTEGER REFERENCES meetings(id), -- optional link to milestone meeting in Cereal
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Table: `timeline_workshops`

Specifically tracks Strategy Sprint workshops (since they follow a predictable structure).

```sql
CREATE TABLE timeline_workshops (
    id SERIAL PRIMARY KEY,
    phase_id INTEGER NOT NULL REFERENCES timeline_phases(id) ON DELETE CASCADE,
    workshop_number INTEGER NOT NULL,          -- 1, 2, 3, 4
    scheduled_date DATE,
    actual_date DATE,
    meeting_id INTEGER REFERENCES meetings(id), -- link to Cereal meeting record
    status TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled, completed, cancelled, rescheduled
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Table: `timeline_snapshots`

Stores point-in-time assessments of project health. This is what the agent writes every time it evaluates "are we on track?"

```sql
CREATE TABLE timeline_snapshots (
    id SERIAL PRIMARY KEY,
    timeline_id INTEGER NOT NULL REFERENCES timelines(id) ON DELETE CASCADE,
    snapshot_date TIMESTAMP NOT NULL DEFAULT NOW(),
    health TEXT NOT NULL,                       -- on_track, at_risk, off_track
    current_phase TEXT NOT NULL,                -- which phase is active
    summary TEXT NOT NULL,                      -- human-readable assessment
    linear_stats JSONB,                        -- ticket counts by status at time of snapshot
    details JSONB,                             -- flexible store for any additional data
    triggered_by TEXT,                         -- 'manual', 'scheduled', 'query'
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Table: `timeline_linear_mappings`

Maps Linear projects/milestones to timeline phases for automatic progress tracking.

```sql
CREATE TABLE timeline_linear_mappings (
    id SERIAL PRIMARY KEY,
    timeline_id INTEGER NOT NULL REFERENCES timelines(id) ON DELETE CASCADE,
    phase_id INTEGER REFERENCES timeline_phases(id) ON DELETE CASCADE,
    milestone_id INTEGER REFERENCES timeline_milestones(id) ON DELETE CASCADE,
    linear_project_id TEXT,                    -- Linear project UUID
    linear_project_name TEXT,                  -- human-readable name
    linear_milestone_id TEXT,                  -- Linear milestone UUID (if applicable)
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- At least one of phase_id or milestone_id must be set
    CONSTRAINT mapping_target CHECK (phase_id IS NOT NULL OR milestone_id IS NOT NULL)
);
```

---

## New MCP Tools

Add the following tools to the Cereal MCP server. Follow the same patterns as existing tools (function signatures, docstrings, database access patterns).

### Timeline Management

#### `create_timeline`
Create a new project timeline for a client.

**Parameters:**
- `client_name` (required) — Client name (resolved via existing client lookup logic)
- `project_name` (required) — e.g., "Physician Directory v2"
- `sow_signed_date` (optional) — ISO date
- `design_weeks_low`, `design_weeks_high` (optional) — Estimated design duration range
- `dev_weeks_low`, `dev_weeks_high` (optional) — Estimated dev duration range
- `overall_weeks_low`, `overall_weeks_high` (optional) — Estimated overall duration range
- `auto_create_phases` (optional, default true) — If true, automatically creates the standard Goji phase structure: Strategy Sprint, Design Phase (with all 5 subphases), and Dev Phase

**Returns:** Timeline ID and summary of what was created.

#### `get_timeline`
Get a client's timeline with all phases, subphases, milestones, and current status.

**Parameters:**
- `client_name` (required) — Client name
- `project_name` (optional) — If client has multiple timelines, specify which one
- `include_linear_status` (optional, default false) — If true, also queries Linear for current ticket counts per mapped project

**Returns:** Full timeline structure with phase statuses and optional Linear data.

#### `update_phase`
Update a timeline phase's status, dates, or notes.

**Parameters:**
- `phase_id` (required) — Phase ID
- `status` (optional) — upcoming, in_progress, completed, skipped
- `actual_start_date` (optional) — ISO date
- `actual_end_date` (optional) — ISO date
- `linear_project_id` (optional) — Link to a Linear project
- `notes` (optional)

**Returns:** Updated phase details.

#### `update_milestone`
Update a milestone's status and dates.

**Parameters:**
- `milestone_id` (required) — Milestone ID
- `status` (optional) — pending, achieved, missed, deferred
- `actual_date` (optional) — ISO date
- `meeting_id` (optional) — Link to a Cereal meeting
- `linear_issue_id` (optional) — Link to a Linear issue

**Returns:** Updated milestone details.

#### `add_milestone`
Add a new milestone to a phase.

**Parameters:**
- `phase_id` (required) — Phase to add the milestone to
- `name` (required)
- `description` (optional)
- `target_date` (optional)
- `linear_issue_id` (optional)
- `linear_project_id` (optional)

**Returns:** Created milestone details.

#### `record_workshop`
Record a Strategy Sprint workshop completion.

**Parameters:**
- `phase_id` (required) — The Strategy Sprint phase ID
- `workshop_number` (required) — 1-4
- `date` (optional) — Date of the workshop (defaults to today)
- `meeting_id` (optional) — Link to Cereal meeting record

**Returns:** Updated workshop details.

#### `list_timelines`
List all active timelines, optionally filtered by client.

**Parameters:**
- `client_name` (optional) — Filter to a specific client
- `status` (optional) — Filter by timeline status (active, completed, etc.)

**Returns:** Summary list of timelines with current phase and health.

### Linear Mapping

#### `map_linear_to_phase`
Connect a Linear project to a timeline phase for automatic progress tracking.

**Parameters:**
- `phase_id` (required) — Timeline phase ID
- `linear_project_id` (required) — Linear project UUID
- `linear_project_name` (optional) — Human-readable name

**Returns:** Confirmation of mapping.

#### `map_linear_to_milestone`
Connect a Linear issue or project to a timeline milestone.

**Parameters:**
- `milestone_id` (required) — Timeline milestone ID
- `linear_issue_id` (optional) — Linear issue UUID
- `linear_project_id` (optional) — Linear project UUID

**Returns:** Confirmation of mapping.

### Project Health Assessment

#### `assess_project_health`
The core synthesis tool. Evaluates project status by cross-referencing the timeline, Linear data, meeting notes, and Slack activity.

**Parameters:**
- `client_name` (required) — Client name
- `project_name` (optional) — Specific project (defaults to active timeline)
- `save_snapshot` (optional, default true) — Whether to persist the assessment

**Returns:** A structured assessment including:
- Current phase and subphase
- Time elapsed vs. estimated for current phase
- Linear ticket breakdown (total, completed, in progress, blocked)
- Key decisions/blockers from recent meetings (last 2 weeks)
- Risk flags (e.g., "50% of time elapsed but only 30% of tickets done")
- Overall health rating: on_track, at_risk, off_track

**Implementation Notes:**
This tool should:
1. Load the timeline from the database
2. Identify the current active phase
3. Use the existing `get_client_config` to get the Linear team ID
4. Query Linear (via the Linear MCP tools or direct API) for ticket status on mapped projects
5. Use `get_client_meetings` from Cereal to pull recent meetings
6. Optionally use `get_client_slack` to identify relevant Slack channels for context
7. Synthesize all data into a health assessment
8. Store a snapshot if `save_snapshot` is true

**Important:** The health assessment logic does NOT need to be deterministic or rule-based. The primary consumer is Claude (via MCP), so the assessment can be generated by prompting Claude with the raw data and asking for synthesis. The `summary` field in the snapshot should be a natural language assessment. The `linear_stats` JSONB field captures the raw numbers for historical tracking.

#### `get_project_snapshots`
Retrieve historical health assessments for a project.

**Parameters:**
- `client_name` (required)
- `project_name` (optional)
- `limit` (optional, default 10)
- `since` (optional) — ISO date, only return snapshots after this date

**Returns:** List of snapshots showing project health trajectory over time.

---

## Example Query Flows

### "Where are we on NGynS?"

1. `get_timeline(client_name="NGynS")` → Returns timeline showing Design Phase active, UI Exploration subphase in progress
2. Agent sees `linear_project_id` mapped to the Design Phase → Queries Linear for ticket breakdown
3. Agent calls `get_client_meetings(client_name="NGynS", limit=5)` → Gets recent meeting context
4. Agent synthesizes: "NGynS is in the Design Phase, currently on UI Exploration. The SOW estimated 6-8 weeks for design; we're 2.5 weeks in. Linear shows 12 of 28 design tickets completed. Last meeting with Natalya on Feb 12 approved low-fis with minor revisions. No blockers identified. On track for the 6-week estimate."
5. Snapshot stored for historical tracking.

### "Are any projects at risk?"

1. `list_timelines(status="active")` → Returns all active project timelines
2. For each, run a lightweight health check (compare elapsed time vs. completion percentage)
3. Flag any where completion percentage significantly lags time percentage
4. Return summary: "NGynS: on track. Ways2Wander: at risk — 60% through dev phase but only 35% of tickets completed."

### "What happened on [project] this week?"

1. `get_client_meetings(client_name="X", limit=10)` → Filter to this week
2. `get_timeline(client_name="X")` → Get timeline context
3. Query Linear for tickets updated this week on mapped projects
4. Synthesize a weekly summary with meeting decisions, ticket progress, and timeline impact

---

## Implementation Notes for Claude Code

### File Structure
Add new files to the existing Cereal MCP server codebase. Follow existing patterns for:
- Database migration (SQL file to create new tables)
- MCP tool registration (same decorator/registration pattern as existing tools)
- Database access (same connection pool / query patterns)
- Error handling and client name resolution (reuse existing `resolve_client` logic)

### Migration
Create a SQL migration file that can be run against the existing PostgreSQL database. The migration should:
1. Create all new tables (`timelines`, `timeline_phases`, `timeline_milestones`, `timeline_workshops`, `timeline_snapshots`, `timeline_linear_mappings`)
2. Add indexes on foreign keys and commonly queried columns (`client_id`, `timeline_id`, `status`, `snapshot_date`)
3. Be idempotent (use `CREATE TABLE IF NOT EXISTS`)

### The `auto_create_phases` Logic
When creating a timeline with `auto_create_phases=True`, automatically create:

```
Phase: Strategy Sprint (phase_type='strategy', sort_order=0)
Phase: Design Phase (phase_type='design', sort_order=1)
  └─ Subphase: User Flow IA + Low-fis (phase_type='design_subphase', sort_order=0)
  └─ Subphase: UI Exploration (phase_type='design_subphase', sort_order=1)
  └─ Subphase: Design System (phase_type='design_subphase', sort_order=2)
  └─ Subphase: High-fis (phase_type='design_subphase', sort_order=3)
  └─ Subphase: Revisions / Hand-off (phase_type='design_subphase', sort_order=4)
Phase: Dev Phase (phase_type='dev', sort_order=2)
```

Also create 4 workshop records for the Strategy Sprint phase.

### Linear Integration
The `assess_project_health` tool needs to query Linear. There are two approaches:

1. **MCP-to-MCP** — Have the health assessment tool call the Linear MCP tools. This keeps the architecture clean but means Cereal depends on Linear MCP being available.
2. **Direct API** — Have Cereal call the Linear API directly. More self-contained but adds API key management.

**Recommendation:** Use approach 1 (MCP-to-MCP) since Claude orchestrates both. The `assess_project_health` tool should return the raw timeline data and signal to Claude that it should also query Linear for the mapped projects. Claude then synthesizes everything. This keeps Cereal focused on data storage/retrieval and lets Claude handle the cross-system orchestration.

In practice, this means `assess_project_health` returns the timeline data including any `linear_project_id` mappings, and Claude's instructions (or a wrapper tool) handle querying Linear and producing the synthesis. The snapshot is then stored via a separate `save_snapshot` call.

### Future: Team Query Interface
The architecture is designed to support a future feature where team members (e.g., David) can query project context through a Slack bot or similar interface. The timeline + snapshot data provides the structured backbone, and Cereal's existing meeting search provides the conversational context. This is out of scope for the initial build but the schema supports it.

### Future: Automated Meeting Archival
A separate workstream will add automatic meeting archival from Granola to Cereal (triggered by calendar events completing). This is out of scope here but will feed the timeline system with richer meeting data automatically.

---

## Current Client Data (for initial setup/testing)

### NGynS
- **Linear Team:** 594b4ff2-382e-4e99-b3e0-61d7ca33c75d (VisionaryASC–NGynS)
- **Slack Internal:** C09T29F4AJY
- **Linear Projects:** "Design Phase" (in progress, started 2026-01-29), "Post-Strategy Planning" (next), plus several future projects (Chat, User Management, Claimed Provider Profiles, Admin, Conversion, Provider Profiles, Provider Discovery, Educational Content)
- **Current State:** Strategy Sprint completed, Design Phase in progress
- **Cereal Meetings:** 4 archived NGynS meetings
- **PRD:** Context document ID 1

### Other Active Clients
- **Ways2Wander** — Linear team: 05511a76-c9fc-4800-9d88-8c19c28226b5 (key: WANDER), Slack: C0A20JC8A3V
- **NB44** — Linear team: 546603cf-30c7-4321-afab-591e8cd132e3
- **Tricon** — Linear team: 0579b903-38b3-474e-979f-08cb31861ffa (key: TRICON), Slack: internal C09NBUCHY1F, external C09P61PBWAZ
- **Mothership** — Linear team: 6f28b424-2246-4fe5-9f50-f1b19b1e46cb
- **Bug Reporter** — Linear team: d700e75d-19fb-4c6b-90b8-5e71eb2fb68f
- **Gaido** — Linear team: bf18fdab-c31d-444f-8738-76a5e909b67f (key: GAID), Slack: internal C064R5B1074, external C08029VUGS0

---

## Summary of Deliverables

1. **SQL migration** — Creates all new tables with indexes
2. **MCP tools** — ~10 new tools following existing Cereal patterns:
   - `create_timeline`, `get_timeline`, `list_timelines`
   - `update_phase`, `add_milestone`, `update_milestone`
   - `record_workshop`
   - `map_linear_to_phase`, `map_linear_to_milestone`
   - `assess_project_health`, `get_project_snapshots`
3. **Auto-phase creation logic** — Standard Goji lifecycle template
4. **Documentation** — Inline docstrings on all tools matching existing Cereal style

Build order recommendation:
1. Migration + table creation
2. `create_timeline` with `auto_create_phases`
3. `get_timeline` and `list_timelines`
4. Phase/milestone update tools
5. Linear mapping tools
6. `assess_project_health` and `get_project_snapshots`
7. Test with NGynS data
