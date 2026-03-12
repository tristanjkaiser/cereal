-- Activity log for pipeline monitoring.
-- Append-only, no foreign keys. Safe to drop without affecting the rest of the system.

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    summary TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_log_created ON activity_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_type ON activity_log(event_type);
