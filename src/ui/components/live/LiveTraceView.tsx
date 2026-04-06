import { useState } from "react";
import { LiveTrace, SnapshotSpan } from "@/lib/live-trace";
import { formatRelativeTime, formatDuration } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  CheckCircle2,
  XCircle,
  ChevronRight,
  ChevronDown,
  Activity,
} from "lucide-react";

// -- Span tree logic --

interface SpanNode {
  span: SnapshotSpan;
  children: SpanNode[];
}

function buildSpanTree(spans: SnapshotSpan[]): SpanNode[] {
  const nodeMap = new Map<string, SpanNode>();
  const roots: SpanNode[] = [];

  for (const span of spans) {
    nodeMap.set(span.span_id, { span, children: [] });
  }

  for (const span of spans) {
    const node = nodeMap.get(span.span_id)!;
    if (span.effective_parent && nodeMap.has(span.effective_parent)) {
      nodeMap.get(span.effective_parent)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

// -- Span tree row --

const MAX_DEPTH = 50;

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
  if (depth >= MAX_DEPTH) return null;
  const { span, children } = node;
  const connector = depth === 0 ? "" : isLast ? "\u2514\u2500 " : "\u251C\u2500 ";
  const showAgentBadge = span.agent_name !== parentAgent;
  const isInProgress =
    span.duration_ms === undefined || span.duration_ms === null;

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
            [{formatDuration(span.duration_ms)}]
          </span>
        )}
        {isInProgress && (
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
  const roots = buildSpanTree(trace.spans);

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
            trace.has_error ? (
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
          <span className="text-[10px] font-mono text-muted-foreground/40 ml-1">
            {trace.trace_id.slice(0, 12)}
          </span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {trace.duration_ms !== undefined && trace.duration_ms !== null && (
            <span className="text-xs font-mono text-muted-foreground">
              {formatDuration(trace.duration_ms)}
            </span>
          )}
          <span className="text-xs text-muted-foreground/60">
            {formatRelativeTime(trace.start_time)}
          </span>
        </div>
      </div>

      {/* Span count summary */}
      <div className="px-4 pb-2 flex items-center gap-3 flex-wrap text-xs text-muted-foreground">
        <span>{trace.span_count} spans</span>
        <span>
          {trace.agents.length} agents
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
            <div className="text-xs text-muted-foreground/60 py-2">
              No spans yet
            </div>
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
