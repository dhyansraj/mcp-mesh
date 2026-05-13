import { useCallback, useEffect, useRef, useState } from "react";
import { getSchemaUsage } from "./api";
import { SchemaUsage } from "./types";

/**
 * Issue #971: page-local Schema detail state — polls /api/schemas/{hash}/usage
 * every 5 seconds with the same visibility-pause + generation-counter pattern
 * as use-schemas.ts / use-jobs.ts.
 *
 * The hash arrives via the URL param. Empty string ⇒ no fetch (used during
 * route mounting before useParams resolves).
 */

const POLL_INTERVAL_MS = 5_000;

export interface UseSchemaUsageResult {
  usage: SchemaUsage | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useSchemaUsage(hash: string): UseSchemaUsageResult {
  const [usage, setUsage] = useState<SchemaUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const genRef = useRef(0);
  // Keep latest hash in a ref so the poll closure picks up param changes
  // without us tearing the interval down.
  const hashRef = useRef(hash);
  hashRef.current = hash;

  const fetchOnce = useCallback(async () => {
    const cur = hashRef.current;
    if (!cur) return;
    const gen = ++genRef.current;
    try {
      const resp = await getSchemaUsage(cur);
      if (gen !== genRef.current) return;
      setUsage(resp);
      setError(null);
    } catch (err) {
      if (gen !== genRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (gen === genRef.current) setLoading(false);
    }
  }, []);

  // Refetch whenever the hash param changes.
  useEffect(() => {
    if (!hash) return;
    setLoading(true);
    setUsage(null);
    fetchOnce();
  }, [hash, fetchOnce]);

  // 5s poll + visibility-pause.
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer !== null) return;
      timer = setInterval(() => {
        if (typeof document !== "undefined" && document.hidden) return;
        fetchOnce();
      }, POLL_INTERVAL_MS);
    };

    const stop = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    const onVisibility = () => {
      if (typeof document === "undefined") return;
      if (document.hidden) {
        stop();
      } else {
        fetchOnce();
        start();
      }
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
      if (!document.hidden) start();
    } else {
      start();
    }

    return () => {
      stop();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
    };
  }, [fetchOnce]);

  const refresh = useCallback(() => {
    setLoading(true);
    fetchOnce();
  }, [fetchOnce]);

  return { usage, loading, error, refresh };
}
