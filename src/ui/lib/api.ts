import { AgentsResponse, DashboardEvent, EdgeStatsResponse, EventsHistoryResponse, HealthResponse, RecentTracesResponse, RegistryEventInfo, TraceDetail } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_REGISTRY_URL || "/api";

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function getAgents(status?: string): Promise<AgentsResponse> {
  let url = `${API_BASE}/agents`;
  if (status) {
    const params = new URLSearchParams({ status });
    url += `?${params.toString()}`;
  }
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch agents: ${res.status}`);
  return res.json();
}

export async function getEventHistory(limit: number = 50): Promise<EventsHistoryResponse> {
  const res = await fetch(`${API_BASE}/events/history?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch event history: ${res.status}`);
  return res.json();
}

export function mapRegistryEventToDashboardEvent(event: RegistryEventInfo): DashboardEvent | null {
  const typeMap: Record<string, DashboardEvent["type"]> = {
    register: "agent_registered",
    unregister: "agent_deregistered",
    unhealthy: "agent_unhealthy",
  };

  // For "update" events, check if it's a recovery to healthy
  if (event.event_type === "update") {
    const data = event.data as Record<string, string> | undefined;
    if (data?.new_status === "healthy") {
      return {
        type: "agent_healthy",
        agent_id: event.agent_id,
        agent_name: event.agent_name,
        timestamp: event.timestamp,
        data: event.data,
      };
    }
    return null; // Skip generic updates
  }

  const mappedType = typeMap[event.event_type];
  if (!mappedType) return null; // Skip expire, rotate, etc.

  return {
    type: mappedType,
    agent_id: event.agent_id,
    agent_name: event.agent_name,
    timestamp: event.timestamp,
    data: event.data,
  };
}

export function formatRelativeTime(dateString: string | null | undefined): string {
  if (!dateString) return "Unknown";
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return "Unknown";
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  if (diffMs < 0) return "0s ago";
  const diffSeconds = Math.floor(diffMs / 1000);
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  if (ms < 1) {
    return `${Math.round(ms * 1000)}µs`;
  }
  return `${Math.round(ms)}ms`;
}

export function getStatusColor(status: string): string {
  switch (status) {
    case "healthy": return "text-green-500";
    case "unhealthy": return "text-red-500";
    case "unknown": return "text-yellow-500";
    default: return "text-muted-foreground";
  }
}

export function getStatusBgColor(status: string): string {
  switch (status) {
    case "healthy": return "bg-green-500";
    case "unhealthy": return "bg-red-500";
    case "unknown": return "bg-yellow-500";
    default: return "bg-muted";
  }
}

export function getRuntimeLabel(runtime?: string): string {
  switch (runtime) {
    case "python": return "Python";
    case "typescript": return "TypeScript";
    case "java": return "Java";
    default: return runtime || "Unknown";
  }
}

export function getAgentTypeLabel(type: string): string {
  switch (type) {
    case "mcp_agent": return "MCP Agent";
    case "mesh_tool": return "Mesh Tool";
    case "decorator_agent": return "Decorator";
    case "api": return "API";
    default: return type;
  }
}

export function getDepStatusColor(status: string): string {
  switch (status) {
    case "available": return "text-green-500";
    case "unavailable": return "text-red-500";
    case "unresolved": return "text-yellow-500";
    default: return "text-muted-foreground";
  }
}

export async function getRecentTraces(limit: number = 20): Promise<RecentTracesResponse> {
  const res = await fetch(`${API_BASE}/trace/recent?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch recent traces: ${res.status}`);
  return res.json();
}

export async function getTraceDetail(traceId: string): Promise<TraceDetail> {
  const res = await fetch(`${API_BASE}/trace/${traceId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch trace: ${res.status}`);
  return res.json();
}

export async function getEdgeStats(limit: number = 20): Promise<EdgeStatsResponse> {
  const res = await fetch(`${API_BASE}/trace/edge-stats?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch edge stats: ${res.status}`);
  return res.json();
}

export function extractAgentName(agentId: string): string {
  // Agent IDs are formatted as "{name}-{8char_hex_uuid}"
  // E.g., "digest-agent-b1a5da10" -> "digest-agent"
  const parts = agentId.split("-");
  if (parts.length >= 2) {
    return parts.slice(0, -1).join("-");
  }
  return agentId;
}

export { API_BASE };
