package io.mcpmesh.spring.web;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Process-local cache of registry-stamped public URLs for each
 * {@code @MeshA2A} surface (spec §8.2).
 *
 * <p>Populated by {@code MeshEventProcessor} when the registry sends a
 * {@code surface_updated} event back as part of the heartbeat response. Read
 * by {@link MeshA2ADispatcherController} at agent-card render time.
 *
 * <p>Mirrors the Python module-level {@code _PUBLIC_URL_CACHE} in
 * {@code mesh/a2a.py:202-228}. Process-local — not persisted across
 * restarts; the registry re-stamps on the next heartbeat.
 *
 * <p>When the cache has no entry for a given {@code (path, skillId)}, the
 * controller falls back to building a local-form URL from the agent's
 * configured host:port. Returning an externally-reachable FQDN matters once
 * the producer is deployed behind a load balancer or ingress.
 *
 * <h2>Cross-runtime parity</h2>
 *
 * <p>The Rust core does not currently emit a {@code surface_updated} event to
 * Java consumers — Java's {@link io.mcpmesh.core.MeshEvent} variants only
 * cover dependency / LLM / lifecycle signals today (Phase 1 baseline). When
 * the registry adds surface URL stamping events (issue follow-up), the
 * {@code MeshEventProcessor} populates this cache via {@link #put}. Until
 * then the cache stays empty and the controller's local-fallback URL form
 * is used — which is the same fallback Python takes when the registry hasn't
 * stamped a URL yet.
 */
public class MeshA2APublicUrlCache {

    private static final Logger log = LoggerFactory.getLogger(MeshA2APublicUrlCache.class);

    private final Map<Key, String> cache = new ConcurrentHashMap<>();

    /**
     * Cache a registry-stamped public URL for one surface. Pass
     * {@code null} or empty {@code publicUrl} to clear the cached entry —
     * matches the Python helper's behaviour
     * ({@code update_public_url_cache} drops the entry when the registry
     * stops stamping it).
     */
    public void put(String path, String skillId, String publicUrl) {
        Key key = new Key(path, skillId);
        if (publicUrl == null || publicUrl.isBlank()) {
            String removed = cache.remove(key);
            if (removed != null) {
                log.debug("MeshA2A public URL cache: cleared entry for {} (skillId={})",
                    path, skillId);
            }
            return;
        }
        cache.put(key, publicUrl);
        log.debug("MeshA2A public URL cache: stored {} = {} (skillId={})",
            path, publicUrl, skillId);
    }

    /**
     * @return the cached public URL for {@code (path, skillId)}, or
     *     {@code null} when no entry exists. Callers MUST fall back to the
     *     local-form URL when this returns {@code null}.
     */
    public String get(String path, String skillId) {
        return cache.get(new Key(path, skillId));
    }

    /** @return current cache size. For diagnostics. */
    public int size() {
        return cache.size();
    }

    /** Drop every cached entry. For tests and shutdown cleanup. */
    public void clear() {
        cache.clear();
    }

    private record Key(String path, String skillId) {
        private Key {
            // Defensive: empty skillId is acceptable (some heartbeat
            // responses may omit it), but null path is a bug.
            Objects.requireNonNull(path, "path");
            skillId = skillId == null ? "" : skillId;
        }
    }
}
