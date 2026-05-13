import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getSchemas } from "./api";
import { SchemaListItem } from "./types";

/**
 * Issue #971: page-local Schemas list state with a 5-second poll +
 * visibility-pause + generation-counter pattern. Verbatim from use-jobs.ts
 * (issue #973): keeping these hooks parallel makes the rhythm of the
 * dashboard predictable — every read-only browse page polls the same way.
 *
 * Filtering is client-side because the list is bounded (live mesh ≈ O(100)
 * schemas) and the only filter is a substring match. Pushing it server-side
 * would require an extra query param + a re-fetch on every keystroke for
 * no win.
 */

const POLL_INTERVAL_MS = 5_000;

export interface UseSchemasResult {
  schemas: SchemaListItem[];
  /** Raw, unfiltered list — useful for totals/badge counters. */
  allSchemas: SchemaListItem[];
  search: string;
  setSearch: (next: string) => void;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useSchemas(): UseSchemasResult {
  const [allSchemas, setAllSchemas] = useState<SchemaListItem[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Generation counter — if the user navigates away or triggers a manual
  // refresh while a fetch is in flight, we discard the late response.
  const genRef = useRef(0);

  const fetchOnce = useCallback(async () => {
    const gen = ++genRef.current;
    try {
      const resp = await getSchemas();
      if (gen !== genRef.current) return;
      setAllSchemas(resp.schemas);
      setError(null);
    } catch (err) {
      if (gen !== genRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (gen === genRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchOnce();
  }, [fetchOnce]);

  // 5s poll + visibility-pause. Identical lifecycle to use-jobs.
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer !== null) return;
      timer = setInterval(() => {
        // Belt-and-suspenders against missed visibilitychange events.
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

  // Client-side filter: substring match over hash + sample_function. Case
  // insensitive — operators paste hash prefixes ("sha256:ab…") from logs and
  // expect them to match without worrying about case.
  const schemas = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (q === "") return allSchemas;
    return allSchemas.filter((s) => {
      if (s.hash.toLowerCase().includes(q)) return true;
      if (s.sample_function && s.sample_function.toLowerCase().includes(q)) return true;
      return false;
    });
  }, [allSchemas, search]);

  return { schemas, allSchemas, search, setSearch, loading, error, refresh };
}
