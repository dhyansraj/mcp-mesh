"use client";

import { useMemo } from "react";
import { Header } from "@/components/layout/Header";
import { StatsCards } from "@/components/dashboard/StatsCards";
import { EventFeed } from "@/components/dashboard/EventFeed";
import { TrafficTable } from "@/components/dashboard/TrafficTable";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ConnectionError } from "@/components/layout/ConnectionError";
import { useMesh } from "@/lib/mesh-context";
import { getStatusBgColor, getRuntimeLabel, getRuntimeBadgeColor } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, Bot } from "lucide-react";
import { AgentStat } from "@/lib/types";

export default function DashboardPage() {
  const { agents, events, loading, error, refresh, agentStats } = useMesh();

  const agentStatsMap = useMemo(() => {
    const map = new Map<string, AgentStat>();
    for (const stat of agentStats) {
      map.set(stat.agent_name, stat);
    }
    return map;
  }, [agentStats]);

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Dashboard" subtitle="MCP Mesh overview" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Dashboard" subtitle="MCP Mesh overview" />
        <ConnectionError error={error} onRetry={refresh} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Dashboard" subtitle="MCP Mesh overview" />
      <div className="flex-1 space-y-6 p-6 overflow-auto">
        <StatsCards agents={agents} />

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Traffic</CardTitle>
          </CardHeader>
          <CardContent>
            <TrafficTable />
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Event Feed */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Recent Events</CardTitle>
            </CardHeader>
            <CardContent>
              <EventFeed events={events} />
            </CardContent>
          </Card>

          {/* Agent Health Overview */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Agent Overview</CardTitle>
            </CardHeader>
            <CardContent>
              {agents.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <Bot className="mb-3 h-10 w-10 opacity-40" />
                  <p className="text-sm">No agents registered</p>
                  <p className="text-xs mt-1">Agents will appear here once they connect to the mesh</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {agents.slice(0, 10).map((agent) => (
                    <div
                      key={agent.id}
                      className="flex items-center justify-between rounded-lg border border-border/50 px-4 py-3 transition-colors hover:bg-muted/20"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <span
                          className={`flex h-2.5 w-2.5 shrink-0 rounded-full ${getStatusBgColor(agent.status)}`}
                        />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground truncate">
                            {agent.name}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {agent.dependencies_resolved}/{agent.total_dependencies} deps resolved
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {agent.runtime && (
                          <Badge variant="outline" className={cn("text-xs", getRuntimeBadgeColor(agent.runtime))}>
                            {getRuntimeLabel(agent.runtime)}
                          </Badge>
                        )}
                        {(() => {
                          const stat = agentStatsMap.get(agent.name);
                          if (stat && stat.span_count > 0) {
                            return (
                              <span className="text-xs font-mono text-muted-foreground">
                                {stat.span_count} calls
                              </span>
                            );
                          }
                          return (
                            <Badge
                              variant={
                                agent.status === "healthy"
                                  ? "default"
                                  : agent.status === "unhealthy"
                                    ? "destructive"
                                    : "secondary"
                              }
                              className="text-xs"
                            >
                              {agent.status}
                            </Badge>
                          );
                        })()}
                      </div>
                    </div>
                  ))}
                  {agents.length > 10 && (
                    <p className="text-xs text-center text-muted-foreground pt-2">
                      and {agents.length - 10} more agents...
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
