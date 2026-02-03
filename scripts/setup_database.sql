-- PM Agent Database Schema
-- PostgreSQL schema for archiving meeting transcripts and notes

-- Clients/companies for categorization
CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    slug VARCHAR(100) UNIQUE,  -- e.g., "mothership", "ngyns"
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Recurring meeting series (e.g., "Weekly Standup with Acme")
CREATE TABLE IF NOT EXISTS meeting_series (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    meeting_type VARCHAR(50),  -- strategy_kickoff, planning, etc.
    recurrence_pattern VARCHAR(50),  -- weekly, biweekly, monthly
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Core meetings table with full content
CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    granola_document_id VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(500) NOT NULL,
    meeting_date TIMESTAMP NOT NULL,

    -- Categorization
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    meeting_series_id INTEGER REFERENCES meeting_series(id) ON DELETE SET NULL,
    meeting_type VARCHAR(50) DEFAULT 'general',
    meeting_type_confidence DECIMAL(3,2),

    -- Full content (the archive)
    transcript TEXT,
    enhanced_notes TEXT,
    manual_notes TEXT,
    combined_markdown TEXT,  -- What gets sent to AI

    -- AI-generated summary
    summary_overview TEXT,
    summary_json JSONB,  -- Full summary structure

    -- Metadata
    processed_at TIMESTAMP,
    archived_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for querying
CREATE INDEX IF NOT EXISTS idx_meetings_client ON meetings(client_id);
CREATE INDEX IF NOT EXISTS idx_meetings_series ON meetings(meeting_series_id);
CREATE INDEX IF NOT EXISTS idx_meetings_type ON meetings(meeting_type);
CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(meeting_date);
CREATE INDEX IF NOT EXISTS idx_meetings_granola_id ON meetings(granola_document_id);

-- Full-text search index on transcript (for future querying)
CREATE INDEX IF NOT EXISTS idx_meetings_transcript_fts ON meetings
    USING gin(to_tsvector('english', COALESCE(transcript, '')));

-- Full-text search on combined content
CREATE INDEX IF NOT EXISTS idx_meetings_content_fts ON meetings
    USING gin(to_tsvector('english',
        COALESCE(transcript, '') || ' ' ||
        COALESCE(enhanced_notes, '') || ' ' ||
        COALESCE(summary_overview, '')
    ));

-- Client context documents (PRDs, estimates, outcomes, etc.)
CREATE TABLE IF NOT EXISTS client_context (
    id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    context_type VARCHAR(50) DEFAULT 'note',  -- prd, estimate, outcome, contract, note
    content TEXT NOT NULL,
    content_summary TEXT,  -- Optional summary for token efficiency
    source_url TEXT,  -- Optional link to original doc
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for client context
CREATE INDEX IF NOT EXISTS idx_client_context_client ON client_context(client_id);
CREATE INDEX IF NOT EXISTS idx_client_context_type ON client_context(context_type);

-- Full-text search on client context
CREATE INDEX IF NOT EXISTS idx_client_context_fts ON client_context
    USING gin(to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(content, '')));

-- Client aliases for name normalization (e.g., "NB44 - Intuit" → "NB44")
CREATE TABLE IF NOT EXISTS client_aliases (
    id SERIAL PRIMARY KEY,
    alias VARCHAR(255) NOT NULL UNIQUE,  -- The alternate name to recognize
    canonical_client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_aliases_alias ON client_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_client_aliases_client ON client_aliases(canonical_client_id);
