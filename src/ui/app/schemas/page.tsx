import { useNavigate } from "react-router-dom";
import { useState } from "react";
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
import { useSchemas } from "@/lib/use-schemas";
import { formatRelativeTime, getRuntimeBadgeColor, getRuntimeLabel } from "@/lib/api";
import { SchemaListItem } from "@/lib/types";
import { Check, Copy, FileJson, Info, Loader2, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Issue #971: Schema Registry Browser — list view.
 *
 * Read-only (Grafana-style). The dashboard never mutates the canonical
 * schema store; the only way to add or remove a row is via agent registration
 * or sweep on the registry side. There are deliberately no edit/delete
 * controls on this page — see the banner below for the operator-facing
 * version of that constraint.
 */

function truncateHash(hash: string): string {
  // Hashes look like "sha256:<64 hex chars>". Show algo + 6 leading + 4
  // trailing so two visually-similar hashes stay distinguishable.
  const colon = hash.indexOf(":");
  if (colon === -1 || hash.length <= colon + 12) return hash;
  const algo = hash.slice(0, colon + 1);
  const digest = hash.slice(colon + 1);
  return `${algo}${digest.slice(0, 6)}…${digest.slice(-4)}`;
}

function HashCell({ hash }: { hash: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async (e: React.MouseEvent) => {
    // Stop the row click so the copy click doesn't navigate away.
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(hash);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can fail under HTTP / sandboxed contexts; silently
      // ignore — the operator can still select-copy the truncated text.
    }
  };
  return (
    <span className="inline-flex items-center gap-2 font-mono text-xs">
      <span title={hash}>{truncateHash(hash)}</span>
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

function RuntimeBadge({ runtime }: { runtime: string }) {
  return (
    <Badge variant="outline" className={cn("text-xs", getRuntimeBadgeColor(runtime))}>
      {getRuntimeLabel(runtime)}
    </Badge>
  );
}

interface SchemaRowProps {
  schema: SchemaListItem;
  onOpen: (hash: string) => void;
}

function SchemaRow({ schema, onOpen }: SchemaRowProps) {
  const onKeyDown = (e: React.KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen(schema.hash);
    }
  };
  return (
    <TableRow
      className="cursor-pointer"
      onClick={() => onOpen(schema.hash)}
      onKeyDown={onKeyDown}
      tabIndex={0}
      role="button"
    >
      <TableCell><HashCell hash={schema.hash} /></TableCell>
      <TableCell><RuntimeBadge runtime={schema.runtime_origin} /></TableCell>
      <TableCell className="font-mono text-xs">{schema.provider_count}</TableCell>
      <TableCell className="font-mono text-xs">{schema.consumer_count}</TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">
        {schema.sample_function ?? <span className="italic">—</span>}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {formatRelativeTime(schema.created_at)}
      </TableCell>
    </TableRow>
  );
}

export default function SchemasPage() {
  const { schemas, allSchemas, search, setSearch, loading, error, refresh } = useSchemas();
  const navigate = useNavigate();

  const open = (hash: string) => navigate(`/schemas/${encodeURIComponent(hash)}`);

  if (loading && allSchemas.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Schemas" subtitle="Canonical JSON schemas (read-only)" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  if (error && allSchemas.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Schemas" subtitle="Canonical JSON schemas (read-only)" />
        {/* The hook surfaces `error` as a string; ConnectionError expects an
            Error object so it can sniff `.message` for network-error detection.
            Wrap to keep the contract clean (the jobs page leaves this loose
            and trips a known TS2322 — issue tracked separately). */}
        <ConnectionError error={new Error(error)} onRetry={refresh} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Schemas" subtitle="Canonical JSON schemas (read-only)" />
      <div className="flex-1 p-6 overflow-auto">
        {/* Read-only constraint banner — mirrors the Jobs page meshctl note.
            Text-only on purpose: no edit/delete affordances anywhere on this page. */}
        <div className="mb-4 flex items-start gap-3 rounded-md border border-blue-500/30 bg-blue-500/10 p-3 text-sm text-blue-200">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p>
              Schemas are content-addressed by hash and managed automatically by the
              registry as agents register and sweep. This page is observation-only.
            </p>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Search className="h-3 w-3" />
            <div className="relative">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="hash prefix or function name"
                className="h-7 w-72 rounded-md border border-border bg-background px-2 pr-6 text-xs text-foreground placeholder:text-muted-foreground/60 focus:border-primary focus:outline-none"
              />
              {search !== "" && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  aria-label="Clear search"
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </label>
          <span className="text-xs text-muted-foreground">
            {schemas.length} of {allSchemas.length}
          </span>
          {error && (
            <span className="ml-auto text-xs text-red-400">{error}</span>
          )}
        </div>

        {schemas.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <FileJson className="mb-3 h-12 w-12 opacity-40" />
            <p className="text-sm font-medium">
              {allSchemas.length === 0
                ? "No canonical schemas registered yet"
                : "No schemas match the current search"}
            </p>
            {allSchemas.length === 0 && (
              <p className="text-xs mt-1">
                Schemas appear here once agents register capabilities with typed inputs or outputs
              </p>
            )}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Hash</TableHead>
                <TableHead>Origin</TableHead>
                <TableHead>Providers</TableHead>
                <TableHead>Consumers</TableHead>
                <TableHead>Sample function</TableHead>
                <TableHead>First seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schemas.map((s) => (
                <SchemaRow key={s.hash} schema={s} onOpen={open} />
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
