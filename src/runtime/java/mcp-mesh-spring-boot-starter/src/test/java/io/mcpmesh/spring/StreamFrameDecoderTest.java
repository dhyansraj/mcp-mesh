package io.mcpmesh.spring;

import io.mcpmesh.types.MeshLlmStopReason;
import io.mcpmesh.types.MeshMaxIterationsException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Flow;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * First Java streaming-frame coverage (issue #1369).
 *
 * <p>Exercises {@link StreamFrameDecoder#decode} — the consumer-side unwrap of the
 * typed {@code _mesh_frame} streaming envelope emitted by a Python/TypeScript
 * streaming provider after #1355. Mirrors the Python {@code _stream_mesh_delegated}
 * and TypeScript {@code stream()} consumer tests:
 * <ul>
 *   <li>{@code chunk} frames → unwrapped {@code content} strings, in order</li>
 *   <li>exhaustion {@code end} frame → {@code onError(MeshMaxIterationsException)};
 *       frame NOT emitted</li>
 *   <li>plain {@code end} frame → {@code onComplete}; frame NOT emitted</li>
 *   <li>collision: a {@code chunk} whose {@code content} is literally the
 *       end-frame JSON is emitted as text and does NOT terminate</li>
 *   <li>unframed passthrough: a raw non-frame chunk (and one frame-shaped under a
 *       DIFFERENT scheme, e.g. {@code {"type":"end"}}) is emitted verbatim</li>
 * </ul>
 */
@DisplayName("StreamFrameDecoder — _mesh_frame consumer unwrap (issue #1369)")
class StreamFrameDecoderTest {

    // Wire shapes — byte-match the Python/TS producer.
    private static final String CHUNK_HELLO = "{\"_mesh_frame\":\"chunk\",\"content\":\"Hello\"}";
    private static final String CHUNK_WORLD = "{\"_mesh_frame\":\"chunk\",\"content\":\", world!\"}";
    private static final String CHUNK_TRAILING = "{\"_mesh_frame\":\"chunk\",\"content\":\"trailing\"}";
    private static final String END_NORMAL = "{\"_mesh_frame\":\"end\"}";
    private static final String END_EXHAUSTION =
        "{\"_mesh_frame\":\"end\",\"stop_reason\":\"max_iterations\"}";

    private static final int MAX_ITERATIONS = 7;

    // -------------------------------------------------------------------------
    // Test helpers
    // -------------------------------------------------------------------------

    /**
     * A cold, synchronous, single-subscriber {@code Flow.Publisher<String>} that
     * emits {@code items} respecting demand — stands in for
     * {@link McpHttpClient#streamTool}'s upstream.
     */
    private static Flow.Publisher<String> source(List<String> items) {
        return source(items, new AtomicBoolean(false));
    }

    /**
     * As {@link #source(List)} but records upstream cancellation into
     * {@code cancelledFlag} so a test can assert the decoder invoked
     * {@code cancel()} on the upstream (e.g. the swallow-{@code end} path).
     */
    private static Flow.Publisher<String> source(List<String> items, AtomicBoolean cancelledFlag) {
        return subscriber -> subscriber.onSubscribe(new Flow.Subscription() {
            private int idx = 0;
            private boolean completed = false;

            @Override
            public void request(long n) {
                if (cancelledFlag.get() || completed) {
                    return;
                }
                for (long i = 0; i < n && idx < items.size(); i++) {
                    subscriber.onNext(items.get(idx++));
                    if (cancelledFlag.get()) {
                        return;
                    }
                }
                if (idx >= items.size() && !completed) {
                    completed = true;
                    subscriber.onComplete();
                }
            }

            @Override
            public void cancel() {
                cancelledFlag.set(true);
            }
        });
    }

    /** Collect Flow.Publisher chunks blocking, throwing on onError. */
    private static List<String> collect(Flow.Publisher<String> publisher) throws Exception {
        ConcurrentLinkedQueue<String> chunks = new ConcurrentLinkedQueue<>();
        CompletableFuture<Throwable> done = new CompletableFuture<>();
        publisher.subscribe(new Flow.Subscriber<>() {
            @Override public void onSubscribe(Flow.Subscription s) { s.request(Long.MAX_VALUE); }
            @Override public void onNext(String item) { chunks.add(item); }
            @Override public void onError(Throwable t) { done.complete(t); }
            @Override public void onComplete() { done.complete(null); }
        });
        Throwable err = done.get(10, TimeUnit.SECONDS);
        if (err != null) {
            if (err instanceof RuntimeException re) throw re;
            throw new RuntimeException(err);
        }
        return new ArrayList<>(chunks);
    }

    private Flow.Publisher<String> decoded(String... frames) {
        return StreamFrameDecoder.decode(source(List.of(frames)), MAX_ITERATIONS);
    }

    // -------------------------------------------------------------------------
    // Constant parity
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("frame constants byte-match Python/TypeScript")
    void frameConstantsByteMatch() {
        assertEquals("_mesh_frame", MeshLlmStopReason.FRAME_KEY);
        assertEquals("chunk", MeshLlmStopReason.FRAME_CHUNK);
        assertEquals("end", MeshLlmStopReason.FRAME_END);
        assertEquals("max_iterations", MeshLlmStopReason.STOP_REASON_MAX_ITERATIONS);
    }

    // -------------------------------------------------------------------------
    // Tests
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("chunk frames → unwrapped content strings, in order; end frame not emitted")
    void chunkFramesUnwrappedInOrder() throws Exception {
        List<String> out = collect(decoded(CHUNK_HELLO, CHUNK_WORLD, END_NORMAL));
        assertEquals(List.of("Hello", ", world!"), out);
    }

    @Test
    @DisplayName("exhaustion end frame → onError(MeshMaxIterationsException); frame not emitted")
    void exhaustionFrameTerminatesWithTypedError() {
        MeshMaxIterationsException ex = assertThrows(
            MeshMaxIterationsException.class,
            () -> collect(decoded(CHUNK_HELLO, END_EXHAUSTION))
        );
        assertEquals(MAX_ITERATIONS, ex.getMaxAllowed());
        assertEquals(MAX_ITERATIONS, ex.getIterationCount());
    }

    @Test
    @DisplayName("exhaustion end frame: chunks before it are still delivered, then error")
    void exhaustionDeliversPriorChunksThenErrors() {
        ConcurrentLinkedQueue<String> chunks = new ConcurrentLinkedQueue<>();
        CompletableFuture<Throwable> done = new CompletableFuture<>();
        decoded(CHUNK_HELLO, CHUNK_WORLD, END_EXHAUSTION).subscribe(new Flow.Subscriber<>() {
            @Override public void onSubscribe(Flow.Subscription s) { s.request(Long.MAX_VALUE); }
            @Override public void onNext(String item) { chunks.add(item); }
            @Override public void onError(Throwable t) { done.complete(t); }
            @Override public void onComplete() { done.complete(null); }
        });
        Throwable err = done.join();
        assertInstanceOf(MeshMaxIterationsException.class, err);
        assertEquals(List.of("Hello", ", world!"), new ArrayList<>(chunks),
            "prior chunk content is delivered; the exhaustion frame itself is never emitted");
    }

    @Test
    @DisplayName("plain end frame → completes normally; frame not emitted")
    void plainEndCompletesNormally() throws Exception {
        List<String> out = collect(decoded(CHUNK_HELLO, END_NORMAL));
        assertEquals(List.of("Hello"), out);
    }

    @Test
    @DisplayName("collision: a chunk whose content IS the end-frame JSON is emitted as text, no throw")
    void collisionChunkContentLooksLikeEndFrame() throws Exception {
        // A framed text delta whose content is literally an exhaustion end-frame
        // JSON string. Parsed as a `chunk`, its content is yielded verbatim — the
        // reserved _mesh_frame discriminator (chunk) wins; no control collision.
        String innerEnd = END_EXHAUSTION;
        String collisionChunk = "{\"_mesh_frame\":\"chunk\",\"content\":"
            + jsonString(innerEnd) + "}";

        List<String> out = collect(decoded(collisionChunk, END_NORMAL));
        assertEquals(List.of(innerEnd), out,
            "the inner end-frame JSON is delivered as plain text, NOT interpreted as a control frame");
    }

    @Test
    @DisplayName("unframed passthrough: raw text and a DIFFERENT-scheme frame are emitted verbatim")
    void unframedChunksPassThroughVerbatim() throws Exception {
        // 1. Plain raw text (not JSON at all).
        // 2. A JSON object that is frame-shaped under a DIFFERENT scheme
        //    ({"type":"end"}) — it lacks the reserved _mesh_frame key, so it is
        //    NOT a control frame and must be forwarded verbatim.
        String rawText = "just some raw text";
        String otherScheme = "{\"type\":\"end\"}";

        List<String> out = collect(decoded(rawText, otherScheme, END_NORMAL));
        assertEquals(List.of(rawText, otherScheme), out);
    }

    @Test
    @DisplayName("chunk frame with null content coerces to empty string")
    void nullContentCoercedToEmpty() throws Exception {
        String chunkNullContent = "{\"_mesh_frame\":\"chunk\",\"content\":null}";
        List<String> out = collect(decoded(chunkNullContent, END_NORMAL));
        assertEquals(List.of(""), out);
    }

    @Test
    @DisplayName("bounded demand: request(1) yields exactly one item at a time (1:1 backpressure)")
    void boundedDemandYieldsOneAtATime() {
        // All other tests request Long.MAX_VALUE; this proves demand maps 1:1 so
        // downstream backpressure is actually honored through the interposed sub.
        List<String> chunks = new ArrayList<>();
        AtomicReference<Flow.Subscription> subRef = new AtomicReference<>();
        CompletableFuture<Throwable> done = new CompletableFuture<>();

        StreamFrameDecoder.decode(source(List.of(CHUNK_HELLO, CHUNK_WORLD, END_NORMAL)), MAX_ITERATIONS)
            .subscribe(new Flow.Subscriber<>() {
                @Override public void onSubscribe(Flow.Subscription s) { subRef.set(s); }
                @Override public void onNext(String item) { chunks.add(item); }
                @Override public void onError(Throwable t) { done.complete(t); }
                @Override public void onComplete() { done.complete(null); }
            });

        Flow.Subscription sub = subRef.get();
        assertNotNull(sub, "downstream received an interposed subscription");
        assertTrue(chunks.isEmpty(), "no items before any demand is signaled");

        sub.request(1);
        assertEquals(List.of("Hello"), chunks, "exactly one item after request(1)");
        assertFalse(done.isDone(), "stream not yet terminated after one bounded request");

        sub.request(1);
        assertEquals(List.of("Hello", ", world!"), chunks, "exactly one more item after next request(1)");

        // Drain the terminal end frame.
        sub.request(1);
        assertNull(done.getNow(new RuntimeException("not done")),
            "plain end frame completes normally after the final request");
        assertEquals(List.of("Hello", ", world!"), chunks, "end frame itself is never emitted");
    }

    @Test
    @DisplayName("trailing items after an exhaustion end frame are dropped; upstream is cancelled")
    void trailingItemsAfterExhaustionEndAreDropped() {
        AtomicBoolean upstreamCancelled = new AtomicBoolean(false);
        List<String> items = List.of(CHUNK_HELLO, CHUNK_WORLD, END_EXHAUSTION, CHUNK_TRAILING);

        ConcurrentLinkedQueue<String> chunks = new ConcurrentLinkedQueue<>();
        CompletableFuture<Throwable> done = new CompletableFuture<>();
        StreamFrameDecoder.decode(source(items, upstreamCancelled), MAX_ITERATIONS)
            .subscribe(new Flow.Subscriber<>() {
                @Override public void onSubscribe(Flow.Subscription s) { s.request(Long.MAX_VALUE); }
                @Override public void onNext(String item) { chunks.add(item); }
                @Override public void onError(Throwable t) { done.complete(t); }
                @Override public void onComplete() { done.complete(null); }
            });

        Throwable err = done.join();
        assertInstanceOf(MeshMaxIterationsException.class, err);
        assertEquals(List.of("Hello", ", world!"), new ArrayList<>(chunks),
            "leading chunks delivered in order; trailing chunk after end is NOT emitted");
        assertTrue(upstreamCancelled.get(), "decoder cancelled the upstream when it swallowed the end frame");
    }

    @Test
    @DisplayName("trailing items after a plain end frame are dropped; upstream is cancelled")
    void trailingItemsAfterPlainEndAreDropped() throws Exception {
        AtomicBoolean upstreamCancelled = new AtomicBoolean(false);
        List<String> items = List.of(CHUNK_HELLO, END_NORMAL, CHUNK_TRAILING);

        ConcurrentLinkedQueue<String> chunks = new ConcurrentLinkedQueue<>();
        CompletableFuture<Throwable> done = new CompletableFuture<>();
        StreamFrameDecoder.decode(source(items, upstreamCancelled), MAX_ITERATIONS)
            .subscribe(new Flow.Subscriber<>() {
                @Override public void onSubscribe(Flow.Subscription s) { s.request(Long.MAX_VALUE); }
                @Override public void onNext(String item) { chunks.add(item); }
                @Override public void onError(Throwable t) { done.complete(t); }
                @Override public void onComplete() { done.complete(null); }
            });

        assertNull(done.get(10, TimeUnit.SECONDS), "plain end frame completes normally");
        assertEquals(List.of("Hello"), new ArrayList<>(chunks),
            "one chunk then onComplete; trailing chunk after end is NOT emitted");
        assertTrue(upstreamCancelled.get(), "decoder cancelled the upstream when it swallowed the end frame");
    }

    /** Minimal JSON string encoder (quotes + escapes) for building collision fixtures. */
    private static String jsonString(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                default -> sb.append(c);
            }
        }
        return sb.append('"').toString();
    }
}
