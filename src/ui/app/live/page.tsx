import { Header } from "@/components/layout/Header";
import { LiveTraceView } from "@/components/live/LiveTraceView";
import { useLiveTraces } from "@/lib/live-trace";
import { Radio, WifiOff } from "lucide-react";
import { cn } from "@/lib/utils";

export default function LivePage() {
  const { traces, connected, error } = useLiveTraces();

  const showDisconnected = !connected && error !== null;

  return (
    <div className="flex flex-col h-full">
      <Header title="Live" subtitle="Real-time call flow" />

      {/* Status bar */}
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span
            className={cn(
              "flex h-2 w-2 rounded-full",
              connected ? "bg-green-500" : "bg-destructive"
            )}
          />
          <span>{connected ? "Streaming" : showDisconnected ? "Disconnected" : "Connecting..."}</span>
          {traces.length > 0 && (
            <span className="ml-2">
              {traces.length} trace{traces.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {showDisconnected && traces.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <WifiOff className="h-12 w-12 text-muted-foreground/50" />
            <div className="text-center">
              <p className="text-sm font-medium text-muted-foreground">
                Distributed tracing is not available
              </p>
              <p className="text-xs text-muted-foreground/60 mt-1 max-w-sm">
                The observability stack (Tempo) is not running or not reachable.
                Start it to see live traces here.
              </p>
            </div>
          </div>
        ) : traces.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <Radio className="h-12 w-12 text-muted-foreground/50" />
            <div className="text-center">
              <p className="text-sm text-muted-foreground">
                Waiting for traces
              </p>
              <p className="text-xs text-muted-foreground/60 mt-1">
                Live spans will appear as agents process requests
              </p>
            </div>
          </div>
        ) : (
          <LiveTraceView traces={traces} />
        )}
      </div>
    </div>
  );
}
