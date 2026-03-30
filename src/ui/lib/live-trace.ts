"use client";

import { useState, useEffect, useCallback, useRef } from "react";

const API_BASE = process.env.NEXT_PUBLIC_REGISTRY_URL || "http://localhost:8000";

export interface SnapshotSpan {
  span_id: string;
  effective_parent?: string;
  agent_name: string;
  operation: string;
  duration_ms?: number;
  success?: boolean;
  runtime?: string;
}

export interface LiveTrace {
  trace_id: string;
  root_agent?: string;
  root_operation?: string;
  start_time: string;
  completed: boolean;
  duration_ms?: number;
  has_error: boolean;
  span_count: number;
  agents: string[];
  spans: SnapshotSpan[];
}

const MAX_TRACES = 20;

export interface UseLiveTracesResult {
  traces: LiveTrace[];
  connected: boolean;
  active: boolean;
  setActive: (active: boolean) => void;
}

export function useLiveTraces(): UseLiveTracesResult {
  const [traces, setTraces] = useState<LiveTrace[]>([]);
  const [connected, setConnected] = useState(false);
  const [active, setActive] = useState(false);
  const tracesRef = useRef<Map<string, LiveTrace>>(new Map());

  const handleSnapshot = useCallback((snapshot: LiveTrace) => {
    const map = tracesRef.current;
    map.set(snapshot.trace_id, snapshot);

    // Evict oldest traces if over limit
    if (map.size > MAX_TRACES) {
      const sorted = Array.from(map.values()).sort(
        (a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime()
      );
      const keep = new Set(sorted.slice(0, MAX_TRACES).map((t) => t.trace_id));
      for (const id of map.keys()) {
        if (!keep.has(id)) map.delete(id);
      }
    }

    // Build sorted array: newest first by start_time
    const sorted = Array.from(map.values()).sort(
      (a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime()
    );
    setTraces(sorted);
  }, []);

  useEffect(() => {
    if (!active) {
      setConnected(false);
      return;
    }

    const eventSource = new EventSource(`${API_BASE}/traces/live`);

    eventSource.onopen = () => {
      setConnected(true);
    };

    eventSource.onerror = () => {
      setConnected(false);
    };

    eventSource.addEventListener("connected", () => {
      setConnected(true);
    });

    eventSource.addEventListener("trace_started", (e: MessageEvent) => {
      try {
        handleSnapshot(JSON.parse(e.data) as LiveTrace);
      } catch { /* ignore parse errors */ }
    });

    eventSource.addEventListener("trace_update", (e: MessageEvent) => {
      try {
        handleSnapshot(JSON.parse(e.data) as LiveTrace);
      } catch { /* ignore parse errors */ }
    });

    eventSource.addEventListener("trace_completed", (e: MessageEvent) => {
      try {
        handleSnapshot(JSON.parse(e.data) as LiveTrace);
      } catch { /* ignore parse errors */ }
    });

    return () => {
      eventSource.close();
      setConnected(false);
    };
  }, [active, handleSnapshot]);

  // Clear state when deactivated
  useEffect(() => {
    if (!active) {
      tracesRef.current.clear();
      setTraces([]);
    }
  }, [active]);

  return { traces, connected, active, setActive };
}
