-- MCP Mesh Registry Database Schema (Clean Redesign)
-- No backward compatibility needed!

-- 1. AGENTS table
-- Represents a process/container with multiple tools
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,                    -- Format: "name-uuid"
    name TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'default',
    base_endpoint TEXT NOT NULL,            -- Base endpoint (stdio:// or http://)
    status TEXT NOT NULL DEFAULT 'healthy',
    transport TEXT DEFAULT '["stdio"]',     -- JSON array: ["stdio", "http"]

    -- Health monitoring
    last_heartbeat TIMESTAMP,
    timeout_threshold INTEGER DEFAULT 60,
    eviction_threshold INTEGER DEFAULT 120,

    -- Metadata
    labels TEXT DEFAULT '{}',               -- JSON: {"env": "prod", "region": "us-east"}
    metadata TEXT DEFAULT '{}',             -- JSON: Any additional fields

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. TOOLS table
-- Individual functions within an agent
CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    name TEXT NOT NULL,                     -- Function name
    capability TEXT NOT NULL,               -- Service it provides
    version TEXT DEFAULT '1.0.0',

    -- Dependencies with rich constraints
    dependencies TEXT DEFAULT '[]',         -- JSON: [{"capability": "x", "version": ">=1.0", "tags": ["prod"]}]

    -- Configuration
    config TEXT DEFAULT '{}',               -- JSON: All tool-specific config

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    UNIQUE(agent_id, name)
);

-- 3. REGISTRY_EVENTS table
-- Audit trail for all changes
CREATE TABLE IF NOT EXISTS registry_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,               -- 'register', 'heartbeat', 'expire'
    agent_id TEXT NOT NULL,
    tool_name TEXT,                         -- NULL for agent-level events
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data TEXT DEFAULT '{}'                  -- JSON event data
);

-- 4. Indexes for performance
CREATE INDEX idx_agents_status ON agents(status);
CREATE INDEX idx_agents_heartbeat ON agents(last_heartbeat);
CREATE INDEX idx_tools_capability ON tools(capability);
CREATE INDEX idx_tools_agent ON tools(agent_id);
CREATE INDEX idx_events_agent ON registry_events(agent_id);
CREATE INDEX idx_events_timestamp ON registry_events(timestamp);
