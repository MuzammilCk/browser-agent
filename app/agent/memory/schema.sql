-- Phase 9 PostgreSQL Memory Persistence Schema
-- Supports structured persistence for Semantic, Episodic, Experience memory and Compaction records.

CREATE TABLE IF NOT EXISTS semantic_memories (
    memory_id VARCHAR(128) PRIMARY KEY,
    subject VARCHAR(256) NOT NULL,
    predicate VARCHAR(256) NOT NULL,
    value_json JSONB NOT NULL,
    portal VARCHAR(256) DEFAULT '',
    user_session_id VARCHAR(128) DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    epistemic_status VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    superseded_by VARCHAR(128),
    provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_provenance (
    id BIGSERIAL PRIMARY KEY,
    memory_id VARCHAR(128) NOT NULL REFERENCES semantic_memories(memory_id) ON DELETE CASCADE,
    source VARCHAR(128) NOT NULL,
    author_type VARCHAR(64) NOT NULL,
    run_id VARCHAR(128) DEFAULT '',
    observation_id VARCHAR(128) DEFAULT '',
    tool_name VARCHAR(128) DEFAULT '',
    state_version INT NOT NULL DEFAULT 0,
    timestamp TIMESTAMPTZ NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id VARCHAR(128) PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    portal VARCHAR(256) DEFAULT '',
    goal TEXT NOT NULL,
    subgoal VARCHAR(256) DEFAULT '',
    summary TEXT NOT NULL,
    key_events JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome VARCHAR(64) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS experiences (
    experience_id VARCHAR(128) PRIMARY KEY,
    run_id VARCHAR(128) DEFAULT '',
    portal VARCHAR(256) DEFAULT '',
    task_type VARCHAR(128) DEFAULT '',
    trigger_condition TEXT NOT NULL,
    recovery_strategy TEXT NOT NULL,
    context_features JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome VARCHAR(64) NOT NULL,
    success_count INT NOT NULL DEFAULT 1,
    failure_count INT NOT NULL DEFAULT 0,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS compaction_records (
    compaction_id VARCHAR(128) PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    pre_items_count INT NOT NULL,
    post_items_count INT NOT NULL,
    preserved_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    compacted_summary TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Indexes for deterministic property-based retrieval and filtering
CREATE INDEX IF NOT EXISTS idx_semantic_subject_pred ON semantic_memories(subject, predicate, is_current);
CREATE INDEX IF NOT EXISTS idx_semantic_portal ON semantic_memories(portal);
CREATE INDEX IF NOT EXISTS idx_semantic_user_session ON semantic_memories(user_session_id);
CREATE INDEX IF NOT EXISTS idx_semantic_status ON semantic_memories(epistemic_status);
CREATE INDEX IF NOT EXISTS idx_semantic_current ON semantic_memories(is_current);

CREATE INDEX IF NOT EXISTS idx_episodes_portal ON episodes(portal);
CREATE INDEX IF NOT EXISTS idx_episodes_run ON episodes(run_id);
CREATE INDEX IF NOT EXISTS idx_episodes_created_at ON episodes(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_experiences_portal_task ON experiences(portal, task_type);
CREATE INDEX IF NOT EXISTS idx_experiences_confidence ON experiences(confidence DESC);

CREATE INDEX IF NOT EXISTS idx_compaction_run_id ON compaction_records(run_id);
