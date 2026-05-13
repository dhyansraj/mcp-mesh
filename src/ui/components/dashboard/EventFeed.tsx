import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { DashboardEvent } from "@/lib/types";
import { formatRelativeTime } from "@/lib/api";
import { Activity } from "lucide-react";

interface EventFeedProps {
  events: DashboardEvent[];
}

// Issue #966: registry persists distinct reasons on lifecycle events
// (status_hooks.go health_degradation, ent_service.go cert_rotation /
// stale_on_startup / graceful_shutdown) but the SSE wire collapses them
// onto a single agent_unhealthy / agent_deregistered SSE type. Sub-classify
// by `data.reason` so the feed reads accurately.
function getReason(event: DashboardEvent): string | undefined {
  const r = event.data?.reason;
  return typeof r === "string" ? r : undefined;
}

function getEventLabel(event: DashboardEvent): string {
  const reason = getReason(event);
  switch (event.type) {
    case "agent_registered":
      return "Agent Registered";
    case "agent_deregistered":
      // Graceful shutdown writes an unregister event with reason=graceful_shutdown
      // (ent_service.go:2205); stale-on-startup uses unhealthy, not unregister.
      if (reason === "graceful_shutdown") return "Agent Stopped";
      return "Agent Deregistered";
    case "agent_healthy":
      return "Agent Healthy";
    case "agent_unhealthy":
      if (reason === "cert_rotation") return "Cert Rotation";
      if (reason === "graceful_shutdown") return "Agent Stopped";
      if (reason === "stale_on_startup") return "Expired (stale)";
      return "Agent Unhealthy";
    case "dependency_resolved":
      return "Dependency Resolved";
    case "dependency_lost":
      return "Dependency Lost";
    case "connected":
      return "Connected";
    case "snapshot":
      return "Snapshot";
    default:
      return event.type;
  }
}

function getEventDotColor(event: DashboardEvent): string {
  const reason = getReason(event);
  switch (event.type) {
    case "agent_registered":
    case "agent_healthy":
      return "bg-green-500";
    case "agent_deregistered":
      if (reason === "graceful_shutdown") return "bg-slate-400";
      return "bg-red-500";
    case "agent_unhealthy":
      if (reason === "cert_rotation") return "bg-blue-500";
      if (reason === "stale_on_startup") return "bg-slate-400";
      if (reason === "graceful_shutdown") return "bg-slate-400";
      return "bg-red-500";
    case "dependency_resolved":
      return "bg-blue-500";
    case "dependency_lost":
      return "bg-orange-500";
    case "connected":
      return "bg-cyan-400";
    case "snapshot":
      return "bg-yellow-500";
    default:
      return "bg-muted-foreground";
  }
}

function getRuntimeBadgeColor(runtime?: string): string {
  switch (runtime) {
    case "python":
      return "bg-blue-600/20 text-blue-400 border-blue-500/30";
    case "typescript":
      return "bg-cyan-600/20 text-cyan-400 border-cyan-500/30";
    case "java":
      return "bg-orange-600/20 text-orange-400 border-orange-500/30";
    default:
      return "";
  }
}

const INTERNAL_EVENTS = new Set(["trace_activity", "edge_stats"]);

export function EventFeed({ events }: EventFeedProps) {
  const displayEvents = events.filter((e) => !INTERNAL_EVENTS.has(e.type)).slice(0, 50);

  if (displayEvents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <Activity className="mb-3 h-10 w-10 opacity-40" />
        <p className="text-sm">No events yet</p>
        <p className="text-xs mt-1">Events will appear as agents register and change state</p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-[400px]">
      <div className="space-y-1 pr-4">
        {displayEvents.map((event, index) => {
          const reason = getReason(event);
          return (
            <div
              key={`${event.timestamp}-${event.agent_id}-${index}`}
              className="flex items-start gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-muted/30"
            >
              <span
                className={`mt-1.5 flex h-2.5 w-2.5 shrink-0 rounded-full ${getEventDotColor(event)}`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">
                    {getEventLabel(event)}
                  </span>
                  {event.runtime && (
                    <Badge
                      variant="outline"
                      className={`text-[10px] px-1.5 py-0 ${getRuntimeBadgeColor(event.runtime)}`}
                    >
                      {event.runtime}
                    </Badge>
                  )}
                  {reason && (
                    <span className="text-[10px] font-mono text-muted-foreground/70">
                      {reason}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-muted-foreground truncate">
                    {event.agent_name || event.agent_id || "system"}
                  </span>
                  <span className="text-xs text-muted-foreground/60">
                    {formatRelativeTime(event.timestamp)}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}
