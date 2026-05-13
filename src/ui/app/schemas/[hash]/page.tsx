import { Link, useNavigate, useParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { Header } from "@/components/layout/Header";
import { ConnectionError } from "@/components/layout/ConnectionError";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSchemaUsage } from "@/lib/use-schema-usage";
import { formatRelativeTime, getRuntimeBadgeColor, getRuntimeLabel } from "@/lib/api";
import { SchemaConsumer, SchemaProvider } from "@/lib/types";
import { ArrowLeft, Check, Copy, Globe, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Issue #971: Schema Registry Browser — detail view.
 *
 * Surfaces the canonical JSON body alongside the provider/consumer split.
 * The cross-runtime banner is the PR #841 win made visible: when one
 * normalized schema is provided by agents in more than one runtime, it means
 * the dedup-by-canonical-hash actually paid off.
 */

function HashWithCopy({ hash, className }: { hash: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Silent fall-back: operators can select-copy the rendered text.
    }
  };
  return (
    <span className={cn("inline-flex items-center gap-2 font-mono text-xs break-all", className)}>
      <span>{hash}</span>
      <button
        type="button"
        onClick={onCopy}
        aria-label={copied ? "Copied" : "Copy hash"}
        className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        {copied ? (
          <Check className="h-3 w-3 text-green-400" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
      </button>
    </span>
  );
}

function RoleBadge({ role }: { role: SchemaProvider["role"] }) {
  const className =
    role === "input"
      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
      : "bg-violet-500/20 text-violet-300 border-violet-500/30";
  return (
    <Badge variant="outline" className={cn("text-xs", className)}>
      {role}
    </Badge>
  );
}

function RuntimeBadge({ runtime }: { runtime: string }) {
  // Older agent rows may have an empty runtime; skip the badge entirely
  // rather than rendering a meaningless "Unknown" pill.
  if (!runtime) return null;
  return (
    <Badge variant="outline" className={cn("text-xs", getRuntimeBadgeColor(runtime))}>
      {getRuntimeLabel(runtime)}
    </Badge>
  );
}

function ProvidersTable({ providers }: { providers: SchemaProvider[] }) {
  if (providers.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        No live agents provide this schema.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Agent</TableHead>
          <TableHead>Runtime</TableHead>
          <TableHead>Function / capability</TableHead>
          <TableHead>Role</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {providers.map((p, i) => (
          <TableRow key={`${p.agent_id}-${p.function_name}-${p.role}-${i}`}>
            <TableCell>
              <div className="flex flex-col">
                <Link
                  to={`/agents?id=${encodeURIComponent(p.agent_id)}`}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  {p.agent_name}
                </Link>
                <span
                  className="text-[10px] font-mono text-muted-foreground"
                  title={p.agent_id}
                >
                  {p.agent_id.replace(`${p.agent_name}-`, "")}
                </span>
              </div>
            </TableCell>
            <TableCell><RuntimeBadge runtime={p.runtime} /></TableCell>
            <TableCell>
              <div className="text-xs font-mono text-foreground">{p.function_name}</div>
              <div className="text-xs text-muted-foreground">{p.capability}</div>
            </TableCell>
            <TableCell><RoleBadge role={p.role} /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function ConsumersTable({ consumers }: { consumers: SchemaConsumer[] }) {
  if (consumers.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        No live agents declare a dependency expecting this schema.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Agent</TableHead>
          <TableHead>Runtime</TableHead>
          <TableHead>Function / capability</TableHead>
          <TableHead>Depends on capability</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {consumers.map((c, i) => (
          <TableRow key={`${c.agent_id}-${c.function_name}-${i}`}>
            <TableCell>
              <div className="flex flex-col">
                <Link
                  to={`/agents?id=${encodeURIComponent(c.agent_id)}`}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  {c.agent_name}
                </Link>
                <span
                  className="text-[10px] font-mono text-muted-foreground"
                  title={c.agent_id}
                >
                  {c.agent_id.replace(`${c.agent_name}-`, "")}
                </span>
              </div>
            </TableCell>
            <TableCell><RuntimeBadge runtime={c.runtime} /></TableCell>
            <TableCell>
              <div className="text-xs font-mono text-foreground">{c.function_name}</div>
              <div className="text-xs text-muted-foreground">{c.capability}</div>
            </TableCell>
            <TableCell className="font-mono text-xs">{c.depends_on_capability}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function SchemaDetailPage() {
  const params = useParams<{ hash: string }>();
  const navigate = useNavigate();
  // useParams gives us the value already URL-decoded; passing the encoded
  // form to encodeURIComponent in the API layer would double-encode.
  const hash = params.hash ?? "";
  const { usage, loading, error, refresh } = useSchemaUsage(hash);

  // Cross-runtime banner: count distinct runtimes seen in providers. The
  // schema's own runtime_origin records where it was *first* seen; if
  // providers now span multiple runtimes, PR #841's canonical-hash dedup is
  // working. Empty-string runtimes (older agent rows without the field) are
  // excluded so they can't inflate the count.
  const distinctRuntimes = useMemo(() => {
    if (!usage) return new Set<string>();
    const set = new Set<string>();
    for (const p of usage.providers) {
      if (p.runtime) set.add(p.runtime);
    }
    return set;
  }, [usage]);
  const showCrossRuntimeBanner = distinctRuntimes.size > 1;

  if (loading && !usage) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Schema" subtitle="Canonical JSON schema (read-only)" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  if (error && !usage) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Schema" subtitle="Canonical JSON schema (read-only)" />
        {/* See SchemasPage for why we wrap the hook's string into an Error. */}
        <ConnectionError error={new Error(error)} onRetry={refresh} />
      </div>
    );
  }

  if (!usage) {
    return null;
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Schema" subtitle="Canonical JSON schema (read-only)" />
      <div className="flex-1 p-6 overflow-auto">
        <button
          type="button"
          onClick={() => navigate("/schemas")}
          className="mb-4 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" />
          All schemas
        </button>

        <div className="mb-4 rounded-md border border-border bg-background/40 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <HashWithCopy hash={usage.schema.hash} className="text-sm" />
            <Badge variant="outline" className={cn("text-xs", getRuntimeBadgeColor(usage.schema.runtime_origin))}>
              {getRuntimeLabel(usage.schema.runtime_origin)}
            </Badge>
            <span className="text-xs text-muted-foreground">
              First seen {formatRelativeTime(usage.schema.created_at)}
            </span>
          </div>
        </div>

        {/* Cross-runtime story banner. Only rendered when providers span
            more than one distinct runtime — single-runtime schemas don't
            demonstrate the dedup win and so don't need the marketing copy. */}
        {showCrossRuntimeBanner && (
          <div className="mb-4 flex items-start gap-3 rounded-md border border-cyan-500/30 bg-cyan-500/10 p-3 text-sm text-cyan-200">
            <Globe className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p>
                Shared across {distinctRuntimes.size} runtimes:{" "}
                {[...distinctRuntimes].map(getRuntimeLabel).join(", ")} — canonical-hash dedup at work.
              </p>
            </div>
          </div>
        )}

        <div className="mb-6 rounded-md border border-border bg-background/40">
          <div className="border-b border-border px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Canonical schema
          </div>
          <pre className="max-h-[400px] overflow-auto px-4 py-3 text-xs leading-relaxed text-foreground">
            {JSON.stringify(usage.schema.canonical, null, 2)}
          </pre>
        </div>

        <div className="mb-6 rounded-md border border-border bg-background/40">
          <div className="border-b border-border px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Providers ({usage.providers.length})
          </div>
          <ProvidersTable providers={usage.providers} />
        </div>

        <div className="mb-6 rounded-md border border-border bg-background/40">
          <div className="border-b border-border px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Consumers ({usage.consumers.length})
          </div>
          <ConsumersTable consumers={usage.consumers} />
        </div>
      </div>
    </div>
  );
}
