"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { DashboardEvent } from "@/lib/types";
import { formatRelativeTime } from "@/lib/api";
import { Activity } from "lucide-react";

interface EventFeedProps {
  events: DashboardEvent[];
}

function getEventLabel(type: DashboardEvent["type"]): string {
  switch (type) {
    case "agent_registered":
      return "Agent Registered";
    case "agent_deregistered":
      return "Agent Deregistered";
    case "agent_healthy":
      return "Agent Healthy";
    case "agent_unhealthy":
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
      return type;
  }
}

function getEventDotColor(type: DashboardEvent["type"]): string {
  switch (type) {
    case "agent_registered":
    case "agent_healthy":
      return "bg-green-500";
    case "agent_deregistered":
    case "agent_unhealthy":
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

export function EventFeed({ events }: EventFeedProps) {
  const displayEvents = events.slice(0, 50);

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
        {displayEvents.map((event, index) => (
          <div
            key={`${event.timestamp}-${event.agent_id}-${index}`}
            className="flex items-start gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-muted/30"
          >
            <span
              className={`mt-1.5 flex h-2.5 w-2.5 shrink-0 rounded-full ${getEventDotColor(event.type)}`}
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-foreground">
                  {getEventLabel(event.type)}
                </span>
                {event.runtime && (
                  <Badge
                    variant="outline"
                    className={`text-[10px] px-1.5 py-0 ${getRuntimeBadgeColor(event.runtime)}`}
                  >
                    {event.runtime}
                  </Badge>
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
        ))}
      </div>
    </ScrollArea>
  );
}
