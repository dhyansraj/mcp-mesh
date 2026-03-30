"use client";

import { useEffect, useState } from "react";
import { EdgeStat } from "@/lib/types";
import { getEdgeStats } from "@/lib/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { ArrowRight, Loader2, RadioTower } from "lucide-react";

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

export function TrafficTable() {
  const [edges, setEdges] = useState<EdgeStat[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const data = await getEdgeStats(20);
        if (cancelled) return;
        setEnabled(data.enabled);
        setEdges(data.edges || []);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <span className="ml-2 text-sm text-muted-foreground">Loading traffic data...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
        <RadioTower className="mb-2 h-8 w-8 opacity-40" />
        <p className="text-sm">Unable to load trace data</p>
        <p className="text-xs mt-1">{error}</p>
      </div>
    );
  }

  if (!enabled || edges.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
        <RadioTower className="mb-2 h-8 w-8 opacity-40" />
        <p className="text-sm">No trace data</p>
        <p className="text-xs mt-1">
          {!enabled
            ? "Tracing is not enabled on the registry"
            : "No inter-agent traffic recorded yet"}
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Route</TableHead>
          <TableHead className="text-right">Calls</TableHead>
          <TableHead className="text-right">Errors</TableHead>
          <TableHead className="text-right">Error Rate</TableHead>
          <TableHead className="text-right">Avg Latency</TableHead>
          <TableHead className="text-right">P99 Latency</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {edges.map((edge) => (
          <TableRow key={`${edge.source}-${edge.target}`}>
            <TableCell>
              <div className="flex items-center gap-1.5">
                <span className="font-medium text-foreground">{edge.source}</span>
                <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0" />
                <span className="font-medium text-foreground">{edge.target}</span>
              </div>
            </TableCell>
            <TableCell className="text-right font-mono">
              {edge.call_count}
            </TableCell>
            <TableCell className="text-right font-mono">
              {edge.error_count}
            </TableCell>
            <TableCell className={cn("text-right font-mono", getErrorRateColor(edge.error_rate))}>
              {edge.error_rate.toFixed(1)}%
            </TableCell>
            <TableCell className={cn("text-right font-mono", getLatencyColor(edge.avg_latency_ms))}>
              {edge.avg_latency_ms.toFixed(1)}ms
            </TableCell>
            <TableCell className={cn("text-right font-mono", getLatencyColor(edge.p99_latency_ms))}>
              {edge.p99_latency_ms.toFixed(0)}ms
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
