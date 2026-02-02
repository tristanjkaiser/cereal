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
