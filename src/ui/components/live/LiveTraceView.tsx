"use client";

import { useState, useEffect, useRef } from "react";
import { LiveTrace, LiveSpan } from "@/lib/live-trace";
import { formatRelativeTime } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  CheckCircle2,
  XCircle,
  ChevronRight,
  ChevronDown,
  Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";

// -- Span tree logic (adapted from AgentTraces) --

interface SpanNode {
  span: LiveSpan;
  children: SpanNode[];
}

function buildLiveSpanTree(spans: LiveSpan[]): SpanNode[] {
  // Filter out proxy_call_wrapper spans
  const meaningful = spans.filter((s) => s.operation !== "proxy_call_wrapper");
  const wrapperIds = new Set(
    spans
      .filter((s) => s.operation === "proxy_call_wrapper")
      .map((s) => s.span_id)
  );

  const spanById = new Map<string, LiveSpan>();
  for (const s of spans) {
    spanById.set(s.span_id, s);
  }

  function resolveParent(
    parentId: string | undefined,
    visited = new Set<string>()
  ): string | undefined {
    if (!parentId) return undefined;
    if (!wrapperIds.has(parentId)) return parentId;
    if (visited.has(parentId)) return undefined;
    visited.add(parentId);
    const parent = spanById.get(parentId);
    if (!parent) return undefined;
    return resolveParent(parent.parent_span, visited);
  }

  const childrenMap = new Map<string | "root", SpanNode[]>();
  childrenMap.set("root", []);

  for (const s of meaningful) {
    const effectiveParent = resolveParent(s.parent_span);
    const key = effectiveParent ?? "root";
    const node: SpanNode = { span: s, children: [] };
    if (!childrenMap.has(key)) childrenMap.set(key, []);
    childrenMap.get(key)!.push(node);
  }

  function wireChildren(node: SpanNode): void {
    node.children = childrenMap.get(node.span.span_id) || [];
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

// -- Span tree row --

function LiveSpanRow({
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
  const showAgentBadge = span.agent_name !== parentAgent;
  const isInProgress =
    span.duration_ms === undefined || span.duration_ms === null;
  const isEnd = span.event_type === "span_end";

  return (
    <>
      <div className="flex items-center gap-1 py-0.5 font-mono text-xs leading-relaxed animate-in fade-in duration-300">
        {depth > 0 && (
          <span
            className="text-muted-foreground/40 select-none shrink-0 whitespace-pre"
            style={{ paddingLeft: `${(depth - 1) * 20}px` }}
          >
            {connector}
          </span>
        )}
        <span className="font-semibold text-foreground">{span.operation}</span>
        {showAgentBadge && (
          <Badge
            variant="outline"
            className="text-[10px] px-1.5 py-0 text-primary border-primary/30 ml-1"
          >
            {span.agent_name}
          </Badge>
        )}
        {span.runtime && showAgentBadge && (
          <Badge
            variant="outline"
            className="text-[10px] px-1.5 py-0 text-muted-foreground border-muted ml-0.5"
          >
            {span.runtime}
          </Badge>
        )}
        {!isInProgress && (
          <span className="text-muted-foreground ml-1">
            [{span.duration_ms}ms]
          </span>
        )}
        {isInProgress && !isEnd && (
          <span className="ml-1 inline-flex items-center gap-0.5">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
            <span className="text-cyan-400 text-[10px]">...</span>
          </span>
        )}
        {span.success === true && (
          <CheckCircle2 className="h-3 w-3 text-green-500 shrink-0 ml-0.5" />
        )}
        {span.success === false && (
          <XCircle className="h-3 w-3 text-red-500 shrink-0 ml-0.5" />
        )}
      </div>
      {children.map((child, i) => (
        <LiveSpanRow
          key={child.span.span_id}
          node={child}
          depth={depth + 1}
          isLast={i === children.length - 1}
          parentAgent={span.agent_name}
        />
      ))}
    </>
  );
}

// -- Single trace card --

function TraceCard({
  trace,
  defaultExpanded,
}: {
  trace: LiveTrace;
  defaultExpanded: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const roots = buildLiveSpanTree(trace.spans);

  // Compute total duration from root span if completed
  const rootSpan = trace.spans.find((s) => !s.parent_span && s.duration_ms !== undefined);
  const totalDuration = rootSpan?.duration_ms;
  const rootSuccess = rootSpan?.success;

  return (
    <div className="rounded-lg border border-border/50 overflow-hidden animate-in fade-in slide-in-from-top-2 duration-300">
      {/* Header */}
      <div
        className="flex items-center justify-between gap-2 px-4 py-3 cursor-pointer hover:bg-muted/30 transition-colors"
        onClick={() => setExpanded((prev) => !prev)}
      >
        <div className="flex items-center gap-2 min-w-0">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
          )}
          {trace.completed ? (
            rootSuccess === false ? (
              <XCircle className="h-4 w-4 text-red-500 shrink-0" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
            )
          ) : (
            <span className="flex h-4 w-4 items-center justify-center shrink-0">
              <span className="h-2.5 w-2.5 rounded-full bg-cyan-400 animate-pulse" />
            </span>
          )}
          <span className="text-sm font-medium text-foreground truncate">
            {trace.root_operation || "..."}
          </span>
          {trace.root_agent && (
            <Badge
              variant="outline"
              className="text-[10px] px-1.5 py-0 text-primary border-primary/30"
            >
              {trace.root_agent}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {totalDuration !== undefined && (
            <span className="text-xs font-mono text-muted-foreground">
              {totalDuration}ms
            </span>
          )}
          <span className="text-xs text-muted-foreground/60">
            {formatRelativeTime(trace.start_time)}
          </span>
        </div>
      </div>

      {/* Span count summary */}
      <div className="px-4 pb-2 flex items-center gap-3 flex-wrap text-xs text-muted-foreground">
        <span>{trace.spans.filter((s) => s.operation !== "proxy_call_wrapper").length} spans</span>
        <span>
          {new Set(trace.spans.map((s) => s.agent_name)).size} agents
        </span>
        {!trace.completed && (
          <Badge
            variant="outline"
            className="text-[10px] px-1.5 py-0 text-cyan-400 border-cyan-400/30"
          >
            in progress
          </Badge>
        )}
      </div>

      {/* Span tree */}
      {expanded && (
        <div className="border-t border-border/30 bg-muted/20 px-4 py-3">
          {roots.length > 0 ? (
            roots.map((root, i) => (
              <LiveSpanRow
                key={root.span.span_id}
                node={root}
                depth={0}
                isLast={i === roots.length - 1}
                parentAgent={null}
              />
            ))
          ) : (
            // No tree structure yet — show flat spans
            trace.spans
              .filter((s) => s.operation !== "proxy_call_wrapper")
              .map((s) => (
                <div
                  key={s.span_id}
                  className="flex items-center gap-1 font-mono text-xs py-0.5"
                >
                  <span className="text-foreground">{s.operation}</span>
                  <Badge
                    variant="outline"
                    className="text-[10px] px-1.5 py-0 text-primary border-primary/30 ml-1"
                  >
                    {s.agent_name}
                  </Badge>
                  {s.duration_ms !== undefined && (
                    <span className="text-muted-foreground ml-1">
                      [{s.duration_ms}ms]
                    </span>
                  )}
                  {s.duration_ms === undefined && (
                    <span className="ml-1 inline-flex items-center gap-0.5">
                      <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                      <span className="text-cyan-400 text-[10px]">...</span>
                    </span>
                  )}
                  {s.success === true && (
                    <CheckCircle2 className="h-3 w-3 text-green-500 ml-0.5" />
                  )}
                  {s.success === false && (
                    <XCircle className="h-3 w-3 text-red-500 ml-0.5" />
                  )}
                </div>
              ))
          )}
        </div>
      )}
    </div>
  );
}

// -- Main component --

interface LiveTraceViewProps {
  traces: LiveTrace[];
}

export function LiveTraceView({ traces }: LiveTraceViewProps) {
  if (traces.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <Activity className="mb-3 h-10 w-10 opacity-40" />
        <p className="text-sm">Waiting for traces...</p>
        <p className="text-xs mt-1">
          Traces will appear here as agents handle requests
        </p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="space-y-3 p-6">
        {traces.map((trace, i) => (
          <TraceCard
            key={trace.trace_id}
            trace={trace}
            defaultExpanded={i === 0}
          />
        ))}
      </div>
    </ScrollArea>
  );
}
