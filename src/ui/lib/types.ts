export interface Agent {
  id: string;
  name: string;
  agent_type: "mcp_agent" | "mesh_tool" | "decorator_agent" | "api";
  runtime?: "python" | "typescript" | "java";
  version?: string;
  status: "healthy" | "unhealthy" | "unknown";
  endpoint: string;
  entity_id?: string;
  created_at?: string;
  last_seen?: string;
  total_dependencies: number;
  dependencies_resolved: number;
  capabilities: Capability[];
  dependency_resolutions?: DependencyResolution[];
  llm_tool_resolutions?: LLMToolResolution[];
  llm_provider_resolutions?: LLMProviderResolution[];
}

export interface Capability {
  function_name: string;
  name: string;
  version: string;
  description?: string;
  tags?: string[];
  llm_filter?: LLMToolFilter;
  llm_provider?: LLMProvider;
}

export interface DependencyResolution {
  function_name: string;
  capability: string;
  status: "available" | "unavailable" | "unresolved";
  tags?: string[];
  provider_agent_id?: string;
  mcp_tool?: string;
  endpoint?: string;
}

export interface LLMToolResolution {
  function_name: string;
  filter_capability: string;
  filter_tags?: string[];
  filter_mode?: string;
  status: "available" | "unavailable" | "unresolved";
  provider_agent_id?: string;
  provider_function_name?: string;
  provider_capability?: string;
  endpoint?: string;
}

export interface LLMProviderResolution {
  function_name: string;
  required_capability: string;
  required_tags?: string[];
  status: "available" | "unavailable" | "unresolved";
  provider_agent_id?: string;
  provider_function_name?: string;
  endpoint?: string;
}

export interface LLMToolFilter {
  capability?: string;
  tags?: string[];
  mode?: string;
}

export interface LLMProvider {
  capability?: string;
  tags?: string[];
  version?: string;
  namespace?: string;
}

export interface AgentsResponse {
  agents: Agent[];
  count: number;
  timestamp: string;
}

export interface RegistryEventInfo {
  event_type: "register" | "unregister" | "unhealthy" | "update" | "expire" | "rotate";
  agent_id: string;
  agent_name?: string;
  function_name?: string;
  timestamp: string;
  data?: Record<string, unknown>;
}

export interface EventsHistoryResponse {
  events: RegistryEventInfo[];
  count: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  uptime_seconds: number;
  timestamp: string;
  service: string;
}

export interface DashboardEvent {
  type:
    | "agent_registered"
    | "agent_deregistered"
    | "agent_healthy"
    | "agent_unhealthy"
    | "dependency_resolved"
    | "dependency_lost"
    | "connected"
    | "snapshot";
  agent_id?: string;
  agent_name?: string;
  runtime?: string;
  status?: string;
  data?: Record<string, unknown>;
  timestamp: string;
}
