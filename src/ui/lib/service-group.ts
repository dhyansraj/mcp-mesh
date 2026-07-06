/**
 * RFC #1280 phase 4: display grouping of dot-namespaced capability names.
 *
 * Capability names may be dot-namespaced (e.g. "media.caption",
 * "media.thumbnail"). The grouping rule is a LAST-dot split:
 *   service = everything before the last dot ("media")
 *   method  = the final segment ("caption")
 * Undotted names have no service and stay ungrouped.
 */

export interface ServiceMethod {
  /** The service segment (everything before the last dot). */
  service: string;
  /** The method segment (the final dotted segment). */
  method: string;
}

/**
 * Split a capability name on its LAST dot. Names without a dot (or with a
 * leading/trailing dot that would produce an empty segment) are treated as
 * ungrouped: `service` is empty and `method` is the whole name.
 */
export function splitServiceCapability(name: string): ServiceMethod {
  const idx = name.lastIndexOf(".");
  if (idx <= 0 || idx === name.length - 1) {
    return { service: "", method: name };
  }
  return { service: name.slice(0, idx), method: name.slice(idx + 1) };
}

export interface ServiceGroup<T> {
  name: string;
  items: T[];
}

export interface GroupedByService<T> {
  /** Dotted items grouped by service, services sorted, items sorted by method. */
  services: ServiceGroup<T>[];
  /** Undotted items, sorted by name (byte-order, for parity with the CLI). */
  ungrouped: T[];
}

/**
 * Partition `items` by their capability name's service segment. Items whose
 * name is undotted land in `ungrouped`; the rest are grouped by service. All
 * ordering uses byte-order comparison for parity with the CLI: services are
 * sorted by name, each group's items by method name, and the ungrouped bucket
 * by name.
 */
export function groupByService<T>(
  items: T[],
  getName: (item: T) => string,
): GroupedByService<T> {
  const byService = new Map<string, Array<{ method: string; item: T }>>();
  const ungrouped: T[] = [];

  for (const item of items) {
    const { service, method } = splitServiceCapability(getName(item));
    if (!service) {
      ungrouped.push(item);
      continue;
    }
    const bucket = byService.get(service) ?? [];
    bucket.push({ method, item });
    byService.set(service, bucket);
  }

  // Byte-order comparison (not localeCompare) for parity with the CLI's
  // sort.Strings, so mixed-case service/method names order identically in
  // both surfaces.
  const byteOrder = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

  const services: ServiceGroup<T>[] = Array.from(byService.entries())
    .sort(([a], [b]) => byteOrder(a, b))
    .map(([name, entries]) => ({
      name,
      items: entries
        .sort((a, b) => byteOrder(a.method, b.method))
        .map((e) => e.item),
    }));

  ungrouped.sort((a, b) => byteOrder(getName(a), getName(b)));

  return { services, ungrouped };
}
