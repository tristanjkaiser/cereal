-- Add sort_order column for drag-and-drop reordering
-- Run: psql postgresql://localhost:5432/cereal -f scripts/todos_sort_order_migration.sql

ALTER TABLE client_todos ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;
