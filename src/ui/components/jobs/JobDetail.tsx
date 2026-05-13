import { Job } from "@/lib/types";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { JobStatusBadge } from "./JobStatusBadge";

interface JobDetailProps {
  job: Job;
}

function fmtEpoch(epoch: number | null | undefined): string {
  if (epoch == null || epoch === 0) return "—";
  return new Date(epoch * 1000).toLocaleString();
}

function MetaCell({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">{label}</span>
      <span className="text-sm text-foreground break-all">{value}</span>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  if (value == null) {
    return <p className="py-6 text-center text-sm text-muted-foreground">No data.</p>;
  }
  return (
    <pre className="overflow-auto rounded bg-background/70 p-3 font-mono text-xs text-foreground">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function JobDetail({ job }: JobDetailProps) {
  const progressPct =
    job.progress != null ? `${Math.round(job.progress * 100)}%` : "—";

  return (
    <div className="px-4 py-4">
      <div className="mb-4 flex items-center gap-3">
        <JobStatusBadge status={job.status} owner_instance_id={job.owner_instance_id} />
        <span className="font-mono text-xs text-muted-foreground break-all">{job.id}</span>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-3">
        <MetaCell label="Capability" value={job.capability} />
        <MetaCell label="Submitted by" value={job.submitted_by || "—"} />
        <MetaCell
          label="Owner"
          value={
            job.owner_instance_id ? (
              <span className="font-mono text-xs">{job.owner_instance_id}</span>
            ) : (
              <span className="italic text-muted-foreground/60">unclaimed</span>
            )
          }
        />
        <MetaCell label="Attempts" value={`${job.attempt_count} / ${job.max_retries}`} />
        <MetaCell label="Progress" value={progressPct} />
        <MetaCell label="Progress message" value={job.progress_message || "—"} />
        <MetaCell label="Submitted at" value={fmtEpoch(job.submitted_at)} />
        <MetaCell label="Last heartbeat" value={fmtEpoch(job.last_heartbeat_at)} />
        <MetaCell label="Lease expires" value={fmtEpoch(job.lease_expires_at)} />
        <MetaCell label="Max duration" value={job.max_duration != null ? `${job.max_duration}s` : "—"} />
        <MetaCell label="Total deadline" value={fmtEpoch(job.total_deadline)} />
        <MetaCell label="Error" value={job.error || "—"} />
      </div>

      <Tabs defaultValue="payload">
        <TabsList>
          <TabsTrigger value="payload">Payload</TabsTrigger>
          <TabsTrigger value="result">Result</TabsTrigger>
          <TabsTrigger value="error">Error</TabsTrigger>
        </TabsList>
        <TabsContent value="payload" className="mt-2">
          <JsonBlock value={job.submitted_payload} />
        </TabsContent>
        <TabsContent value="result" className="mt-2">
          <JsonBlock value={job.result} />
        </TabsContent>
        <TabsContent value="error" className="mt-2">
          {job.error ? (
            <pre className="overflow-auto rounded bg-background/70 p-3 font-mono text-xs text-red-300">
              {job.error}
            </pre>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground">No error.</p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
