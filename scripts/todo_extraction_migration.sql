-- AI Todo Extraction migration
-- Run: psql $DATABASE_URL -f scripts/todo_extraction_migration.sql

-- Distinguish who owns the action item: us, them, or unclear
ALTER TABLE client_todos ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(20) DEFAULT 'us';

-- Prevent duplicate extraction when auto_archive re-processes a meeting
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS todos_extracted_at TIMESTAMP;
