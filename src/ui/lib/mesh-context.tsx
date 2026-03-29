"use client";

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
import { Agent, DashboardEvent } from "./types";
import { getAgents, getEventHistory, mapRegistryEventToDashboardEvent } from "./api";
import { useMeshEvents } from "./sse";

export interface MeshContextValue {
  agents: Agent[];
  events: DashboardEvent[];
  connected: boolean;
  loading: boolean;
  error: Error | null;
  showAll: boolean;
  setShowAll: (show: boolean) => void;
  paused: boolean;
  setPaused: (paused: boolean) => void;
  refresh: () => Promise<void>;
}

const MeshContext = createContext<MeshContextValue | null>(null);

export function MeshProvider({ children }: { children: React.ReactNode }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<Error | null>(null);
  const [historyEvents, setHistoryEvents] = useState<DashboardEvent[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [paused, setPaused] = useState(false);

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

  // SSE subscription — refetch agents on structural changes (unless paused)
  const handleEvent = useCallback(
    (event: DashboardEvent) => {
      if (paused) return;
      const refetchEvents = [
        "agent_registered",
        "agent_deregistered",
        "agent_healthy",
        "agent_unhealthy",
        "dependency_resolved",
        "dependency_lost",
      ];
      if (refetchEvents.includes(event.type)) {
        fetchAgents();
      }
    },
    [fetchAgents, paused]
  );

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
        error: fetchError || sseError,
        showAll,
        setShowAll,
        paused,
        setPaused,
        refresh: fetchAgents,
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
