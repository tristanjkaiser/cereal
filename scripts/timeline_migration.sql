-- Timeline tables for project tracking
-- Run against existing cereal database: psql $DATABASE_URL -f scripts/timeline_migration.sql

-- Top-level container: one timeline per client project
CREATE TABLE IF NOT EXISTS timelines (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    project_name TEXT NOT NULL,
    sow_signed_date DATE,
    estimated_design_weeks_low NUMERIC(4,1),
    estimated_design_weeks_high NUMERIC(4,1),
    estimated_dev_weeks_low NUMERIC(4,1),
    estimated_dev_weeks_high NUMERIC(4,1),
    estimated_overall_weeks_low NUMERIC(4,1),
    estimated_overall_weeks_high NUMERIC(4,1),
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timelines_client ON timelines(client_id);
CREATE INDEX IF NOT EXISTS idx_timelines_status ON timelines(status);

-- Tracks each major phase and its subphases
CREATE TABLE IF NOT EXISTS timeline_phases (
    id SERIAL PRIMARY KEY,
    timeline_id INTEGER NOT NULL REFERENCES timelines(id) ON DELETE CASCADE,
    parent_phase_id INTEGER REFERENCES timeline_phases(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    phase_type TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'upcoming',
    planned_start_date DATE,
    planned_end_date DATE,
    actual_start_date DATE,
    actual_end_date DATE,
    planned_duration_weeks_low NUMERIC(4,1),
    planned_duration_weeks_high NUMERIC(4,1),
    linear_project_id TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeline_phases_timeline ON timeline_phases(timeline_id);
CREATE INDEX IF NOT EXISTS idx_timeline_phases_parent ON timeline_phases(parent_phase_id);
CREATE INDEX IF NOT EXISTS idx_timeline_phases_status ON timeline_phases(status);

-- Key checkpoints within phases
CREATE TABLE IF NOT EXISTS timeline_milestones (
    id SERIAL PRIMARY KEY,
    phase_id INTEGER NOT NULL REFERENCES timeline_phases(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    target_date DATE,
    actual_date DATE,
    linear_issue_id TEXT,
    linear_project_id TEXT,
    meeting_id INTEGER REFERENCES meetings(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeline_milestones_phase ON timeline_milestones(phase_id);
CREATE INDEX IF NOT EXISTS idx_timeline_milestones_status ON timeline_milestones(status);

-- Strategy Sprint workshop tracking
CREATE TABLE IF NOT EXISTS timeline_workshops (
    id SERIAL PRIMARY KEY,
    phase_id INTEGER NOT NULL REFERENCES timeline_phases(id) ON DELETE CASCADE,
    workshop_number INTEGER NOT NULL,
    scheduled_date DATE,
    actual_date DATE,
    meeting_id INTEGER REFERENCES meetings(id),
    status TEXT NOT NULL DEFAULT 'scheduled',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeline_workshops_phase ON timeline_workshops(phase_id);

-- Point-in-time health assessments
CREATE TABLE IF NOT EXISTS timeline_snapshots (
    id SERIAL PRIMARY KEY,
    timeline_id INTEGER NOT NULL REFERENCES timelines(id) ON DELETE CASCADE,
    snapshot_date TIMESTAMP NOT NULL DEFAULT NOW(),
    health TEXT NOT NULL,
    current_phase TEXT NOT NULL,
    summary TEXT NOT NULL,
    linear_stats JSONB,
    details JSONB,
    triggered_by TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeline_snapshots_timeline ON timeline_snapshots(timeline_id);
CREATE INDEX IF NOT EXISTS idx_timeline_snapshots_date ON timeline_snapshots(snapshot_date);

-- Maps Linear projects/milestones to timeline phases
CREATE TABLE IF NOT EXISTS timeline_linear_mappings (
    id SERIAL PRIMARY KEY,
    timeline_id INTEGER NOT NULL REFERENCES timelines(id) ON DELETE CASCADE,
    phase_id INTEGER REFERENCES timeline_phases(id) ON DELETE CASCADE,
    milestone_id INTEGER REFERENCES timeline_milestones(id) ON DELETE CASCADE,
    linear_project_id TEXT,
    linear_project_name TEXT,
    linear_milestone_id TEXT,
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT mapping_target CHECK (phase_id IS NOT NULL OR milestone_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_timeline_linear_mappings_timeline ON timeline_linear_mappings(timeline_id);
CREATE INDEX IF NOT EXISTS idx_timeline_linear_mappings_phase ON timeline_linear_mappings(phase_id);
CREATE INDEX IF NOT EXISTS idx_timeline_linear_mappings_milestone ON timeline_linear_mappings(milestone_id);
