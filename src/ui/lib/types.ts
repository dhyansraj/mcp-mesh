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
    | "snapshot"
    | "trace_activity"
    | "edge_stats"
    | "agent_stats"
    | "model_stats";
  agent_id?: string;
  agent_name?: string;
  runtime?: string;
  status?: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

export interface RecentTrace {
  trace_id: string;
  root_agent: string;
  root_operation: string;
  duration_ms: number;
  start_time: string;
  span_count: number;
  agent_count: number;
  success: boolean;
  agents: string[];
}

export interface RecentTracesResponse {
  enabled: boolean;
  traces: RecentTrace[];
  count: number;
  limit: number;
}

export interface TraceSpan {
  SpanID: string;
  ParentSpan: string | null;
  AgentName: string;
  Operation: string;
  DurationMS: number | null;
  Success: boolean | null;
  ErrorMessage: string | null;
}

export interface TraceDetail {
  TraceID: string;
  Spans: TraceSpan[];
  Success: boolean;
  SpanCount: number;
  AgentCount: number;
  Agents: string[];
}

export interface EdgeStat {
  source: string;
  target: string;
  call_count: number;
  error_count: number;
  error_rate: number;
  avg_latency_ms: number;
  p99_latency_ms: number;
  max_latency_ms: number;
  min_latency_ms: number;
}

export interface AgentStat {
  agent_name: string;
  span_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_request_bytes: number;
  total_response_bytes: number;
}

export interface ModelStat {
  model: string;
  provider: string;
  call_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface EdgeStatsResponse {
  enabled: boolean;
  edges: EdgeStat[];
  count: number;
  edge_count: number;
}
