"use client";

import { AlertCircle, Container, RefreshCw, Server, Terminal, Wifi, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { API_BASE } from "@/lib/api";

interface ConnectionErrorProps {
  error: Error;
  onRetry: () => void;
}

export function ConnectionError({ error, onRetry }: ConnectionErrorProps) {
  const isNetworkError =
    error.message.includes("Failed to fetch") ||
    error.message.includes("NetworkError") ||
    error.message.includes("ECONNREFUSED");

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-8">
      <div className="max-w-lg w-full space-y-6 text-center">
        {/* Icon */}
        <div className="flex justify-center">
          <div className="rounded-full bg-red-500/10 p-4">
            <WifiOff className="h-10 w-10 text-red-400" />
          </div>
        </div>

        {/* Title */}
        <div>
          <h2 className="text-lg font-semibold text-foreground">
            {isNetworkError ? "Unable to connect to registry" : "Something went wrong"}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {isNetworkError
              ? `The dashboard cannot reach the MCP Mesh registry at ${API_BASE}`
              : error.message}
          </p>
        </div>

        {/* Help card */}
        {isNetworkError && (
          <Card className="bg-card/50 border-border text-left">
            <CardContent className="pt-4 space-y-4">
              {/* Local development */}
              <div>
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                  Local development
                </p>
                <div className="space-y-2">
                  <div className="flex items-start gap-2.5">
                    <Terminal className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm text-foreground">Start the registry</p>
                      <code className="text-xs text-muted-foreground bg-background/50 px-1.5 py-0.5 rounded">
                        meshctl start
                      </code>
                    </div>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <Wifi className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm text-foreground">Verify it&apos;s running</p>
                      <code className="text-xs text-muted-foreground bg-background/50 px-1.5 py-0.5 rounded">
                        curl {API_BASE}/health
                      </code>
                    </div>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <AlertCircle className="h-4 w-4 text-yellow-500 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm text-foreground">Enable CORS for dev mode</p>
                      <code className="text-xs text-muted-foreground bg-background/50 px-1.5 py-0.5 rounded">
                        MCP_MESH_CORS_ORIGIN=* meshctl start
                      </code>
                    </div>
                  </div>
                </div>
              </div>

              {/* Docker / K8s */}
              <div className="border-t border-border pt-3">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                  Docker Compose / Kubernetes
                </p>
                <div className="space-y-2">
                  <div className="flex items-start gap-2.5">
                    <Container className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm text-foreground">Set the registry URL</p>
                      <code className="text-xs text-muted-foreground bg-background/50 px-1.5 py-0.5 rounded">
                        MCP_MESH_REGISTRY_URL=http://registry:8000
                      </code>
                    </div>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <Server className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm text-foreground">Or use meshctl with --registry-url</p>
                      <code className="text-xs text-muted-foreground bg-background/50 px-1.5 py-0.5 rounded">
                        meshctl list --registry-url http://registry:8000
                      </code>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Retry button */}
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Retry connection
        </Button>

        {/* Registry URL */}
        <p className="text-[10px] text-muted-foreground/60">
          Connecting to: {API_BASE} (set via NEXT_PUBLIC_REGISTRY_URL)
        </p>
      </div>
    </div>
  );
}
