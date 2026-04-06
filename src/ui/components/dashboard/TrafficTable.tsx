import { useEffect, useMemo, useRef, useState } from "react";
import { EdgeStat } from "@/lib/types";
import { useMesh } from "@/lib/mesh-context";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { ArrowRight, RadioTower } from "lucide-react";

const MAX_HISTORY = 30; // ~5 min at 10s intervals

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

function Sparkline({ points, width = 80, height = 24 }: {
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

  // Color based on latest value
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

export function TrafficTable() {
  const { edgeStats } = useMesh();

  // Ring buffer: accumulate edge stats snapshots keyed by route
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
    setTick((t) => t + 1); // force re-render so sparklines update
  }, [edgeStats]);

  const sorted = useMemo(() => {
    return [...edgeStats].sort((a, b) => {
      const routeA = `${a.source}->${a.target}`;
      const routeB = `${b.source}->${b.target}`;
      return routeA.localeCompare(routeB);
    });
  }, [edgeStats]);

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
        <RadioTower className="mb-2 h-8 w-8 opacity-40" />
        <p className="text-sm">No trace data</p>
        <p className="text-xs mt-1">Inter-agent traffic will appear here when traces are recorded</p>
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
          <TableHead className="w-[96px]">Trend</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((edge) => {
          const key = `${edge.source}->${edge.target}`;
          const history = historyRef.current.get(key) || [];

          return (
            <TableRow key={key}>
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
              <TableCell>
                <Sparkline points={history} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
