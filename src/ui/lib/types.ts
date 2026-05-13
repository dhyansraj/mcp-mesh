export interface Agent {
  id: string;
  name: string;
  agent_type: "mcp_agent" | "mesh_tool" | "decorator_agent" | "api" | "a2a";
  runtime?: "python" | "typescript" | "java";
  version?: string;
  /**
   * Free-form agent description (issue #969). Optional + may be empty when
   * the agent never set `@mesh.agent(description=...)` (or equivalent in
   * Java/TypeScript). The detail header renders a placeholder in that case.
   */
  description?: string;
  /**
   * Issue #972: true if this agent registers at least one A2A producer
   * surface (@mesh.a2a / @MeshA2A / mesh.a2a.mount). Defaults to false on
   * the registry when absent. Type-only addition here — UI rendering /
   * badges land in #970.
   */
  a2a_producer?: boolean;
  /**
   * Issue #972: true if this agent registers at least one A2A consumer
   * surface (@mesh.a2a_consumer / @A2AConsumer / a2aConfig). Defaults to
   * false on the registry when absent. Type-only addition here — UI
   * rendering / badges land in #970.
   */
  a2a_consumer?: boolean;
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
  event_type:
    | "register"
    | "unregister"
    | "unhealthy"
    | "update"
    | "expire"
    | "rotate"
    | "dependency_resolved"
    | "dependency_unresolved";
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

/**
 * Issue #973: MeshJob observability types. Mirrors the Job + JobsListResponse
 * schemas in api/mcp-mesh-registry.openapi.yaml — time fields are UNIX-epoch
 * seconds (integers), not ISO strings.
 *
 * NOTE: status values must come from the registry's `job.Status` enum.
 * "unclaimed" is NOT a real status — it's derived in the UI by checking
 * `owner_instance_id === null` on `status === "working"` rows.
 */
export type JobStatus =
  | "working"
  | "input_required"
  | "completed"
  | "failed"
  | "cancelled";

export interface Job {
  id: string;
  capability: string;
  owner_instance_id: string | null;
  status: JobStatus;
  progress: number | null;
  progress_message: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  submitted_payload: Record<string, unknown>;
  attempt_count: number;
  max_retries: number;
  max_duration: number | null;
  total_deadline: number | null;
  lease_expires_at: number | null;
  last_heartbeat_at: number | null;
  submitted_at: number;
  submitted_by: string;
}

export interface JobsResponse {
  jobs: Job[];
  next_cursor: string | null;
}

/**
 * Issue #971: Schema Registry Browser types. Backed by the meshui server's
 * /api/schemas and /api/schemas/{hash}/usage endpoints. The shape mirrors
 * src/core/ui/schemas_handler.go — keep them in sync.
 *
 * Note: providers/consumers are always arrays (never null) even when empty,
 * so the SPA can render empty-state rows without nil guards.
 */
export interface SchemaListItem {
  hash: string;
  runtime_origin: string;
  created_at: string;
  provider_count: number;
  consumer_count: number;
  /** First provider's function_name, or null when no providers exist. */
  sample_function: string | null;
  /**
   * Distinct provider agent names (sorted, deduped). Always a non-null array
   * so the client-side filter can include agent-name matches without a guard.
   */
  provider_agent_names: string[];
}

export interface SchemasResponse {
  schemas: SchemaListItem[];
  count: number;
}

export interface SchemaProvider {
  agent_id: string;
  agent_name: string;
  /**
   * Owning agent's SDK runtime (python/typescript/java, or "" for older rows
   * predating the field). Denormalized server-side so the cross-runtime
   * banner on the schema detail page can compute distinct runtimes without
   * a second round-trip.
   */
  runtime: string;
  function_name: string;
  capability: string;
  /** Whether this capability declares the hash on its input or output side. */
  role: "input" | "output";
}

export interface SchemaConsumer {
  agent_id: string;
  agent_name: string;
  /** Owning agent's SDK runtime — see SchemaProvider.runtime. */
  runtime: string;
  function_name: string;
  capability: string;
  /** Always "dependency" in v1 — declarative consumers only. */
  via: "dependency";
  /** The dependency entry's `capability` value (what the consumer asked for). */
  depends_on_capability: string;
}

export interface SchemaUsage {
  schema: {
    hash: string;
    canonical: unknown;
    runtime_origin: string;
    created_at: string;
  };
  providers: SchemaProvider[];
  consumers: SchemaConsumer[];
}

export interface JobsQuery {
  /**
   * Comma-separated JobStatus values. Empty / undefined ⇒ all statuses.
   * The API layer wires this directly into the `status` query param so
   * callers can pass either "working" or "working,input_required".
   */
  status?: string;
  owner_instance_id?: string;
  capability?: string;
  /** Unix epoch seconds; inclusive lower bound on submitted_at. */
  submitted_since?: number;
  /** Bounded server-side at [1, 200]; default 50. */
  limit?: number;
  /** Opaque cursor from a previous response's next_cursor. */
  cursor?: string;
}
