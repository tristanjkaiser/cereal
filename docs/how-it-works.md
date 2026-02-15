# How Cereal Works: Client Detection & Search Efficiency

## Client Population

### Auto-Client Detection

When `archive_new_meetings` runs, each meeting is automatically assigned to a client via `detect_client_from_meeting()` in `server.py`. Detection uses the following priority order:

1. **Client aliases** (highest priority) — user-defined mappings via `merge_clients` or `add_client_alias`. Checked against the meeting title (case-insensitive).

2. **Known client name** — if an existing client name appears in the title.

3. **Title pattern extraction**:
   - `{Client} x Goji ...` → Client
   - `{Client}: ...` → Client
   - `Record {Client} ...` → Client

4. **External attendee company** — if exactly one non-internal company appears in the attendee list (based on `INTERNAL_DOMAIN` env var, default `gojilabs.com`).

New clients are auto-created via `get_or_create_client()`. Meetings without a detectable client have `client_id = NULL`.

Clients can also be created explicitly via `add_client_context` or `assign_meeting_to_client`.

---

## Search Efficiency

### Tiered Data Access (Progressive Disclosure)

Claude doesn't load full transcripts by default. The tools are designed in tiers:

```
Tier 1: Metadata only (tiny)
├── list_clients()           → names + counts
├── list_recent_meetings()   → titles + dates + IDs
└── list_client_context()    → titles + types + IDs

Tier 2: Summaries (small)
├── get_client_meetings()    → summaries truncated to 500 chars
├── search_meetings()        → snippets + relevance scores
└── search_client_context()  → 300 char previews

Tier 3: Full content (large, on-demand)
├── get_meeting_details()    → full notes (no transcript)
├── get_meeting_transcript() → full transcript (50k+ chars)
└── get_client_context()     → full document content
```

### PostgreSQL Full-Text Search

All search operations use PostgreSQL's built-in full-text search with GIN indexes:

```sql
-- Meetings index (created in setup_database.sql)
CREATE INDEX idx_meetings_content_fts ON meetings
    USING gin(to_tsvector('english',
        COALESCE(transcript, '') || ' ' ||
        COALESCE(enhanced_notes, '') || ' ' ||
        COALESCE(summary_overview, '')
    ));

-- Client context index
CREATE INDEX idx_client_context_fts ON client_context
    USING gin(to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(content, '')));
```

**How it works:**
1. `to_tsvector()` converts text to searchable tokens (stems words, removes stop words)
2. `plainto_tsquery()` converts search query to same format
3. `@@` operator matches query against vector
4. `ts_rank()` scores relevance

Example search query:
```sql
SELECT m.*, ts_rank(...) as rank
FROM meetings m
WHERE to_tsvector('english', ...) @@ plainto_tsquery('english', 'authentication')
ORDER BY rank DESC
LIMIT 10
```

### Truncation Points

| Tool | Field | Limit |
|------|-------|-------|
| `get_client_meetings` | enhanced_notes | 500 chars |
| `search_meetings` | summary_overview | 300 chars |
| `get_meeting_details` | enhanced_notes | 10,000 chars |
| `get_meeting_transcript` | transcript | 50,000 chars |
| `search_client_context` | content_preview | 300 chars |

### Query Flow Example

**User asks**: "What did we discuss about authentication with NGynS?"

**Claude's tool calls**:
```
1. get_client_meetings("NGynS", limit=20)
   → Returns 20 meeting summaries (~500 chars each = ~10k tokens)

2. search_meetings("authentication")
   → Returns 10 matches with 300 char snippets (~3k tokens)

3. get_meeting_details(42)  // If Claude needs more detail
   → Returns full notes for one meeting (~10k chars)

4. get_meeting_transcript(42)  // Only if quoted text needed
   → Returns full transcript (50k+ chars)
```

**Total context used**: ~15-20k tokens instead of loading all transcripts (~500k+)

---

## Database Schema

```
clients (id, name, slug, notes)
    ├── meetings (id, client_id, title, transcript, enhanced_notes, ...)
    ├── client_context (id, client_id, title, content, context_type, ...)
    ├── client_aliases (id, alias, canonical_client_id)
    ├── client_integrations (id, client_id, integration_type, external_id, metadata)
    └── meeting_series (id, name, client_id, meeting_type)
```

Foreign keys enable efficient joins:
```sql
-- Get meetings with client names
SELECT m.*, c.name as client_name
FROM meetings m
LEFT JOIN clients c ON m.client_id = c.id
```

Indexes for common queries:
- `idx_meetings_client` - filter by client
- `idx_meetings_date` - sort by date
- `idx_meetings_content_fts` - full-text search
- `idx_client_context_client` - filter context by client
- `idx_client_context_fts` - search context

---

## Future Improvements

1. **Embedding search**: Semantic similarity instead of just keyword matching
3. **Chunked transcripts**: Retrieve specific time ranges instead of full transcript
4. **Smart summaries**: Auto-generate `content_summary` for context docs
5. **Date range queries**: Filter meetings by date range to reduce result sets
