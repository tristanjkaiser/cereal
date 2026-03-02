-- Migration: Add client_todos table for per-client to-do lists
-- Run: psql $DATABASE_URL -f scripts/todos_migration.sql

CREATE TABLE IF NOT EXISTS client_todos (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, in_progress, done, archived
    priority INTEGER NOT NULL DEFAULT 0,             -- 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low
    due_date DATE,
    completed_at TIMESTAMP,
    category VARCHAR(100),                           -- agent-assigned tag: "design", "follow-up", "billing"
    meeting_id INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
    source_context TEXT,                             -- "from workshop 2", "per Slack thread", etc.
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- B-tree indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_client_todos_client_status ON client_todos (client_id, status);
CREATE INDEX IF NOT EXISTS idx_client_todos_due_date ON client_todos (due_date) WHERE status IN ('pending', 'in_progress');
CREATE INDEX IF NOT EXISTS idx_client_todos_priority ON client_todos (priority) WHERE status IN ('pending', 'in_progress');
CREATE INDEX IF NOT EXISTS idx_client_todos_status ON client_todos (status);
