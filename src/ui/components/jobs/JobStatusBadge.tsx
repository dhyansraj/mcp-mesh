import { Badge } from "@/components/ui/badge";
import { JobStatus } from "@/lib/types";
import { Ban, CheckCircle2, Clock, Loader2, MessageCircleQuestion, XCircle } from "lucide-react";

interface JobStatusBadgeProps {
  status: JobStatus;
  /**
   * When status === "working", the owner determines color/icon: a NULL
   * owner means the row is unclaimed (slate / Clock) and a set owner
   * means it's actively being processed (blue / spinner).
   */
  owner_instance_id?: string | null;
}

interface StyleSpec {
  label: string;
  className: string;
  icon: typeof Clock;
  spin?: boolean;
}

function styleFor(status: JobStatus, ownerSet: boolean): StyleSpec {
  switch (status) {
    case "working":
      return ownerSet
        ? {
            label: "Working",
            className: "bg-blue-500/20 text-blue-300 border-blue-500/30",
            icon: Loader2,
            spin: true,
          }
        : {
            label: "Unclaimed",
            className: "bg-slate-500/20 text-slate-300 border-slate-500/30",
            icon: Clock,
          };
    case "input_required":
      return {
        label: "Input required",
        className: "bg-amber-500/20 text-amber-300 border-amber-500/30",
        icon: MessageCircleQuestion,
      };
    case "completed":
      return {
        label: "Completed",
        className: "bg-green-500/20 text-green-300 border-green-500/30",
        icon: CheckCircle2,
      };
    case "failed":
      return {
        label: "Failed",
        className: "bg-red-500/20 text-red-300 border-red-500/30",
        icon: XCircle,
      };
    case "cancelled":
      return {
        label: "Cancelled",
        className: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
        icon: Ban,
      };
  }
}

export function JobStatusBadge({ status, owner_instance_id }: JobStatusBadgeProps) {
  const spec = styleFor(status, owner_instance_id != null && owner_instance_id !== "");
  const Icon = spec.icon;
  return (
    <Badge variant="outline" className={`text-xs gap-1 ${spec.className}`}>
      <Icon className={`h-3 w-3 ${spec.spin ? "animate-spin" : ""}`} />
      {spec.label}
    </Badge>
  );
}
