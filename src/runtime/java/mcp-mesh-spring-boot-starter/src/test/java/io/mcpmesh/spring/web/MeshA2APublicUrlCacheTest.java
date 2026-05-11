package io.mcpmesh.spring.web;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link MeshA2APublicUrlCache} (spec §2.4 / §8.2).
 *
 * <p>Public URL caching:
 * <ul>
 *   <li>Stores registry-stamped public URLs keyed by {@code (path, skill_id)};</li>
 *   <li>Empty / blank / null {@code publicUrl} → REMOVES the cached entry,
 *       so the controller falls back to the local-form URL (matches Python's
 *       {@code update_public_url_cache} which drops the entry when the
 *       registry stops stamping it);</li>
 *   <li>Thread-safe — backed by {@link java.util.concurrent.ConcurrentHashMap}
 *       so concurrent put/get from the heartbeat thread + request threads
 *       never lose updates.</li>
 * </ul>
 */
@DisplayName("MeshA2APublicUrlCache — registry public URL caching (spec §2.4 / §8.2)")
class MeshA2APublicUrlCacheTest {

    private MeshA2APublicUrlCache cache;

    @BeforeEach
    void setUp() {
        cache = new MeshA2APublicUrlCache();
    }

    /** put/get round-trip — the canonical happy path. */
    @Test
    @DisplayName("put/get round-trip preserves the registry-stamped public URL")
    void putGetRoundTrip() {
        cache.put("/agents/report", "generate-report",
            "https://agents.acme.com/agents/report");

        assertEquals("https://agents.acme.com/agents/report",
            cache.get("/agents/report", "generate-report"));
    }

    /** Distinct (path, skillId) pairs do NOT collide. */
    @Test
    @DisplayName("Distinct (path, skillId) keys do not collide")
    void distinctKeysDoNotCollide() {
        cache.put("/agents/x", "skill-a", "https://x/a");
        cache.put("/agents/x", "skill-b", "https://x/b");
        cache.put("/agents/y", "skill-a", "https://y/a");

        assertEquals("https://x/a", cache.get("/agents/x", "skill-a"));
        assertEquals("https://x/b", cache.get("/agents/x", "skill-b"));
        assertEquals("https://y/a", cache.get("/agents/y", "skill-a"));
        assertEquals(3, cache.size());
    }

    /** Missing key → null (caller falls back to local-form URL). */
    @Test
    @DisplayName("get() returns null for missing key (controller falls back to local URL)")
    void missingKeyReturnsNull() {
        assertNull(cache.get("/agents/missing", "skill"));
        cache.put("/agents/x", "skill", "https://x");
        assertNull(cache.get("/agents/x", "different-skill"),
            "Same path but different skillId is a different key — must miss");
    }

    /** Empty publicUrl REMOVES any cached entry — matches Python helper
     *  {@code update_public_url_cache} dropping the entry. */
    @Test
    @DisplayName("Empty publicUrl removes cached entry (Python parity)")
    void emptyUrlRemovesEntry() {
        cache.put("/agents/x", "skill", "https://x");
        assertEquals(1, cache.size());

        cache.put("/agents/x", "skill", "");
        assertNull(cache.get("/agents/x", "skill"),
            "Empty publicUrl MUST remove the cached entry — matches Python's "
                + "update_public_url_cache behavior when registry stops stamping");
        assertEquals(0, cache.size());
    }

    /** Null publicUrl also removes the entry. */
    @Test
    @DisplayName("Null publicUrl removes cached entry")
    void nullUrlRemovesEntry() {
        cache.put("/agents/x", "skill", "https://x");
        cache.put("/agents/x", "skill", null);
        assertNull(cache.get("/agents/x", "skill"));
        assertEquals(0, cache.size());
    }

    /** Null/empty for a key that was never present is a no-op (does not crash). */
    @Test
    @DisplayName("Null/empty for absent key is a no-op")
    void clearAbsentKeyIsNoOp() {
        assertDoesNotThrow(() -> cache.put("/agents/none", "skill", ""));
        assertDoesNotThrow(() -> cache.put("/agents/none", "skill", null));
        assertEquals(0, cache.size());
    }

    /** clear() drops every entry. */
    @Test
    @DisplayName("clear() drops every entry")
    void clearEmptiesCache() {
        cache.put("/a", "s1", "https://a");
        cache.put("/b", "s2", "https://b");
        assertEquals(2, cache.size());

        cache.clear();
        assertEquals(0, cache.size());
        assertNull(cache.get("/a", "s1"));
        assertNull(cache.get("/b", "s2"));
    }

    /** Replace existing entry — last write wins. */
    @Test
    @DisplayName("Put on existing key replaces the URL (last write wins)")
    void putReplacesExisting() {
        cache.put("/agents/x", "skill", "https://old.example.com");
        cache.put("/agents/x", "skill", "https://new.example.com");
        assertEquals("https://new.example.com",
            cache.get("/agents/x", "skill"));
        assertEquals(1, cache.size());
    }

    /** Null skillId treated as empty string (defensive — some heartbeat
     *  responses may omit it). */
    @Test
    @DisplayName("Null skillId treated as empty string for key purposes (defensive)")
    void nullSkillIdNormalisedToEmpty() {
        cache.put("/agents/x", null, "https://x");
        assertEquals("https://x", cache.get("/agents/x", null));
        assertEquals("https://x", cache.get("/agents/x", ""),
            "Null and empty skillId must normalise to the same cache key");
    }

    /** Concurrent put/get safety — multiple threads must not lose updates
     *  or observe torn state. ConcurrentHashMap-backed; this stress-tests
     *  the contract. */
    @Test
    @DisplayName("Concurrent put + get from many threads does not lose updates")
    void concurrentPutGetIsSafe() throws InterruptedException {
        final int threads = 16;
        final int opsPerThread = 200;
        ExecutorService exec = Executors.newFixedThreadPool(threads);
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(threads);
        AtomicInteger errors = new AtomicInteger(0);

        for (int t = 0; t < threads; t++) {
            final int threadId = t;
            exec.submit(() -> {
                try {
                    start.await();
                    for (int i = 0; i < opsPerThread; i++) {
                        String path = "/agents/" + (i % 4);
                        String skill = "skill-" + threadId;
                        cache.put(path, skill, "https://t" + threadId + "/" + i);
                        // Read back our own write — must see something non-null.
                        String got = cache.get(path, skill);
                        if (got == null) {
                            errors.incrementAndGet();
                        }
                    }
                } catch (Exception e) {
                    errors.incrementAndGet();
                } finally {
                    done.countDown();
                }
            });
        }
        start.countDown();
        assertTrue(done.await(15, TimeUnit.SECONDS),
            "Concurrent stress test must complete within 15s");
        exec.shutdownNow();

        assertEquals(0, errors.get(),
            "Concurrent put/get must not lose own-thread writes (got " + errors.get() + " misses)");
        // Final state: each (path, skill) pair has exactly one value.
        // 4 paths × 16 threads = 64 distinct keys.
        assertEquals(64, cache.size(),
            "Final cache size must equal the number of distinct (path, skillId) keys");
    }
}
