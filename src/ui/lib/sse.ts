"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { DashboardEvent } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_REGISTRY_URL || `${process.env.NEXT_PUBLIC_UI_BASE_PATH || ""}/api`;

export interface UseMeshEventsOptions {
  maxEvents?: number;
  onEvent?: (event: DashboardEvent) => void;
}

export interface UseMeshEventsResult {
  events: DashboardEvent[];
  connected: boolean;
  error: Error | null;
  clearEvents: () => void;
}

export function useMeshEvents(options: UseMeshEventsOptions = {}): UseMeshEventsResult {
  const { maxEvents = 200, onEvent } = options;
  const [events, setEvents] = useState<DashboardEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const seenKeys = useRef<Set<string>>(new Set());

  const clearEvents = useCallback(() => {
    setEvents([]);
    seenKeys.current.clear();
  }, []);

  useEffect(() => {
    const eventSource = new EventSource(`${API_BASE}/events`);

    eventSource.onopen = () => {
      setConnected(true);
      setError(null);
    };

    eventSource.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects, just track the state
    };

    // Listen for all event types published by the Go backend
    const eventTypes = [
      "connected",
      "agent_registered",
      "agent_deregistered",
      "agent_healthy",
      "agent_unhealthy",
      "dependency_resolved",
      "dependency_lost",
      "trace_activity",
      "edge_stats",
      "agent_stats",
      "model_stats",
    ];

    const handleEvent = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as DashboardEvent;
        // Override type from the SSE event type field
        const event: DashboardEvent = { ...data, type: e.type as DashboardEvent["type"] };

        // Notify context handler first (handles state updates for all event types)
        onEventRef.current?.(event);

        // Only add agent lifecycle events to the event feed (not metrics/trace updates)
        const metricsEvents = ["trace_activity", "edge_stats", "agent_stats", "model_stats"];
        if (metricsEvents.includes(event.type)) return;

        const key = `${event.type}:${event.agent_id ?? ""}:${event.timestamp}`;
        if (seenKeys.current.has(key)) return;
        seenKeys.current.add(key);

        setEvents((prev) => {
          const next = [event, ...prev];
          return next.slice(0, maxEvents);
        });
      } catch (err) {
        console.error("Failed to parse SSE event:", err);
      }
    };

    for (const type of eventTypes) {
      eventSource.addEventListener(type, handleEvent);
    }

    return () => {
      eventSource.close();
      setConnected(false);
    };
  }, [maxEvents]);

  return { events, connected, error, clearEvents };
}
