import { Header } from "@/components/layout/Header";
import { ConnectionError } from "@/components/layout/ConnectionError";
import { JobTable } from "@/components/jobs/JobTable";
import { useJobs } from "@/lib/use-jobs";
import { JobStatus } from "@/lib/types";
import { Info, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_CHIPS: { value: JobStatus; label: string }[] = [
  { value: "working", label: "Working" },
  { value: "input_required", label: "Input required" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

export default function JobsPage() {
  const { jobs, filters, setFilters, loading, error, refresh } = useJobs();

  const toggleStatus = (status: JobStatus) => {
    const next = filters.statuses.includes(status)
      ? filters.statuses.filter((s) => s !== status)
      : [...filters.statuses, status];
    setFilters({ ...filters, statuses: next });
  };

  if (loading && jobs.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Jobs" subtitle="Long-running MeshJob coordination (read-only)" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  if (error && jobs.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Jobs" subtitle="Long-running MeshJob coordination (read-only)" />
        <ConnectionError error={error} onRetry={refresh} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Jobs" subtitle="Long-running MeshJob coordination (read-only)" />
      <div className="flex-1 p-6 overflow-auto">
        {/* meshctl-only cancellation banner (issue #973, read-only constraint).
            Intentionally text-only — no buttons here. */}
        <div className="mb-4 flex items-start gap-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p>
              To cancel a job, run{" "}
              <code className="rounded bg-background/40 px-1 py-0.5 font-mono text-xs">
                meshctl call __mesh_job_cancel job_id=&lt;id&gt;
              </code>
              . The Jobs page is observation-only.
            </p>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Filter status:</span>
          {STATUS_CHIPS.map((chip) => {
            const active = filters.statuses.includes(chip.value);
            return (
              <button
                key={chip.value}
                type="button"
                onClick={() => toggleStatus(chip.value)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors",
                  active
                    ? "border-primary bg-primary/20 text-primary"
                    : "border-border bg-background text-muted-foreground hover:bg-accent",
                )}
              >
                {chip.label}
              </button>
            );
          })}
          {filters.statuses.length > 0 && (
            <button
              type="button"
              onClick={() => setFilters({ ...filters, statuses: [] })}
              className="text-xs text-muted-foreground underline-offset-2 hover:underline"
            >
              clear
            </button>
          )}
          {error && (
            <span className="ml-auto text-xs text-red-400">{error}</span>
          )}
        </div>

        <JobTable jobs={jobs} />
      </div>
    </div>
  );
}
