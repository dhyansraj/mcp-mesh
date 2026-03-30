"use client";

import { useState, useEffect, useCallback, useRef } from "react";

const API_BASE = process.env.NEXT_PUBLIC_REGISTRY_URL || "http://localhost:8000";

export interface LiveSpan {
  trace_id: string;
  span_id: string;
  parent_span?: string;
  agent_name: string;
  agent_id: string;
  operation: string;
  event_type: string;
  duration_ms?: number;
  success?: boolean;
  runtime?: string;
  timestamp: string;
}

export interface LiveTrace {
  trace_id: string;
  spans: LiveSpan[];
  root_agent?: string;
  root_operation?: string;
  start_time: string;
  last_seen: string;
  completed: boolean;
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
  const orderRef = useRef<string[]>([]);

  const handleSpan = useCallback((span: LiveSpan) => {
    const map = tracesRef.current;
    const order = orderRef.current;

    let trace = map.get(span.trace_id);
    if (!trace) {
      trace = {
        trace_id: span.trace_id,
        spans: [],
        start_time: span.timestamp,
        last_seen: span.timestamp,
        completed: false,
      };
      map.set(span.trace_id, trace);
      order.unshift(span.trace_id);

      // Evict oldest if over limit
      while (order.length > MAX_TRACES) {
        const old = order.pop()!;
        map.delete(old);
      }
    }

    // Merge span: update existing or add new
    const existingIdx = trace.spans.findIndex((s) => s.span_id === span.span_id);
    if (existingIdx >= 0) {
      // Merge span_end data into existing span_start entry
      trace.spans[existingIdx] = { ...trace.spans[existingIdx], ...span };
    } else {
      trace.spans.push(span);
    }

    // Update root info — root span has no parent or parent is "null"/""/undefined
    const isRootSpan = !span.parent_span || span.parent_span === "null";
    if (isRootSpan) {
      trace.root_agent = span.agent_name;
      trace.root_operation = span.operation;
      // Mark completed when root span has duration > 0 (span_end arrived)
      if (span.duration_ms !== undefined && span.duration_ms !== null && span.duration_ms > 0) {
        trace.completed = true;
      }
    }

    trace.last_seen = span.timestamp;

    // Move this trace to front of order if not already
    const idx = order.indexOf(span.trace_id);
    if (idx > 0) {
      order.splice(idx, 1);
      order.unshift(span.trace_id);
    }

    // Build sorted array from order
    const sorted: LiveTrace[] = [];
    for (const id of order) {
      const t = map.get(id);
      if (t) sorted.push({ ...t, spans: [...t.spans] });
    }
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

    eventSource.addEventListener("span", (e: MessageEvent) => {
      try {
        const span = JSON.parse(e.data) as LiveSpan;
        handleSpan(span);
      } catch (err) {
        console.error("Failed to parse live span:", err);
      }
    });

    eventSource.addEventListener("connected", () => {
      setConnected(true);
    });

    return () => {
      eventSource.close();
      setConnected(false);
    };
  }, [active, handleSpan]);

  // Clear state when deactivated
  useEffect(() => {
    if (!active) {
      tracesRef.current.clear();
      orderRef.current = [];
      setTraces([]);
    }
  }, [active]);

  return { traces, connected, active, setActive };
}
