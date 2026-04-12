import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Agent, AgentStat, DashboardEvent, EdgeStat, ModelStat } from "./types";
import { getAgents, getEventHistory, mapRegistryEventToDashboardEvent } from "./api";
import { useMeshEvents } from "./sse";

export interface MeshContextValue {
  agents: Agent[];
  events: DashboardEvent[];
  connected: boolean;
  loading: boolean;
  error: Error | null;
  sseError: Error | null;
  showAll: boolean;
  setShowAll: (show: boolean) => void;
  paused: boolean;
  setPaused: (paused: boolean) => void;
  refresh: () => Promise<void>;
  traceActivity: Record<string, number>;
  totalCalls: number;
  totalErrors: number;
  edgeStats: EdgeStat[];
  agentStats: AgentStat[];
  modelStats: ModelStat[];
}

const MeshContext = createContext<MeshContextValue | null>(null);

export function MeshProvider({ children }: { children: React.ReactNode }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<Error | null>(null);
  const [historyEvents, setHistoryEvents] = useState<DashboardEvent[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [paused, setPaused] = useState(false);
  const [traceActivity, setTraceActivity] = useState<Record<string, number>>({});
  const [totalCalls, setTotalCalls] = useState<number>(0);
  const [totalErrors, setTotalErrors] = useState<number>(0);
  const [edgeStats, setEdgeStats] = useState<EdgeStat[]>([]);
  const [agentStats, setAgentStats] = useState<AgentStat[]>([]);
  const [modelStats, setModelStats] = useState<ModelStat[]>([]);

  const fetchAgents = useCallback(async () => {
    try {
      const response = await getAgents(showAll ? undefined : "healthy");
      setAgents(response.agents || []);
      setFetchError(null);
    } catch (err) {
      setFetchError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [showAll]);

  // Debounced refetch: coalesce rapid SSE events into a single fetchAgents call
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // SSE subscription — refetch agents on structural changes (unless paused)
  const handleEvent = useCallback(
    (event: DashboardEvent) => {
      if (paused) return;

      // Handle trace updates (no agent refetch needed)
      if (event.type === "trace_activity") {
        const agents = event.data?.agents as Record<string, number> | undefined;
        if (agents) setTraceActivity(agents);
        const total = event.data?.total_calls as number | undefined;
        if (total !== undefined) setTotalCalls(total);
        const errors = event.data?.total_errors as number | undefined;
        if (errors !== undefined) setTotalErrors(errors);
        return;
      }
      if (event.type === "edge_stats") {
        const edges = event.data?.edges as EdgeStat[] | undefined;
        if (edges) setEdgeStats(edges);
        return;
      }
      if (event.type === "agent_stats") {
        const agents = event.data?.agents as AgentStat[] | undefined;
        if (agents) setAgentStats(agents);
        return;
      }
      if (event.type === "model_stats") {
        const models = event.data?.models as ModelStat[] | undefined;
        if (models) setModelStats(models);
        return;
      }

      const refetchEvents = [
        "agent_registered",
        "agent_deregistered",
        "agent_healthy",
        "agent_unhealthy",
        "dependency_resolved",
        "dependency_lost",
      ];
      if (refetchEvents.includes(event.type)) {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
          fetchAgents();
          debounceRef.current = null;
        }, 500);
      }
    },
    [fetchAgents, paused]
  );

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const { events, connected, error: sseError } = useMeshEvents({
    onEvent: handleEvent,
  });

  // Initial fetch
  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Periodic refresh as fallback (every 30s, unless paused)
  useEffect(() => {
    if (paused) return;
    const interval = setInterval(fetchAgents, 30000);
    return () => clearInterval(interval);
  }, [fetchAgents, paused]);

  // Fetch event history on mount
  useEffect(() => {
    getEventHistory(50)
      .then((resp) => {
        const mapped = resp.events
          .map(mapRegistryEventToDashboardEvent)
          .filter((e): e is DashboardEvent => e !== null);
        setHistoryEvents(mapped);
      })
      .catch(() => {
        // Silently fail — SSE backfill will cover it
      });
  }, []);

  // Combine SSE events with history, deduplicating by agent_id+type+timestamp
  const allEvents = useMemo(() => {
    if (events.length === 0) return historyEvents;
    const seen = new Set(events.map((e) => `${e.agent_id}-${e.type}-${e.timestamp}`));
    const uniqueHistory = historyEvents.filter(
      (e) => !seen.has(`${e.agent_id}-${e.type}-${e.timestamp}`)
    );
    return [...events, ...uniqueHistory].slice(0, 200);
  }, [events, historyEvents]);

  return (
    <MeshContext.Provider
      value={{
        agents,
        events: allEvents,
        connected,
        loading,
        error: fetchError,
        sseError,
        showAll,
        setShowAll,
        paused,
        setPaused,
        refresh: fetchAgents,
        traceActivity,
        totalCalls,
        totalErrors,
        edgeStats,
        agentStats,
        modelStats,
      }}
    >
      {children}
    </MeshContext.Provider>
  );
}

export function useMesh(): MeshContextValue {
  const ctx = useContext(MeshContext);
  if (!ctx) {
    throw new Error("useMesh must be used within a MeshProvider");
  }
  return ctx;
}
