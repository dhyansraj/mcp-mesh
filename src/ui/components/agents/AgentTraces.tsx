"use client";

import { useEffect, useState } from "react";
import { RecentTrace, TraceDetail, TraceSpan } from "@/lib/types";
import { getRecentTraces, getTraceDetail, formatRelativeTime } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2, CheckCircle2, XCircle, Activity, ChevronRight, ChevronDown } from "lucide-react";

interface AgentTracesProps {
  agentName: string;
  refreshKey?: number; // Changes when new trace data arrives via SSE
}

interface SpanNode {
  span: TraceSpan;
  children: SpanNode[];
}

function buildSpanTree(spans: TraceSpan[]): SpanNode[] {
  // Filter out proxy_call_wrapper spans
  const meaningful = spans.filter((s) => s.Operation !== "proxy_call_wrapper");
  const wrapperIds = new Set(
    spans.filter((s) => s.Operation === "proxy_call_wrapper").map((s) => s.SpanID)
  );

  // Build a map to resolve parent chains through skipped spans
  const spanById = new Map<string, TraceSpan>();
  for (const s of spans) {
    spanById.set(s.SpanID, s);
  }

  // Resolve the effective parent: skip over proxy_call_wrapper spans
  function resolveParent(parentId: string | null): string | null {
    if (!parentId) return null;
    if (!wrapperIds.has(parentId)) return parentId;
    const parent = spanById.get(parentId);
    if (!parent) return null;
    return resolveParent(parent.ParentSpan);
  }

  const childrenMap = new Map<string | "root", SpanNode[]>();
  childrenMap.set("root", []);

  for (const s of meaningful) {
    const effectiveParent = resolveParent(s.ParentSpan);
    const key = effectiveParent ?? "root";
    const node: SpanNode = { span: s, children: [] };
    if (!childrenMap.has(key)) childrenMap.set(key, []);
    childrenMap.get(key)!.push(node);
  }

  // Wire children recursively
  function wireChildren(node: SpanNode): void {
    node.children = childrenMap.get(node.span.SpanID) || [];
    for (const child of node.children) {
      wireChildren(child);
    }
  }

  const roots = childrenMap.get("root") || [];
  for (const root of roots) {
    wireChildren(root);
  }

  return roots;
}

function SpanTreeRow({
  node,
  depth,
  isLast,
  parentAgent,
}: {
  node: SpanNode;
  depth: number;
  isLast: boolean;
  parentAgent: string | null;
}) {
  const { span, children } = node;
  const connector = depth === 0 ? "" : isLast ? "\u2514\u2500 " : "\u251C\u2500 ";
  const showAgentBadge = span.AgentName !== parentAgent;

  return (
    <>
      <div className="flex items-center gap-1 py-0.5 font-mono text-xs leading-relaxed">
        {depth > 0 && (
          <span
            className="text-muted-foreground/40 select-none shrink-0 whitespace-pre"
            style={{ paddingLeft: `${(depth - 1) * 20}px` }}
          >
            {connector}
          </span>
        )}
        <span className="font-semibold text-foreground">{span.Operation}</span>
        {showAgentBadge && (
          <Badge
            variant="outline"
            className="text-[10px] px-1.5 py-0 text-primary border-primary/30 ml-1"
          >
            {span.AgentName}
          </Badge>
        )}
        {span.DurationMS !== null && (
          <span className="text-muted-foreground ml-1">[{span.DurationMS}ms]</span>
        )}
        {span.Success === true && (
          <CheckCircle2 className="h-3 w-3 text-green-500 shrink-0 ml-0.5" />
        )}
        {span.Success === false && (
          <XCircle className="h-3 w-3 text-red-500 shrink-0 ml-0.5" />
        )}
        {span.ErrorMessage && (
          <span className="text-red-400 ml-1 truncate">{span.ErrorMessage}</span>
        )}
      </div>
      {children.map((child, i) => (
        <SpanTreeRow
          key={child.span.SpanID}
          node={child}
          depth={depth + 1}
          isLast={i === children.length - 1}
          parentAgent={span.AgentName}
        />
      ))}
    </>
  );
}

function SpanTree({ traceId }: { traceId: string }) {
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    getTraceDetail(traceId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [traceId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-3 pl-6">
        <Loader2 className="h-4 w-4 animate-spin text-primary" />
        <span className="text-xs text-muted-foreground">Loading span tree...</span>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <p className="py-3 pl-6 text-xs text-muted-foreground">Failed to load trace detail</p>
    );
  }

  const roots = buildSpanTree(detail.Spans || []);
  if (roots.length === 0) {
    // Root span not yet received — show flat span list
    const meaningful = (detail.Spans || []).filter((s) => s.Operation !== "proxy_call_wrapper");
    if (meaningful.length === 0) {
      return (
        <p className="py-3 pl-6 text-xs text-muted-foreground">Trace still being collected...</p>
      );
    }
    return (
      <div className="border-t border-border/30 bg-muted/20 px-4 py-3">
        <p className="text-[10px] text-muted-foreground/60 mb-2">Partial trace (root span pending)</p>
        {meaningful.map((s) => (
          <div key={s.SpanID} className="flex items-center gap-1 font-mono text-xs py-0.5">
            <span className="text-foreground">{s.Operation}</span>
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-primary border-primary/30 ml-1">
              {s.AgentName}
            </Badge>
            {s.DurationMS !== null && (
              <span className="text-muted-foreground ml-1">[{s.DurationMS}ms]</span>
            )}
            {s.Success === true && <CheckCircle2 className="h-3 w-3 text-green-500 ml-0.5" />}
            {s.Success === false && <XCircle className="h-3 w-3 text-red-500 ml-0.5" />}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="border-t border-border/30 bg-muted/20 px-4 py-3">
      {roots.map((root, i) => (
        <SpanTreeRow
          key={root.span.SpanID}
          node={root}
          depth={0}
          isLast={i === roots.length - 1}
          parentAgent={null}
        />
      ))}
    </div>
  );
}

export function AgentTraces({ agentName, refreshKey }: AgentTracesProps) {
  const [traces, setTraces] = useState<RecentTrace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchTraces() {
      try {
        const data = await getRecentTraces(20);
        if (cancelled) return;
        if (!data.enabled) {
          setTraces([]);
          setError(null);
          setLoading(false);
          return;
        }
        const filtered = (data.traces || []).filter((t) =>
          t.agents.includes(agentName)
        );
        setTraces(filtered);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchTraces();
    return () => { cancelled = true; };
  }, [agentName, refreshKey]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span className="ml-2 text-sm text-muted-foreground">Loading traces...</span>
      </div>
    );
  }

  if (error) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        Unable to load traces: {error}
      </p>
    );
  }

  if (traces.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
        <Activity className="mb-2 h-8 w-8 opacity-40" />
        <p className="text-sm">No traces found</p>
        <p className="text-xs mt-1">No recent traces involve this agent</p>
      </div>
    );
  }

  function handleToggle(traceId: string) {
    setExpandedTraceId((prev) => (prev === traceId ? null : traceId));
  }

  return (
    <ScrollArea className="h-[400px]">
      <div className="space-y-2 pr-2">
        {traces.map((trace) => {
          const isExpanded = expandedTraceId === trace.trace_id;
          return (
            <div
              key={trace.trace_id}
              className="rounded-lg border border-border/50 overflow-hidden"
            >
              <div
                className="flex items-center justify-between gap-2 px-4 py-3 cursor-pointer hover:bg-muted/30 transition-colors"
                onClick={() => handleToggle(trace.trace_id)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  )}
                  {trace.success ? (
                    <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                  ) : (
                    <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                  )}
                  <span className="text-sm font-medium text-foreground truncate">
                    {trace.root_operation}
                  </span>
                </div>
                <span className="text-xs text-muted-foreground/60 shrink-0">
                  {formatRelativeTime(trace.start_time)}
                </span>
              </div>
              <div className="px-4 pb-3 flex items-center gap-3 flex-wrap text-xs text-muted-foreground">
                <span className="font-mono">{trace.duration_ms}ms</span>
                <span>{trace.agent_count} agents</span>
                <span>{trace.span_count} spans</span>
                <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                  {trace.root_agent}
                </Badge>
              </div>
              {isExpanded && <SpanTree traceId={trace.trace_id} />}
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}
