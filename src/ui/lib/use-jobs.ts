import { useCallback, useEffect, useRef, useState } from "react";
import { getJobs } from "./api";
import { Job, JobStatus } from "./types";

/**
 * Issue #973: page-local jobs state with filter inputs, error surface, and
 * a 5-second poll. Deliberately NOT wired into MeshContext — jobs change
 * shape and cadence on a much faster cadence than the agent roster, and
 * the dashboard's other pages don't care about them. Keeping this in a
 * scoped hook also means closing the Jobs tab fully tears down the poll.
 *
 * Visibility handling: the poll pauses while `document.hidden` and
 * resumes (firing one immediate fetch) when the tab is foregrounded again
 * — same pattern the existing dashboard event poller uses to avoid
 * burning the registry while the user isn't looking.
 */

export interface JobsFilters {
  /**
   * Multi-select status chips. Empty array ⇒ all statuses.
   */
  statuses: JobStatus[];
  ownerInstanceId: string;
  capability: string;
}

const DEFAULT_FILTERS: JobsFilters = {
  statuses: [],
  ownerInstanceId: "",
  capability: "",
};

const POLL_INTERVAL_MS = 5_000;
const DEFAULT_LIMIT = 50;

export interface UseJobsResult {
  jobs: Job[];
  filters: JobsFilters;
  setFilters: (next: JobsFilters) => void;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useJobs(): UseJobsResult {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [filters, setFilters] = useState<JobsFilters>(DEFAULT_FILTERS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Keep the latest filters in a ref so the poll closure doesn't capture
  // a stale value across renders.
  const filtersRef = useRef<JobsFilters>(filters);
  filtersRef.current = filters;

  // Generation counter — if a filter change happens while a fetch is in
  // flight, we discard the late response by comparing generations.
  const genRef = useRef(0);

  const fetchOnce = useCallback(async () => {
    const gen = ++genRef.current;
    const cur = filtersRef.current;
    try {
      const params: Record<string, string | number> = { limit: DEFAULT_LIMIT };
      if (cur.statuses.length > 0) params.status = cur.statuses.join(",");
      if (cur.ownerInstanceId.trim() !== "") params.owner_instance_id = cur.ownerInstanceId.trim();
      if (cur.capability.trim() !== "") params.capability = cur.capability.trim();

      const resp = await getJobs(params);
      if (gen !== genRef.current) return; // stale response, ignore
      setJobs(resp.jobs);
      setError(null);
    } catch (err) {
      if (gen !== genRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (gen === genRef.current) setLoading(false);
    }
  }, []);

  // Fetch when filters change.
  useEffect(() => {
    setLoading(true);
    fetchOnce();
  }, [filters, fetchOnce]);

  // 5s poll + visibility handling.
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer !== null) return;
      timer = setInterval(() => {
        // Belt-and-suspenders: even if visibilitychange didn't fire, a
        // hidden tab should never enqueue a request.
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
        // Coming back to the tab: fire an immediate fetch so the user
        // doesn't stare at stale data while waiting for the next tick.
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

  return { jobs, filters, setFilters, loading, error, refresh };
}
