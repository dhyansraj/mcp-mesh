package io.mcpmesh.spring.web;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Flow;
import java.util.concurrent.SubmissionPublisher;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("MeshSse.forward — bridges Flow.Publisher to SseEmitter")
class MeshSseTest {

    /**
     * Test double for SseEmitter that captures the rendered SSE frames sent
     * via {@code send(SseEventBuilder)} as joined strings (one entry per
     * {@code emitter.send(...)} call). Also tracks complete / completeWithError
     * for terminal-state assertions.
     */
    static final class CapturingEmitter extends SseEmitter {
        /** One entry per send() call, holding the concatenated SSE frame text. */
        final List<String> frames = new ArrayList<>();
        final AtomicBoolean completed = new AtomicBoolean(false);
        final AtomicReference<Throwable> errored = new AtomicReference<>();
        final CountDownLatch terminalLatch = new CountDownLatch(1);

        @Override
        public void send(SseEventBuilder builder) throws IOException {
            // Build the same Set<DataWithMediaType> the real emitter would emit
            // to the response stream, then concat the data fields into one text
            // so tests can assert on the full frame.
            Set<DataWithMediaType> events = builder.build();
            StringBuilder sb = new StringBuilder();
            for (DataWithMediaType e : events) {
                sb.append(e.getData());
            }
            frames.add(sb.toString());
        }

        @Override
        public void complete() {
            if (completed.compareAndSet(false, true)) {
                terminalLatch.countDown();
            }
        }

        @Override
        public void completeWithError(Throwable ex) {
            if (errored.compareAndSet(null, ex)) {
                completed.set(true);
                terminalLatch.countDown();
            }
        }

        boolean awaitTerminal(long ms) throws InterruptedException {
            return terminalLatch.await(ms, TimeUnit.MILLISECONDS);
        }
    }

    /**
     * Reflectively invoke ResponseBodyEmitter's internal timeoutCallback (which
     * runs every onTimeout(...) delegate registered via the public API). This is
     * what Spring's async dispatcher invokes when an async request times out.
     */
    private static void fireTimeout(SseEmitter emitter) throws Exception {
        Field f = ResponseBodyEmitter.class.getDeclaredField("timeoutCallback");
        f.setAccessible(true);
        Runnable cb = (Runnable) f.get(emitter);
        cb.run();
    }

    /** Same trick for the error callback. */
    @SuppressWarnings("unchecked")
    private static void fireError(SseEmitter emitter, Throwable t) throws Exception {
        Field f = ResponseBodyEmitter.class.getDeclaredField("errorCallback");
        f.setAccessible(true);
        java.util.function.Consumer<Throwable> cb = (java.util.function.Consumer<Throwable>) f.get(emitter);
        cb.accept(t);
    }

    /**
     * A simple Flow.Publisher that emits a fixed list and then completes (or
     * throws if errorAtIndex >= 0). Synchronous push: matches an "unbounded
     * demand" subscriber.
     */
    private static Flow.Publisher<String> publisherOf(List<String> items, int errorAtIndex, Throwable err) {
        return new Flow.Publisher<>() {
            @Override
            public void subscribe(Flow.Subscriber<? super String> sub) {
                sub.onSubscribe(new Flow.Subscription() {
                    final AtomicInteger called = new AtomicInteger();
                    @Override public void request(long n) {
                        if (called.getAndIncrement() != 0) return;
                        for (int i = 0; i < items.size(); i++) {
                            if (errorAtIndex == i) {
                                sub.onError(err);
                                return;
                            }
                            sub.onNext(items.get(i));
                        }
                        if (errorAtIndex == items.size()) {
                            sub.onError(err);
                        } else {
                            sub.onComplete();
                        }
                    }
                    @Override public void cancel() { called.set(-1); }
                });
            }
        };
    }

    @Test
    @DisplayName("forwards each chunk via send(...) and ends with [DONE] + complete()")
    void forwardsChunksAndDone() throws Exception {
        CapturingEmitter emitter = new CapturingEmitter();
        Flow.Publisher<String> pub = publisherOf(List.of("a", "b", "c"), -1, null);

        MeshSse.forward(emitter, pub);
        assertTrue(emitter.awaitTerminal(2000), "Expected emitter to terminate");

        // 3 data frames + 1 [DONE] frame = 4 total
        assertEquals(4, emitter.frames.size());
        // SSE wire format: "data:<sp><payload>\n\n"
        assertEquals("data:a\n\n", emitter.frames.get(0));
        assertEquals("data:b\n\n", emitter.frames.get(1));
        assertEquals("data:c\n\n", emitter.frames.get(2));
        assertEquals("data:[DONE]\n\n", emitter.frames.get(3));
        assertTrue(emitter.completed.get());
        assertNull(emitter.errored.get());
    }

    @Test
    @DisplayName("empty publisher still sends [DONE] and completes")
    void emptyPublisherEndsWithDone() throws Exception {
        CapturingEmitter emitter = new CapturingEmitter();
        MeshSse.forward(emitter, publisherOf(List.of(), -1, null));
        assertTrue(emitter.awaitTerminal(2000));

        assertEquals(1, emitter.frames.size());
        assertEquals("data:[DONE]\n\n", emitter.frames.get(0));
        assertTrue(emitter.completed.get());
    }

    @Test
    @DisplayName("on publisher error: writes event:error frame, NO [DONE], completeWithError")
    void onPublisherError() throws Exception {
        CapturingEmitter emitter = new CapturingEmitter();
        RuntimeException boom = new RuntimeException("upstream blew up");
        // Emit one chunk then error
        Flow.Publisher<String> pub = publisherOf(List.of("first"), 1, boom);

        MeshSse.forward(emitter, pub);
        assertTrue(emitter.awaitTerminal(2000));

        // Should have written: "first" frame, then a JSON error frame; NO [DONE]
        assertEquals(2, emitter.frames.size());
        assertEquals("data:first\n\n", emitter.frames.get(0));
        String errorFrame = emitter.frames.get(1);
        // The frame format is "event:error\ndata:<json>\n\n"
        assertTrue(errorFrame.startsWith("event:error\n"),
            "Expected error frame to start with 'event:error', got: " + errorFrame);
        assertTrue(errorFrame.contains("upstream blew up"),
            "Error frame should include exception message, got: " + errorFrame);
        assertTrue(errorFrame.contains("RuntimeException"),
            "Error frame should include exception type, got: " + errorFrame);
        assertFalse(emitter.frames.contains("data:[DONE]\n\n"),
            "[DONE] frame must not be sent when an error occurs");
        assertNotNull(emitter.errored.get(), "completeWithError should have been called");
        assertSame(boom, emitter.errored.get());
    }

    @Test
    @DisplayName("emitter onTimeout cancels the upstream subscription")
    void onTimeoutCancelsSubscription() throws Exception {
        CapturingEmitter emitter = new CapturingEmitter();

        AtomicBoolean cancelled = new AtomicBoolean(false);
        Flow.Publisher<String> pub = sub -> sub.onSubscribe(new Flow.Subscription() {
            @Override public void request(long n) { /* slow producer — no-op */ }
            @Override public void cancel() { cancelled.set(true); }
        });

        MeshSse.forward(emitter, pub);
        fireTimeout(emitter);

        assertTrue(cancelled.get(), "Timeout should have cancelled the upstream subscription");
    }

    @Test
    @DisplayName("emitter onError cancels the upstream subscription")
    void onEmitterErrorCancelsSubscription() throws Exception {
        CapturingEmitter emitter = new CapturingEmitter();

        AtomicBoolean cancelled = new AtomicBoolean(false);
        Flow.Publisher<String> pub = sub -> sub.onSubscribe(new Flow.Subscription() {
            @Override public void request(long n) { /* no-op */ }
            @Override public void cancel() { cancelled.set(true); }
        });

        MeshSse.forward(emitter, pub);
        fireError(emitter, new RuntimeException("client gone"));

        assertTrue(cancelled.get(), "Emitter error should have cancelled the upstream subscription");
    }

    @Test
    @DisplayName("rejects null arguments")
    void rejectsNulls() {
        SseEmitter emitter = new SseEmitter();
        Flow.Publisher<String> pub = publisherOf(List.of(), -1, null);
        assertThrows(NullPointerException.class, () -> MeshSse.forward(null, pub));
        assertThrows(NullPointerException.class, () -> MeshSse.forward(emitter, null));
    }

    @Test
    @DisplayName("works with java.util.concurrent.SubmissionPublisher (real reactive source)")
    void worksWithSubmissionPublisher() throws Exception {
        CapturingEmitter emitter = new CapturingEmitter();
        try (SubmissionPublisher<String> pub = new SubmissionPublisher<>()) {
            MeshSse.forward(emitter, pub);
            pub.submit("x");
            pub.submit("y");
            pub.submit("z");
            // try-with-resources will close() — that signals onComplete to the subscriber
        }
        assertTrue(emitter.awaitTerminal(2000));
        // Order: chunks then [DONE]. SubmissionPublisher delivers asynchronously
        // but FIFO per-subscriber, so we can assert the exact sequence.
        assertEquals(List.of(
            "data:x\n\n",
            "data:y\n\n",
            "data:z\n\n",
            "data:[DONE]\n\n"
        ), emitter.frames);
        assertTrue(emitter.completed.get());
    }
}
