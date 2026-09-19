-- Phase 8 PostgreSQL Durable Persistence Schema
-- Supports crash-safe checkpoints, interrupts, approvals, concurrency locking, and audit trails.

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id VARCHAR(128) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    lifecycle VARCHAR(64) NOT NULL,
    goal TEXT NOT NULL,
    portal VARCHAR(256) DEFAULT '',
    current_subgoal_id VARCHAR(128) DEFAULT '',
    state_version INT NOT NULL DEFAULT 0,
    total_iterations INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    checkpoint_id VARCHAR(128) PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    format_version INT NOT NULL DEFAULT 2,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    reason VARCHAR(256) NOT NULL,
    lifecycle VARCHAR(64) NOT NULL,
    state_version INT NOT NULL DEFAULT 0,
    state_payload JSONB NOT NULL,
    events_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    recovery_cursor INT NOT NULL DEFAULT 0,
    is_latest BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS human_interrupts (
    interrupt_id VARCHAR(128) PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    checkpoint_id VARCHAR(128) REFERENCES agent_checkpoints(checkpoint_id) ON DELETE SET NULL,
    reason VARCHAR(64) NOT NULL,
    status VARCHAR(64) NOT NULL,
    description TEXT NOT NULL,
    observation_id VARCHAR(128) NOT NULL,
    world_state_version INT NOT NULL,
    subgoal_id VARCHAR(128),
    required_action VARCHAR(128),
    target_identity VARCHAR(256),
    semantic_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS approval_bindings (
    approval_id VARCHAR(128) PRIMARY KEY,
    interrupt_id VARCHAR(128) NOT NULL REFERENCES human_interrupts(interrupt_id) ON DELETE CASCADE,
    run_id VARCHAR(128) NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    requested_action VARCHAR(128) NOT NULL,
    target_identity VARCHAR(256) NOT NULL,
    semantic_id VARCHAR(128),
    world_state_version INT NOT NULL,
    observation_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    approved_by VARCHAR(128) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS resume_locks (
    run_id VARCHAR(128) PRIMARY KEY REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    worker_id VARCHAR(128) NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    fencing_token BIGINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS hitl_audit_events (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for performance and query patterns
CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id ON agent_checkpoints(run_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_latest ON agent_checkpoints(run_id, is_latest);
CREATE INDEX IF NOT EXISTS idx_checkpoints_expires_at ON agent_checkpoints(expires_at);

CREATE INDEX IF NOT EXISTS idx_interrupts_run_id ON human_interrupts(run_id);
CREATE INDEX IF NOT EXISTS idx_interrupts_status ON human_interrupts(status);
CREATE INDEX IF NOT EXISTS idx_interrupts_expires_at ON human_interrupts(expires_at);

CREATE INDEX IF NOT EXISTS idx_approvals_interrupt_id ON approval_bindings(interrupt_id);
CREATE INDEX IF NOT EXISTS idx_approvals_run_id ON approval_bindings(run_id);

CREATE INDEX IF NOT EXISTS idx_resume_locks_expires ON resume_locks(expires_at);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON hitl_audit_events(run_id, timestamp);
