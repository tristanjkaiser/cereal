-- Dismissed alerts table for the Attention Queue
-- Run: psql postgresql://localhost:5432/cereal -f scripts/dismissed_alerts_migration.sql

CREATE TABLE IF NOT EXISTS dismissed_alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    reference_id INTEGER,
    dismissed_at TIMESTAMP DEFAULT NOW(),
    recheck_after TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dismissed_alerts_lookup
    ON dismissed_alerts (alert_type, reference_id);
