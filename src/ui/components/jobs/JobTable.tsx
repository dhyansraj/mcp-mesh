import { useMemo, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Job } from "@/lib/types";
import { formatRelativeTime } from "@/lib/api";
import { ArrowDown, ArrowUp, Briefcase, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { JobDetail } from "./JobDetail";
import { JobStatusBadge } from "./JobStatusBadge";

interface JobTableProps {
  jobs: Job[];
}

type SortKey = "status" | "capability" | "owner" | "submitted_at" | "attempts" | "progress";
type SortDir = "asc" | "desc";

function sortJobs(jobs: Job[], key: SortKey, dir: SortDir): Job[] {
  const sorted = [...jobs].sort((a, b) => {
    let cmp = 0;
    switch (key) {
      case "status":
        cmp = a.status.localeCompare(b.status);
        break;
      case "capability":
        cmp = a.capability.localeCompare(b.capability);
        break;
      case "owner":
        cmp = (a.owner_instance_id || "").localeCompare(b.owner_instance_id || "");
        break;
      case "submitted_at":
        cmp = a.submitted_at - b.submitted_at;
        break;
      case "attempts":
        cmp = a.attempt_count - b.attempt_count;
        break;
      case "progress":
        cmp = (a.progress || 0) - (b.progress || 0);
        break;
    }
    return dir === "asc" ? cmp : -cmp;
  });
  return sorted;
}

function SortableHead({
  label,
  sortKey,
  currentKey,
  currentDir,
  onSort,
  className,
}: {
  label: string;
  sortKey: SortKey;
  currentKey: SortKey;
  currentDir: SortDir;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = currentKey === sortKey;
  return (
    <TableHead
      className={cn("cursor-pointer select-none hover:text-foreground", className)}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active && (currentDir === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        ))}
      </span>
    </TableHead>
  );
}

function epochToRelative(epoch: number | null | undefined): string {
  if (epoch == null || epoch === 0) return "—";
  return formatRelativeTime(new Date(epoch * 1000).toISOString());
}

export function JobTable({ jobs }: JobTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // Default sort: most recently submitted first (matches API order).
  const [sortKey, setSortKey] = useState<SortKey>("submitted_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sorted = useMemo(() => sortJobs(jobs, sortKey, sortDir), [jobs, sortKey, sortDir]);

  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <Briefcase className="mb-3 h-12 w-12 opacity-40" />
        <p className="text-sm font-medium">No jobs match the current filters</p>
        <p className="text-xs mt-1">Jobs will appear here as agents submit work to the mesh</p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-8" />
          <SortableHead label="Status" sortKey="status" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortableHead label="Capability" sortKey="capability" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortableHead label="Owner" sortKey="owner" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortableHead label="Submitted" sortKey="submitted_at" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortableHead label="Progress" sortKey="progress" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortableHead label="Attempts" sortKey="attempts" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((job) => {
          const isExpanded = expandedId === job.id;
          return (
            <JobRow
              key={job.id}
              job={job}
              isExpanded={isExpanded}
              onToggle={() => setExpandedId(isExpanded ? null : job.id)}
            />
          );
        })}
      </TableBody>
    </Table>
  );
}

interface JobRowProps {
  job: Job;
  isExpanded: boolean;
  onToggle: () => void;
}

function JobRow({ job, isExpanded, onToggle }: JobRowProps) {
  const progressPct = job.progress != null ? `${Math.round(job.progress * 100)}%` : "—";
  return (
    <>
      <TableRow className="cursor-pointer" onClick={onToggle}>
        <TableCell>
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </TableCell>
        <TableCell>
          <JobStatusBadge status={job.status} owner_instance_id={job.owner_instance_id} />
        </TableCell>
        <TableCell className="font-mono text-xs text-foreground">{job.capability}</TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {job.owner_instance_id ? (
            <span className="font-mono">{job.owner_instance_id}</span>
          ) : (
            <span className="italic">unclaimed</span>
          )}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {epochToRelative(job.submitted_at)}
        </TableCell>
        <TableCell className="font-mono text-xs">{progressPct}</TableCell>
        <TableCell className="font-mono text-xs">
          {job.attempt_count}/{job.max_retries}
        </TableCell>
      </TableRow>
      {isExpanded && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={7} className="bg-background/50 p-0">
            <JobDetail job={job} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
