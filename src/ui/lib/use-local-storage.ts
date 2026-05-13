import { useCallback, useEffect, useState } from "react";

/**
 * Issue #968: tiny localStorage-backed useState. Used by the Agents page to
 * remember the list/grid toggle across reloads. Kept dependency-free and in
 * the lib/ hooks pile alongside use-jobs / use-schemas so the dashboard
 * doesn't drag in a state library for one ~25-line concern.
 *
 * Behavior:
 *   - Lazy-init from localStorage on first render; falls back to `defaultValue`
 *     when the key is missing, JSON.parse throws, or the optional `validate`
 *     predicate rejects the parsed value.
 *   - On a failed parse / failed validation, the bad key is removed so a
 *     subsequent reload starts from `defaultValue` instead of looping on
 *     the same garbage.
 *   - Writes happen in an effect on every change. Wrapped in try/catch
 *     because localStorage can throw (quota exceeded, private-mode Safari).
 */
export function useLocalStorage<T>(
  key: string,
  defaultValue: T,
  validate?: (v: unknown) => v is T,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === "undefined") return defaultValue;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return defaultValue;
      const parsed: unknown = JSON.parse(raw);
      if (validate && !validate(parsed)) {
        window.localStorage.removeItem(key);
        return defaultValue;
      }
      return parsed as T;
    } catch {
      try {
        window.localStorage.removeItem(key);
      } catch {
        /* ignore */
      }
      return defaultValue;
    }
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* ignore quota / private-mode failures */
    }
  }, [key, value]);

  const set = useCallback((next: T) => setValue(next), []);
  return [value, set];
}
