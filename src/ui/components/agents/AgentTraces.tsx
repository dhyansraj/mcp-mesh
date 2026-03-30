"use client";

import { useEffect, useState } from "react";
import { RecentTrace } from "@/lib/types";
import { getRecentTraces, formatRelativeTime } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2, CheckCircle2, XCircle, Activity } from "lucide-react";

interface AgentTracesProps {
  agentName: string;
}

export function AgentTraces({ agentName }: AgentTracesProps) {
  const [traces, setTraces] = useState<RecentTrace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
  }, [agentName]);

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

  return (
    <ScrollArea className="h-[400px]">
      <div className="space-y-2 pr-2">
        {traces.map((trace) => (
          <div
            key={trace.trace_id}
            className="rounded-lg border border-border/50 px-4 py-3"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
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
            <div className="mt-1.5 flex items-center gap-3 flex-wrap text-xs text-muted-foreground">
              <span className="font-mono">{trace.duration_ms}ms</span>
              <span>{trace.agent_count} agents</span>
              <span>{trace.span_count} spans</span>
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                {trace.root_agent}
              </Badge>
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}
