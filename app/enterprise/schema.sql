-- Phase 13 Enterprise Runtime Schema
-- Extends the existing Phase 8 persistence schema (same PostgreSQL database).
-- Reuses (unchanged): agent_runs, agent_checkpoints, human_interrupts,
-- approval_bindings, resume_locks, hitl_audit_events.

CREATE TABLE IF NOT EXISTS workflows (
    workflow_id VARCHAR(128) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'active',
    current_run_id VARCHAR(128),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id VARCHAR(128) PRIMARY KEY,
    workflow_id VARCHAR(128) NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    tenant_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'queued',
    worker_id VARCHAR(128),
    lease_id VARCHAR(128),
    fencing_token BIGINT NOT NULL DEFAULT 0,
    checkpoint_id VARCHAR(128),
    agent_run_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
    failure_code VARCHAR(128),
    dispatch_attempts INT NOT NULL DEFAULT 0,
    max_dispatch_attempts INT NOT NULL DEFAULT 3,
    version INT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS worker_leases (
    run_id VARCHAR(128) PRIMARY KEY,
    worker_id VARCHAR(128) NOT NULL,
    lease_id VARCHAR(128) NOT NULL,
    fencing_token BIGINT NOT NULL DEFAULT 1,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    renewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    state VARCHAR(32) NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS execution_queue (
    queue_id VARCHAR(128) PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL UNIQUE REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    workflow_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'queued',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_by VARCHAR(128),
    claim_expires_at TIMESTAMPTZ,
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id VARCHAR(128) PRIMARY KEY,
    parent_event_id VARCHAR(128),
    tenant_id VARCHAR(128) NOT NULL DEFAULT '',
    user_id VARCHAR(128) NOT NULL DEFAULT '',
    workflow_id VARCHAR(128),
    run_id VARCHAR(128),
    worker_id VARCHAR(128),
    event_type VARCHAR(128) NOT NULL,
    actor_type VARCHAR(64) NOT NULL DEFAULT 'system',
    actor_id VARCHAR(128) NOT NULL DEFAULT '',
    action VARCHAR(128),
    policy_result VARCHAR(64),
    hitl_result VARCHAR(64),
    security_event VARCHAR(128),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key VARCHAR(256) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    operation VARCHAR(64) NOT NULL,
    request_hash VARCHAR(128) NOT NULL,
    status_code INT NOT NULL DEFAULT 200,
    response JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (key, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_workflows_tenant ON workflows(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_workflow ON workflow_runs(workflow_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_tenant ON workflow_runs(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_runs_status ON workflow_runs(status);
CREATE INDEX IF NOT EXISTS idx_leases_expires ON worker_leases(expires_at);
CREATE INDEX IF NOT EXISTS idx_queue_state ON execution_queue(state, available_at);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_events(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id, created_at);
