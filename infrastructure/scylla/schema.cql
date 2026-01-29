-- Facto ScyllaDB Schema
-- This schema defines the storage layer for the Facto forensic accountability system

CREATE KEYSPACE IF NOT EXISTS facto
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE facto;

-- Main events table (partitioned by agent+date for even distribution)
-- This is the primary storage for all facto events
CREATE TABLE IF NOT EXISTS events (
    agent_id text,
    date date,
    facto_id text,
    session_id text,
    parent_facto_id text,
    action_type text,
    status text,
    input_data blob,
    output_data blob,
    model_id text,
    model_hash text,
    temperature float,
    seed bigint,
    max_tokens int,
    tool_calls text,
    sdk_version text,
    sdk_language text,
    tags map<text, text>,
    signature blob,
    public_key blob,
    prev_hash text,
    event_hash text,
    started_at timestamp,
    completed_at timestamp,
    received_at timestamp,
    PRIMARY KEY ((agent_id, date), completed_at, facto_id)
) WITH CLUSTERING ORDER BY (completed_at DESC, facto_id ASC)
  AND compaction = {'class': 'TimeWindowCompactionStrategy',
                    'compaction_window_unit': 'HOURS',
                    'compaction_window_size': 1};

-- Lookup by facto_id (for direct event retrieval)
CREATE TABLE IF NOT EXISTS events_by_facto_id (
    facto_id text PRIMARY KEY,
    agent_id text,
    date date,
    completed_at timestamp,
    session_id text,
    action_type text,
    status text,
    input_data blob,
    output_data blob,
    model_id text,
    model_hash text,
    temperature float,
    seed bigint,
    max_tokens int,
    tool_calls text,
    sdk_version text,
    sdk_language text,
    tags map<text, text>,
    signature blob,
    public_key blob,
    prev_hash text,
    event_hash text,
    parent_facto_id text,
    started_at timestamp,
    received_at timestamp
);

-- Lookup by session (for retrieving all events in a session)
CREATE TABLE IF NOT EXISTS events_by_session (
    session_id text,
    completed_at timestamp,
    facto_id text,
    agent_id text,
    action_type text,
    status text,
    event_hash text,
    input_data blob,
    output_data blob,
    model_id text,
    temperature float,
    sdk_version text,
    sdk_language text,
    tags map<text, text>,
    signature blob,
    public_key blob,
    prev_hash text,
    parent_facto_id text,
    started_at timestamp,
    received_at timestamp,
    PRIMARY KEY (session_id, completed_at, facto_id)
) WITH CLUSTERING ORDER BY (completed_at ASC, facto_id ASC);

-- Merkle roots for batch anchoring and verification
CREATE TABLE IF NOT EXISTS merkle_roots (
    date date,
    bucket_time timestamp,
    root_hash text,
    event_count int,
    first_facto_id text,
    last_facto_id text,
    event_hashes list<text>,
    created_at timestamp,
    PRIMARY KEY (date, bucket_time)
) WITH CLUSTERING ORDER BY (bucket_time DESC);

-- Chain state tracking (for maintaining prev_hash linkage per agent)
CREATE TABLE IF NOT EXISTS chain_state (
    agent_id text PRIMARY KEY,
    last_event_hash text,
    last_facto_id text,
    event_count bigint,
    updated_at timestamp
);

-- Agent registry (for tracking registered agents and their public keys)
CREATE TABLE IF NOT EXISTS agents (
    agent_id text PRIMARY KEY,
    public_key blob,
    name text,
    description text,
    tags map<text, text>,
    created_at timestamp,
    updated_at timestamp,
    event_count bigint,
    last_event_at timestamp
);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS events_by_action_type ON events (action_type);
CREATE INDEX IF NOT EXISTS events_by_status ON events (status);
