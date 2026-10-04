package io.mcpmesh;

import io.mcpmesh.core.MeshException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.DisabledIfEnvironmentVariable;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Unit tests for {@link MeshJobs} — the static {@code postEvent} helper +
 * the LRU proxy cache. Mirrors the Python {@code jobs_test.py} and
 * TypeScript {@code jobs.spec.ts} coverage:
 *
 * <ul>
 *   <li>{@code MCP_MESH_REGISTRY_URL} unset → clean error (no NPE)</li>
 *   <li>arg validation (null/empty jobId, null/empty eventType)</li>
 *   <li>cache hit returns the same proxy instance for repeated calls</li>
 *   <li>cache miss on a different jobId allocates a new instance</li>
 *   <li>LRU eviction when the cache exceeds {@code MCP_MESH_JOBPROXY_CACHE_MAX}</li>
 * </ul>
 *
 * <p>The full FFI send-event round-trip (recv_event / send_event /
 * JobNotFound / JobTerminal exceptions) is exercised in the integration
 * suite (uc23_meshjob_java/tc24–tc26) because it needs a live registry.
 * Mocking the FFI layer here would require subclassing the JNR-FFI
 * binding — not a pattern this codebase uses; integration tests are
 * the canonical cover.
 *
 * <p>The cache tests reach the {@code getOrCreateProxy} entry point
 * which DOES construct a {@link JobProxy} via {@code JobProxy.open}.
 * That construction is harmless without a live registry — the proxy
 * holds a registry URL string but doesn't make any HTTP calls until
 * {@code sendEvent} is invoked. We close each constructed proxy after
 * the test to drop the underlying FFI handle.
 */
class MeshJobsTest {

    private static final String FAKE_REGISTRY = "http://localhost:0/no-such";

    @BeforeEach
    void clearCache() {
        MeshJobs.clearProxyCacheForTest();
    }

    @AfterEach
    void clearCacheAfter() {
        MeshJobs.clearProxyCacheForTest();
    }

    @Test
    void postEvent_rejectsNullJobId() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.postEvent(null, "signal", null));
        assertTrue(e.getMessage().toLowerCase().contains("jobid"),
            "error should mention jobId; got: " + e.getMessage());
    }

    @Test
    void postEvent_rejectsEmptyJobId() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.postEvent("", "signal", null));
    }

    @Test
    void postEvent_rejectsNullEventType() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.postEvent("j-1", null, null));
        assertTrue(e.getMessage().toLowerCase().contains("eventtype"),
            "error should mention eventType; got: " + e.getMessage());
    }

    @Test
    void postEvent_rejectsEmptyEventType() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.postEvent("j-1", "", null));
    }

    /**
     * {@code MCP_MESH_REGISTRY_URL} unset must surface a clean
     * MeshException with a useful message. Mirrors the Python
     * {@code _resolve_registry_url} and TS {@code resolveRegistryUrl}
     * error path.
     *
     * <p>Note: we can't easily unset the env var on the live process
     * here, so we drive {@code resolveRegistryUrl()} directly. The env
     * is preserved on entry/exit; if it's already unset, this exercises
     * the actual unset path; if set, we skip with a clean message.
     */
    @Test
    void resolveRegistryUrl_failsCleanlyWhenEnvUnset() {
        String existing = System.getenv("MCP_MESH_REGISTRY_URL");
        if (existing != null && !existing.isEmpty()) {
            // CI / dev shell already exports the env — can't directly
            // assert the unset path. We DO assert that resolveRegistryUrl
            // returns the same value (sanity check) so the test stays
            // useful in both shells.
            assertEquals(existing, MeshJobs.resolveRegistryUrl());
            return;
        }
        MeshException e = assertThrows(MeshException.class,
            MeshJobs::resolveRegistryUrl);
        assertTrue(e.getMessage().contains("MCP_MESH_REGISTRY_URL"),
            "error should reference the env var name; got: " + e.getMessage());
    }

    /**
     * Cache hit: a second {@code getOrCreateProxy} call for the same
     * key MUST return the same {@link JobProxy} instance — proves the
     * LRU lookup short-circuits before reconstructing the proxy. This
     * is the cache's reason for existence.
     */
    @Test
    void getOrCreateProxy_returnsSameInstanceForRepeatedKey() {
        JobProxy first = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-A");
        JobProxy second = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-A");
        assertSame(first, second,
            "second call with the same key must return the cached instance");
        assertEquals(1, MeshJobs.cacheSizeForTest(),
            "cache should hold exactly one entry");
    }

    /**
     * Cache miss on a distinct jobId allocates a new proxy. The cache
     * MUST then carry both entries.
     */
    @Test
    void getOrCreateProxy_distinctJobIdsAreCachedIndependently() {
        JobProxy a = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-A");
        JobProxy b = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-B");
        assertNotSame(a, b, "distinct jobIds must yield distinct proxies");
        assertEquals(2, MeshJobs.cacheSizeForTest());
    }

    /**
     * Cache miss on a distinct registryUrl ALSO allocates a new proxy
     * (the cache is keyed on the pair, not just jobId). This matters
     * for multi-registry setups (e.g. agent rebinding mid-process).
     */
    @Test
    void getOrCreateProxy_distinctRegistryUrlsAreCachedIndependently() {
        JobProxy a = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-A");
        JobProxy b = MeshJobs.getOrCreateProxy("http://example.org/registry", "job-A");
        assertNotSame(a, b);
        assertEquals(2, MeshJobs.cacheSizeForTest());
    }

    /**
     * LRU eviction: when the cache exceeds {@code MCP_MESH_JOBPROXY_CACHE_MAX},
     * the least-recently-used entry MUST be dropped. This test sets the
     * cap to 2 via a system-level env-var trick: we can't mutate the
     * process env table portably across JDKs, so we exercise the cap
     * indirectly by feeding the default cap of 256 a smaller number of
     * entries and confirming size monotonically grows up to the cap.
     *
     * <p>A direct eviction test would need to either set the env at
     * launch (via Surefire's {@code <environmentVariables>}) or
     * reflect into {@link System#getenv()} (fragile). We instead test
     * the eviction policy via {@code proxyCacheMax()} env parsing +
     * size-grows behaviour — the eviction logic itself is the
     * {@link java.util.LinkedHashMap} default which is well-tested in
     * the JDK.
     */
    @Test
    void getOrCreateProxy_cacheGrowsUpToCap() {
        for (int i = 0; i < 5; i++) {
            MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-" + i);
        }
        assertEquals(5, MeshJobs.cacheSizeForTest(),
            "default cap is 256 — 5 entries must all fit");
    }

    /**
     * {@code proxyCacheMax} fallback when env is unset or invalid —
     * confirms a typo'd / missing env doesn't silently disable the cache.
     */
    @Test
    void proxyCacheMax_fallsBackOnUnsetOrInvalidEnv() {
        // We can't portably mutate the env table here; we rely on the
        // CI shell NOT exporting MCP_MESH_JOBPROXY_CACHE_MAX in the
        // test environment (matches the Python / TS test setup).
        // If the env IS set, this test just confirms the helper returns
        // SOMETHING positive.
        int cap = MeshJobs.proxyCacheMax();
        assertTrue(cap > 0, "cache cap must always be positive; got " + cap);
        // The default is 256; if the env override is unset, we should
        // see the default. (If a CI env override is in play we skip the
        // strict-equality check.)
        String env = System.getenv("MCP_MESH_JOBPROXY_CACHE_MAX");
        if (env == null || env.isEmpty()) {
            assertEquals(256, cap, "default cap should be 256 when env unset");
        }
    }

    /**
     * The {@code MeshJobs} class is intended as a static-only utility —
     * its constructor must be private so callers can't instantiate it.
     * (Defence-in-depth; lints would catch this, but the test pins the
     * contract.)
     */
    @Test
    void meshJobs_isUtilityClass() {
        java.lang.reflect.Constructor<?>[] ctors = MeshJobs.class.getDeclaredConstructors();
        assertEquals(1, ctors.length, "exactly one ctor expected");
        assertTrue(java.lang.reflect.Modifier.isPrivate(ctors[0].getModifiers()),
            "ctor must be private");
    }

    /**
     * Type-tag and instance-of checks for the typed exception hierarchy —
     * verifies {@link JobNotFoundException} and {@link JobTerminalException}
     * both extend {@link MeshException}, so existing
     * {@code catch (MeshException ...)} handlers continue to catch them.
     */
    @Test
    void typedExceptions_extendMeshException() {
        JobNotFoundException nf = new JobNotFoundException("missing");
        JobTerminalException term = new JobTerminalException("done");
        assertTrue(nf instanceof MeshException);
        assertTrue(term instanceof MeshException);
        assertEquals("missing", nf.getMessage());
        assertEquals("done", term.getMessage());

        // Cause chaining works through both.
        RuntimeException cause = new RuntimeException("root");
        JobNotFoundException withCause = new JobNotFoundException("wrap", cause);
        assertSame(cause, withCause.getCause());
    }

    /**
     * Direct eviction-path coverage: populate the cache past the default
     * cap of 256 and verify that {@code removeEldestEntry} fires —
     * (a) cache size stays bounded at the cap,
     * (b) the evicted {@link JobProxy} is NOT closed — eviction only drops
     *     the cache's reference, exactly as Python and TypeScript do (issue
     *     #1592). A holder such as an {@link EventSubscription} returned by
     *     {@code subscribeEvents} still uses it; closing it failed that
     *     holder with "JobProxy is closed". The native handle is freed by
     *     {@code JobProxy}'s Cleaner once the last holder lets go
     *     ({@code JobProxyLifecycleTest}), and
     * (c) re-fetching the evicted key constructs a NEW proxy instance.
     *
     * <p>The JVM's env table is effectively read-only, so this exercises the
     * eviction path at the default cap (256) instead of lowering it to 2.
     * 257 lightweight FFI proxy allocations stay well under 1 second.
     */
    @Test
    void getOrCreateProxy_evictsLruWithoutClosingTheProxyAtCap() {
        int cap = MeshJobs.proxyCacheMax();
        assumeTrue(cap <= 1024,
            "Skipping eviction test: cache cap " + cap + " exceeds bound (1024). "
                + "Unset MCP_MESH_JOBPROXY_CACHE_MAX or set it <= 1024 to run.");
        // The LRU sentinel, held the way subscribeEvents holds it.
        JobProxy lru = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-lru");
        EventSubscription holder = new EventSubscription(lru, SubscribeOptions.defaults());
        for (int i = 0; i < cap - 1; i++) {
            MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "filler-" + i);
        }
        assertEquals(cap, MeshJobs.cacheSizeForTest(),
            "cache should be exactly at cap before the eviction-triggering put");
        JobProxy overflow = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "overflow");
        assertEquals(cap, MeshJobs.cacheSizeForTest(),
            "cache must stay bounded at cap after overflow");
        // The evicted proxy is still open for whoever holds it.
        assertFalse(lru.toString().contains("closed=true"),
            "eviction must not close a proxy a live holder still uses; toString reported: "
                + lru.toString());
        assertFalse(overflow.toString().contains("closed=true"));
        JobProxy refetch = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "job-lru");
        assertNotSame(lru, refetch,
            "re-fetching the evicted key must construct a new proxy instance");
        holder.close();
    }

    /**
     * Smoke check: postEvent's argument validation runs BEFORE the
     * registry URL resolution. A caller passing an invalid jobId must
     * see the IllegalArgumentException regardless of MCP_MESH_REGISTRY_URL.
     */
    @Test
    void postEvent_argValidationRunsBeforeEnvResolution() {
        // Even with the env set or unset, the IllegalArgumentException
        // wins because the null check is the first thing postEvent does.
        Map<String, Object> payload = Map.of("k", "v");
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.postEvent(null, "signal", payload));
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.postEvent("j", null, payload));
    }

    // -----------------------------------------------------------------
    // cancel / status / await — issue #1080 lifecycle facades
    // -----------------------------------------------------------------
    //
    // The FFI round-trip (cancel POST, status GET, await poll) needs a
    // live registry and is exercised by uc23_meshjob_java in the
    // integration suite. The unit tests below only assert the static-
    // facade layer that wraps the proxy: arg validation, env-var
    // resolution, and proxy-cache reuse. Mocking the JNR-FFI binding
    // here is not a pattern this codebase uses.

    @Test
    void cancel_rejectsNullJobId() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.cancel(null, "reason"));
        assertTrue(e.getMessage().toLowerCase().contains("jobid"),
            "error should mention jobId; got: " + e.getMessage());
    }

    @Test
    void cancel_rejectsEmptyJobId() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.cancel("", "reason"));
    }

    @Test
    void cancel_noArgOverloadRejectsNullJobId() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.cancel(null));
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.cancel(""));
    }

    @Test
    void status_rejectsNullJobId() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.status(null));
        assertTrue(e.getMessage().toLowerCase().contains("jobid"),
            "error should mention jobId; got: " + e.getMessage());
    }

    @Test
    void status_rejectsEmptyJobId() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.status(""));
    }

    @Test
    void await_rejectsNullJobId() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.await(null, 5.0));
        assertTrue(e.getMessage().toLowerCase().contains("jobid"),
            "error should mention jobId; got: " + e.getMessage());
    }

    @Test
    void await_rejectsEmptyJobId() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.await("", 5.0));
    }

    @Test
    void await_noArgOverloadRejectsNullJobId() {
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.await(null));
        assertThrows(IllegalArgumentException.class,
            () -> MeshJobs.await(""));
    }

    /**
     * {@code MCP_MESH_REGISTRY_URL} unset must surface a clean
     * MeshException through every lifecycle facade, exercising the same
     * {@code resolveRegistryUrl()} pre-flight that {@code postEvent}
     * uses.
     */
    @Test
    @DisabledIfEnvironmentVariable(named = "MCP_MESH_REGISTRY_URL", matches = ".+")
    void cancel_failsCleanlyWhenRegistryUrlUnset() {
        MeshException e = assertThrows(MeshException.class,
            () -> MeshJobs.cancel("job-x", "reason"));
        assertTrue(e.getMessage().contains("MCP_MESH_REGISTRY_URL"),
            "error should reference the env var name; got: " + e.getMessage());
    }

    @Test
    @DisabledIfEnvironmentVariable(named = "MCP_MESH_REGISTRY_URL", matches = ".+")
    void status_failsCleanlyWhenRegistryUrlUnset() {
        MeshException e = assertThrows(MeshException.class,
            () -> MeshJobs.status("job-x"));
        assertTrue(e.getMessage().contains("MCP_MESH_REGISTRY_URL"),
            "error should reference the env var name; got: " + e.getMessage());
    }

    @Test
    @DisabledIfEnvironmentVariable(named = "MCP_MESH_REGISTRY_URL", matches = ".+")
    void await_failsCleanlyWhenRegistryUrlUnset() {
        MeshException e = assertThrows(MeshException.class,
            () -> MeshJobs.await("job-x"));
        assertTrue(e.getMessage().contains("MCP_MESH_REGISTRY_URL"),
            "error should reference the env var name; got: " + e.getMessage());
    }

    /**
     * Cross-facade cache sharing (mirror of Python's W6 review test
     * from #1077): two different lifecycle facades targeting the same
     * jobId share a single cached proxy — the cache key is
     * {@code (registryUrl, jobId)} only, so {@code postEvent},
     * {@code cancel}, {@code status}, {@code await} and
     * {@code subscribeEvents} all reuse the same underlying
     * {@link JobProxy}.
     *
     * <p>We exercise the cache via {@code getOrCreateProxy} directly
     * because the facades' FFI call paths would fail without a live
     * registry — the cache lookup itself runs before any FFI call, so
     * this assertion holds without HTTP traffic.
     */
    @Test
    void getOrCreateProxy_sharesAcrossLifecycleFacades() {
        // First lookup — populates the cache.
        JobProxy first = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "shared-job");
        // Subsequent lookups for the same (registryUrl, jobId) — the
        // four facades (cancel, status, await, postEvent) all funnel
        // through getOrCreateProxy with the same key, so each call
        // returns the same instance.
        JobProxy second = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "shared-job");
        JobProxy third = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "shared-job");
        JobProxy fourth = MeshJobs.getOrCreateProxy(FAKE_REGISTRY, "shared-job");
        assertSame(first, second,
            "second facade lookup must reuse the cached proxy");
        assertSame(first, third,
            "third facade lookup must reuse the cached proxy");
        assertSame(first, fourth,
            "fourth facade lookup must reuse the cached proxy");
        assertEquals(1, MeshJobs.cacheSizeForTest(),
            "cache should hold exactly one entry across facade reuse");
    }

    /**
     * Substring-based translation of generic {@code MeshException} into
     * {@link JobNotFoundException} / {@link JobTerminalException} — the
     * same contract Python's {@code _translate_job_error} and TypeScript's
     * {@code translateJobError} implement against the registry's stable
     * error-message prefixes. The proxy-level
     * {@link JobProxy#cancel(String)}, {@link JobProxy#status()}, and
     * {@link JobProxy#await(double)} surfaces all raise a generic
     * {@code MeshException} on non-zero rc (unlike {@code sendEvent} /
     * {@code listEvents} which dispatch on rc directly); the facade
     * layer must close that gap.
     */
    @Test
    void translateJobError_classifiesByMessageSubstring() {
        // Pure MeshException with no marker → passes through unchanged.
        MeshException plain = new MeshException("registry unreachable");
        assertSame(plain, MeshJobs.translateJobError(plain));

        // "job not found" → JobNotFoundException, preserving cause.
        MeshException nf = new MeshException(
            "mesh_job_proxy_cancel failed: job not found: job-x");
        MeshException nfTranslated = MeshJobs.translateJobError(nf);
        assertNotSame(nf, nfTranslated);
        assertTrue(nfTranslated instanceof JobNotFoundException,
            "expected JobNotFoundException; got: " + nfTranslated.getClass());
        assertSame(nf, nfTranslated.getCause());
        assertEquals(nf.getMessage(), nfTranslated.getMessage());

        // "job is terminal" → JobTerminalException, preserving cause.
        MeshException term = new MeshException(
            "mesh_job_proxy_cancel failed: job is terminal: job-x");
        MeshException termTranslated = MeshJobs.translateJobError(term);
        assertNotSame(term, termTranslated);
        assertTrue(termTranslated instanceof JobTerminalException,
            "expected JobTerminalException; got: " + termTranslated.getClass());
        assertSame(term, termTranslated.getCause());
        assertEquals(term.getMessage(), termTranslated.getMessage());

        // Case-insensitive match — substring contract documents
        // lowercase comparison.
        MeshException upper = new MeshException("JOB NOT FOUND in registry");
        assertTrue(MeshJobs.translateJobError(upper) instanceof JobNotFoundException);

        // Already-typed exception passes through (no double-wrap).
        JobNotFoundException already = new JobNotFoundException("job not found: pre-typed");
        assertSame(already, MeshJobs.translateJobError(already));
        JobTerminalException alreadyTerm = new JobTerminalException("job is terminal: pre-typed");
        assertSame(alreadyTerm, MeshJobs.translateJobError(alreadyTerm));
    }
}
