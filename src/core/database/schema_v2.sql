-- MCP Mesh Registry Database Schema V2
-- Clean separation: Agents metadata + Capabilities table

-- 1. AGENTS table - Pure agent metadata
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,                 -- "multi-service-agent"
    agent_type TEXT NOT NULL DEFAULT 'mcp_agent',
    name TEXT NOT NULL,                        -- "Multi-Service Agent"
    version TEXT,                              -- "2.1.0"
    http_host TEXT,                            -- "0.0.0.0"
    http_port INTEGER,                         -- 8080
    namespace TEXT DEFAULT 'default',          -- "production"

    -- Dependency tracking (computed fields)
    total_dependencies INTEGER DEFAULT 0,      -- Total deps across all tools
    dependencies_resolved INTEGER DEFAULT 0,   -- How many are resolved

    -- Registry-controlled timestamps (source of truth)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. CAPABILITIES table - What each agent provides
CREATE TABLE IF NOT EXISTS capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    function_name TEXT NOT NULL,               -- "smart_greet", "get_weather_report"
    capability TEXT NOT NULL,                  -- "personalized_greeting", "weather_report"
    version TEXT DEFAULT '1.0.0',
    description TEXT,
    tags TEXT DEFAULT '[]',                    -- JSON array: ["prod", "ml", "gpu"]

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE,
    UNIQUE(agent_id, function_name)
);

-- 3. REGISTRY_EVENTS table - Audit trail (unchanged)
CREATE TABLE IF NOT EXISTS registry_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,                  -- 'register', 'heartbeat', 'expire'
    agent_id TEXT NOT NULL,
    function_name TEXT,                        -- NULL for agent-level events
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data TEXT DEFAULT '{}'                     -- JSON event data
);

-- 4. Performance indexes
CREATE INDEX IF NOT EXISTS idx_agents_namespace ON agents(namespace);
CREATE INDEX IF NOT EXISTS idx_agents_type ON agents(agent_type);
CREATE INDEX IF NOT EXISTS idx_agents_updated_at ON agents(updated_at);

CREATE INDEX IF NOT EXISTS idx_capabilities_capability ON capabilities(capability);
CREATE INDEX IF NOT EXISTS idx_capabilities_agent ON capabilities(agent_id);
CREATE INDEX IF NOT EXISTS idx_capabilities_function ON capabilities(function_name);

CREATE INDEX IF NOT EXISTS idx_events_agent ON registry_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON registry_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type ON registry_events(event_type);
