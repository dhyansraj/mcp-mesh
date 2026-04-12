import { useState, useEffect, useCallback, useRef } from "react";
import { getApiBase } from "./config";

const API_BASE = getApiBase();

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
  error: Error | null;
  active: boolean;
  setActive: (active: boolean) => void;
}

export function useLiveTraces(): UseLiveTracesResult {
  const [traces, setTraces] = useState<LiveTrace[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [active, setActive] = useState(true);
  const tracesRef = useRef<Map<string, LiveTrace>>(new Map());

  const handleSnapshot = useCallback((snapshot: LiveTrace) => {
    const map = tracesRef.current;
    map.set(snapshot.trace_id, snapshot);

    // Sort once: newest first by start_time
    const sorted = Array.from(map.values()).sort(
      (a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime()
    );

    // Evict oldest traces if over limit
    if (sorted.length > MAX_TRACES) {
      const evicted = sorted.splice(MAX_TRACES);
      for (const t of evicted) {
        map.delete(t.trace_id);
      }
    }

    setTraces(sorted);
  }, []);

  useEffect(() => {
    if (!active) {
      setConnected(false);
      setError(null);
      tracesRef.current.clear();
      setTraces([]);
      return;
    }

    const eventSource = new EventSource(`${API_BASE}/traces/live`);

    eventSource.onopen = () => {
      setConnected(true);
      setError(null);
    };

    eventSource.onerror = () => {
      setConnected(false);
      setError(new Error("Live trace connection lost. Reconnecting..."));
    };

    eventSource.addEventListener("connected", () => {
      setConnected(true);
      setError(null);
    });

    eventSource.addEventListener("trace_started", (e: MessageEvent) => {
      try {
        handleSnapshot(JSON.parse(e.data) as LiveTrace);
      } catch (err) { console.error("live-trace: failed to parse trace_started event", err); }
    });

    eventSource.addEventListener("trace_update", (e: MessageEvent) => {
      try {
        handleSnapshot(JSON.parse(e.data) as LiveTrace);
      } catch (err) { console.error("live-trace: failed to parse trace_update event", err); }
    });

    eventSource.addEventListener("trace_completed", (e: MessageEvent) => {
      try {
        handleSnapshot(JSON.parse(e.data) as LiveTrace);
      } catch (err) { console.error("live-trace: failed to parse trace_completed event", err); }
    });

    return () => {
      eventSource.close();
      setConnected(false);
    };
  }, [active, handleSnapshot]);

  return { traces, connected, error, active, setActive };
}
