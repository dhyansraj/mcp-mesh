"use client";

import { useMemo, useEffect, useRef, useState } from "react";
import { Header } from "@/components/layout/Header";
import { ConnectionError } from "@/components/layout/ConnectionError";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMesh } from "@/lib/mesh-context";
import { formatBytes, formatTokenCount } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Activity,
  ArrowRight,
  Bot,
  Cpu,
  Database,
  Loader2,
  RadioTower,
  Zap,
} from "lucide-react";

const MAX_HISTORY = 30;

function getErrorRateColor(rate: number): string {
  if (rate === 0) return "text-green-400";
  if (rate < 10) return "text-yellow-400";
  return "text-red-400";
}

function getLatencyColor(ms: number): string {
  if (ms < 50) return "text-green-400";
  if (ms <= 200) return "text-yellow-400";
  return "text-red-400";
}

function Sparkline({
  points,
  width = 80,
  height = 24,
}: {
  points: number[];
  width?: number;
  height?: number;
}) {
  if (points.length < 2) {
    return <div style={{ width, height }} />;
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const pad = 2;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;

  const pathPoints = points.map((v, i) => {
    const x = pad + (i / (points.length - 1)) * innerW;
    const y = pad + innerH - ((v - min) / range) * innerH;
    return `${x},${y}`;
  });

  const latest = points[points.length - 1];
  const color = latest < 50 ? "#22c55e" : latest <= 200 ? "#eab308" : "#ef4444";

  const lastX = pad + innerW;
  const lastY = pad + innerH - ((latest - min) / range) * innerH;

  return (
    <svg width={width} height={height} className="block">
      <path
        d={`M ${pathPoints.join(" L ")}`}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={0.7}
      />
      <circle cx={lastX} cy={lastY} r={2} fill={color} />
    </svg>
  );
}

export default function TrafficPage() {
  const { edgeStats, agentStats, modelStats, loading, error, refresh } = useMesh();

  // Sparkline history ring buffer
  const historyRef = useRef<Map<string, number[]>>(new Map());
  const [, setTick] = useState(0);

  useEffect(() => {
    if (edgeStats.length === 0) return;
    for (const edge of edgeStats) {
      const key = `${edge.source}->${edge.target}`;
      const history = historyRef.current.get(key) || [];
      history.push(edge.avg_latency_ms);
      if (history.length > MAX_HISTORY) history.shift();
      historyRef.current.set(key, history);
    }
    setTick((t) => t + 1);
  }, [edgeStats]);

  // Aggregated stats for overview cards
  const overview = useMemo(() => {
    const totalCalls = edgeStats.reduce((sum, e) => sum + (e.call_count || 0), 0);
    const totalErrors = edgeStats.reduce((sum, e) => sum + (e.error_count || 0), 0);
    const successRate = totalCalls > 0 ? ((1 - totalErrors / totalCalls) * 100) : 100;

    const totalTokens = agentStats.reduce(
      (sum, a) => sum + (a.total_input_tokens || 0) + (a.total_output_tokens || 0),
      0
    );

    const totalData = agentStats.reduce(
      (sum, a) => sum + (a.total_request_bytes || 0) + (a.total_response_bytes || 0),
      0
    );

    return { totalCalls, successRate, totalTokens, totalData };
  }, [edgeStats, agentStats]);

  // Sorted edges by route name
  const sortedEdges = useMemo(() => {
    return [...edgeStats].sort((a, b) => {
      const routeA = `${a.source}->${a.target}`;
      const routeB = `${b.source}->${b.target}`;
      return routeA.localeCompare(routeB);
    });
  }, [edgeStats]);

  // Sorted agent stats by agent name (stable across SSE updates)
  const sortedAgentStats = useMemo(() => {
    return [...agentStats].sort((a, b) => a.agent_name.localeCompare(b.agent_name));
  }, [agentStats]);

  // Sorted model stats by model name (stable across SSE updates)
  const sortedModelStats = useMemo(() => {
    return [...modelStats].sort((a, b) => a.model.localeCompare(b.model));
  }, [modelStats]);

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Traffic" subtitle="Network traffic and usage metrics" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Traffic" subtitle="Network traffic and usage metrics" />
        <ConnectionError error={error} onRetry={refresh} />
      </div>
    );
  }

  const successRateColor =
    overview.successRate > 99
      ? "text-success"
      : overview.successRate > 95
        ? "text-yellow-500"
        : "text-red-500";
  const successRateAccent =
    overview.successRate > 99
      ? "bg-success"
      : overview.successRate > 95
        ? "bg-yellow-500"
        : "bg-red-500";
  const successRateBg =
    overview.successRate > 99
      ? "bg-success/10"
      : overview.successRate > 95
        ? "bg-yellow-500/10"
        : "bg-red-500/10";

  const overviewStats = [
    {
      name: "Total Calls",
      value: overview.totalCalls.toLocaleString(),
      icon: Activity,
      color: "text-primary",
      bgColor: "bg-primary/10",
      accentColor: "bg-primary",
    },
    {
      name: "Success Rate",
      value: `${overview.successRate.toFixed(1)}%`,
      icon: Zap,
      color: successRateColor,
      bgColor: successRateBg,
      accentColor: successRateAccent,
    },
    {
      name: "Total Tokens",
      value: formatTokenCount(overview.totalTokens),
      icon: Cpu,
      color: "text-secondary",
      bgColor: "bg-secondary/10",
      accentColor: "bg-secondary",
    },
    {
      name: "Data Transferred",
      value: formatBytes(overview.totalData),
      icon: Database,
      color: "text-primary",
      bgColor: "bg-primary/10",
      accentColor: "bg-primary",
    },
  ];

  return (
    <div className="flex flex-col h-full">
      <Header title="Traffic" subtitle="Network traffic and usage metrics" />
      <div className="flex-1 space-y-6 p-6 overflow-auto">
        {/* Section 1: Traffic Overview */}
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {overviewStats.map((stat) => (
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

        {/* Section 2: Per-Edge Traffic Table */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Per-Edge Traffic</CardTitle>
          </CardHeader>
          <CardContent>
            {sortedEdges.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                <RadioTower className="mb-2 h-8 w-8 opacity-40" />
                <p className="text-sm">No trace data</p>
                <p className="text-xs mt-1">
                  Inter-agent traffic will appear here when traces are recorded
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Route</TableHead>
                    <TableHead className="text-right">Calls</TableHead>
                    <TableHead className="text-right">Errors</TableHead>
                    <TableHead className="text-right">Error Rate</TableHead>
                    <TableHead className="text-right">Avg Latency</TableHead>
                    <TableHead className="text-right">P99</TableHead>
                    <TableHead className="w-[96px]">Trend</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedEdges.map((edge) => {
                    const key = `${edge.source}->${edge.target}`;
                    const history = historyRef.current.get(key) || [];

                    return (
                      <TableRow key={key}>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <span className="font-medium text-foreground">
                              {edge.source}
                            </span>
                            <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />
                            <span className="font-medium text-foreground">
                              {edge.target}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {edge.call_count}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {edge.error_count}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right font-mono",
                            getErrorRateColor(edge.error_rate)
                          )}
                        >
                          {edge.error_rate.toFixed(1)}%
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right font-mono",
                            getLatencyColor(edge.avg_latency_ms)
                          )}
                        >
                          {edge.avg_latency_ms.toFixed(1)}ms
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right font-mono",
                            getLatencyColor(edge.p99_latency_ms)
                          )}
                        >
                          {edge.p99_latency_ms.toFixed(0)}ms
                        </TableCell>
                        <TableCell>
                          <Sparkline points={history} />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Section 3: Per-Agent Stats Table */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Per-Agent Stats</CardTitle>
          </CardHeader>
          <CardContent>
            {sortedAgentStats.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                <Bot className="mb-2 h-8 w-8 opacity-40" />
                <p className="text-sm">No agent data</p>
                <p className="text-xs mt-1">
                  Per-agent metrics will appear here when agents process requests
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Agent</TableHead>
                    <TableHead className="text-right">Spans</TableHead>
                    <TableHead className="text-right">Tokens In</TableHead>
                    <TableHead className="text-right">Tokens Out</TableHead>
                    <TableHead className="text-right">Data In</TableHead>
                    <TableHead className="text-right">Data Out</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedAgentStats.map((agent) => (
                    <TableRow key={agent.agent_name}>
                      <TableCell className="font-medium text-foreground">
                        {agent.agent_name}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {(agent.span_count || 0).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatTokenCount(agent.total_input_tokens || 0)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatTokenCount(agent.total_output_tokens || 0)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatBytes(agent.total_request_bytes || 0)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatBytes(agent.total_response_bytes || 0)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Section 4: Token Usage by Model */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Token Usage by Model</CardTitle>
          </CardHeader>
          <CardContent>
            {sortedModelStats.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                <Cpu className="mb-2 h-8 w-8 opacity-40" />
                <p className="text-sm">No model data</p>
                <p className="text-xs mt-1">
                  Token usage will be grouped by LLM model when available
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead className="text-right">Calls</TableHead>
                    <TableHead className="text-right">Input Tokens</TableHead>
                    <TableHead className="text-right">Output Tokens</TableHead>
                    <TableHead className="text-right">Total Tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedModelStats.map((m) => (
                    <TableRow key={m.model}>
                      <TableCell className="font-medium text-foreground">
                        {m.model}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {m.provider || "-"}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {(m.call_count || 0).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatTokenCount(m.input_tokens || 0)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatTokenCount(m.output_tokens || 0)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatTokenCount(m.total_tokens || 0)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
