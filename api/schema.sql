-- Phase 7: PostgreSQL Database Schema

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Projects Table
CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR(255) PRIMARY KEY,
    owner_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Provisioning',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP
);

-- Pagination and query indexes
CREATE INDEX IF NOT EXISTS idx_projects_owner_id ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC);

-- Deployments Table
CREATE TABLE IF NOT EXISTS deployments (
    deployment_id VARCHAR(255) PRIMARY KEY,
    project_id VARCHAR(255) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    repo_url TEXT NOT NULL,
    image_uri TEXT,
    replicas INT DEFAULT 1,
    port INT DEFAULT 8080,
    state VARCHAR(50) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_error TEXT
);

-- Pagination and query indexes
CREATE INDEX IF NOT EXISTS idx_deployments_project_id ON deployments(project_id);
CREATE INDEX IF NOT EXISTS idx_deployments_state ON deployments(state);
CREATE INDEX IF NOT EXISTS idx_deployments_updated_at ON deployments(updated_at DESC);

-- Builds Table
CREATE TABLE IF NOT EXISTS builds (
    build_id VARCHAR(255) PRIMARY KEY,
    deployment_id VARCHAR(255) NOT NULL REFERENCES deployments(deployment_id) ON DELETE CASCADE,
    s3_log_uri TEXT, -- Logs stored externally in S3
    status VARCHAR(50) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Pagination and query indexes
CREATE INDEX IF NOT EXISTS idx_builds_deployment_id ON builds(deployment_id);
CREATE INDEX IF NOT EXISTS idx_builds_status ON builds(status);
CREATE INDEX IF NOT EXISTS idx_builds_started_at ON builds(started_at DESC);

-- Phase 11: Audit Logs (Append-Only)
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(255) REFERENCES projects(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    details JSONB,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Deny updates or deletes on audit_logs to enforce append-only
-- In a real DB this would be enforced via triggers or IAM policies.

CREATE INDEX IF NOT EXISTS idx_audit_logs_project_id ON audit_logs(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
