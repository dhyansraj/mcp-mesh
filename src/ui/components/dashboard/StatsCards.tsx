import { Bot, HeartPulse, AlertTriangle, Puzzle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Agent } from "@/lib/types";
import { useGroupedAgents } from "@/lib/use-grouped-agents";

interface StatsCardsProps {
  agents: Agent[];
}

export function StatsCards({ agents }: StatsCardsProps) {
  // Count logical agents (replica-collapsed), not raw instances, so replicas
  // don't inflate every figure. Dependencies/capabilities are counted once per
  // logical agent via the group's representative instance.
  const groups = useGroupedAgents(agents);
  const totalAgents = groups.length;
  const healthyCount = groups.filter((g) => g.aggregateStatus === "healthy").length;
  const totalDeps = groups.reduce((sum, g) => sum + (g.totalDependencies || 0), 0);
  const resolvedDeps = groups.reduce((sum, g) => sum + (g.dependenciesResolved || 0), 0);
  const capabilitiesCount = groups.reduce((sum, g) => sum + (g.representative.capabilities?.length || 0), 0);

  const stats = [
    {
      name: "Total Agents",
      value: totalAgents.toString(),
      icon: Bot,
      color: "text-primary",
      bgColor: "bg-primary/10",
      accentColor: "bg-primary",
    },
    {
      name: "Healthy",
      value: healthyCount.toString(),
      icon: HeartPulse,
      color: "text-success",
      bgColor: "bg-success/10",
      accentColor: "bg-success",
    },
    {
      name: "Dependencies",
      value: `${resolvedDeps}/${totalDeps}`,
      icon: AlertTriangle,
      color: resolvedDeps === totalDeps ? "text-success" : resolvedDeps === 0 ? "text-red-500" : "text-yellow-500",
      bgColor: resolvedDeps === totalDeps ? "bg-success/10" : resolvedDeps === 0 ? "bg-red-500/10" : "bg-yellow-500/10",
      accentColor: resolvedDeps === totalDeps ? "bg-success" : resolvedDeps === 0 ? "bg-red-500" : "bg-yellow-500",
    },
    {
      name: "Capabilities",
      value: capabilitiesCount.toString(),
      icon: Puzzle,
      color: "text-secondary",
      bgColor: "bg-secondary/10",
      accentColor: "bg-secondary",
    },
  ];

  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => (
        <Card key={stat.name} className="border-border bg-card rounded-md overflow-hidden">
          <div className="flex">
            <div className={`w-1 ${stat.accentColor}`} />
            <CardContent className="p-6 flex-1">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">
                    {stat.name}
                  </p>
                  <p className="mt-2 text-3xl font-bold text-foreground">
                    {stat.value}
                  </p>
                </div>
                <div className={`rounded p-3 ${stat.bgColor}`}>
                  <stat.icon className={`h-6 w-6 ${stat.color}`} />
                </div>
              </div>
            </CardContent>
          </div>
        </Card>
      ))}
    </div>
  );
}
