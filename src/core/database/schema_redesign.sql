-- MCP Mesh Registry Database Schema Redesign
-- Supports: One Agent = Multiple Tools

-- 1. AGENTS table (minimal changes)
-- Represents a process/container with multiple functions
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,                    -- agent-uuid format
    name TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'default',
    endpoint TEXT NOT NULL,                 -- Base endpoint (may be updated when HTTP starts)
    status TEXT NOT NULL DEFAULT 'pending',
    labels TEXT DEFAULT '{}',               -- JSON: agent-level tags
    annotations TEXT DEFAULT '{}',          -- JSON: agent metadata
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    resource_version TEXT NOT NULL,
    last_heartbeat TIMESTAMP,
    health_interval INTEGER DEFAULT 30,
    timeout_threshold INTEGER DEFAULT 60,
    eviction_threshold INTEGER DEFAULT 120,
    agent_type TEXT DEFAULT 'mesh-agent',
    config TEXT DEFAULT '{}',               -- JSON: agent configuration
    security_context TEXT,
    dependencies TEXT DEFAULT '[]'          -- DEPRECATED: Move to tools level
);

-- 2. TOOLS table (NEW)
-- Represents individual functions within an agent
CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,                -- Function name (e.g., 'greet')
    capability TEXT NOT NULL,               -- What it provides
    version TEXT DEFAULT '1.0.0',
    description TEXT,

    -- Discovery
    tags TEXT DEFAULT '[]',                 -- JSON array
    endpoint TEXT,                          -- Tool-specific endpoint (if different from agent)
    transport TEXT DEFAULT '["stdio"]',     -- JSON array: ["stdio", "http"]

    -- Dependencies with constraints
    dependencies TEXT DEFAULT '[]',         -- JSON: [{"capability": "x", "version": ">=1.0", "tags": ["prod"]}]

    -- Service configuration
    health_interval INTEGER DEFAULT 30,
    timeout INTEGER DEFAULT 30,
    retry_attempts INTEGER DEFAULT 3,
    enable_caching BOOLEAN DEFAULT TRUE,
    fallback_mode BOOLEAN DEFAULT TRUE,

    -- HTTP configuration
    enable_http BOOLEAN DEFAULT FALSE,
    http_host TEXT DEFAULT '0.0.0.0',
    http_port INTEGER DEFAULT 0,

    -- Performance & Security
    security_context TEXT,
    performance_profile TEXT DEFAULT '{}',   -- JSON
    resource_requirements TEXT DEFAULT '{}', -- JSON

    -- MCP metadata
    parameters_schema TEXT,                  -- JSON: MCP function parameters

    -- Additional metadata
    metadata TEXT DEFAULT '{}',              -- JSON: All other fields

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    UNIQUE(agent_id, tool_name)             -- No duplicate tool names per agent
);

-- 3. CAPABILITIES view (for backward compatibility)
-- Makes new schema look like old schema for existing queries
CREATE VIEW IF NOT EXISTS capabilities AS
SELECT
    t.id,
    t.agent_id,
    t.capability as name,
    t.description,
    t.version,
    t.parameters_schema,
    t.security_context as security_requirements,
    t.created_at,
    t.updated_at
FROM tools t;

-- 4. TOOL_HEALTH table (NEW)
-- Track health per tool (optional, for fine-grained monitoring)
CREATE TABLE IF NOT EXISTS tool_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'healthy',
    last_invocation TIMESTAMP,
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    avg_response_time_ms REAL,
    metadata TEXT DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    UNIQUE(agent_id, tool_name)
);

-- 5. Indexes for performance
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_namespace ON agents(namespace);
CREATE INDEX IF NOT EXISTS idx_agents_last_heartbeat ON agents(last_heartbeat);

CREATE INDEX IF NOT EXISTS idx_tools_agent_id ON tools(agent_id);
CREATE INDEX IF NOT EXISTS idx_tools_capability ON tools(capability);
CREATE INDEX IF NOT EXISTS idx_tools_capability_version ON tools(capability, version);
CREATE INDEX IF NOT EXISTS idx_tools_tags ON tools(tags);  -- JSON index

CREATE INDEX IF NOT EXISTS idx_agent_health_agent_id ON agent_health(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_health_timestamp ON agent_health(timestamp);

-- 6. Migration helpers
-- Convert old single-capability agents to new format
-- This would be run during migration
/*
INSERT INTO tools (agent_id, tool_name, capability, version, description, ...)
SELECT
    a.id as agent_id,
    c.name as tool_name,  -- Use capability name as tool name for old data
    c.name as capability,
    c.version,
    c.description,
    ...
FROM agents a
JOIN capabilities c ON a.id = c.agent_id
WHERE NOT EXISTS (
    SELECT 1 FROM tools t WHERE t.agent_id = a.id
);
*/
