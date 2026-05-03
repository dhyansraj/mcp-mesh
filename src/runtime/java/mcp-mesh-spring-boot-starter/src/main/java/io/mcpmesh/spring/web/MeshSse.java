package io.mcpmesh.spring.web;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.concurrent.Flow;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * SSE streaming helper for Spring MVC route handlers.
 *
 * <p>Subscribes a {@link Flow.Publisher Flow.Publisher&lt;String&gt;} to a Spring
 * {@link SseEmitter}, writing each chunk as an SSE {@code data:} frame and
 * terminating with {@code data: [DONE]\n\n}. Designed to be called from inside a
 * {@link MeshRoute @MeshRoute} controller method that returns the emitter.
 *
 * <p>Wire format mirrors the Python {@code mesh.route} SSE adapter and the
 * TypeScript {@code mesh.sseStream} helper:
 * <ul>
 *   <li>{@code data: <chunk>\n\n} per item</li>
 *   <li>{@code data: [DONE]\n\n} terminator on normal completion</li>
 *   <li>{@code event: error\ndata: <json>\n\n} on per-chunk error</li>
 * </ul>
 *
 * <p>If the consumer disconnects mid-stream (e.g. browser navigates away), the
 * SseEmitter's {@code onTimeout} / {@code onError} / {@code onCompletion}
 * callbacks fire and the upstream {@link Flow.Subscription Flow.Subscription} is
 * cancelled so the underlying HTTP connection is released.
 *
 * <h2>Example usage</h2>
 * <pre>{@code
 * @PostMapping("/plan")
 * @MeshRoute(dependencies = { @MeshDependency(capability = "trip_planner") })
 * public SseEmitter plan(
 *         @RequestBody Map<String, Object> body,
 *         @MeshInject("trip_planner") McpMeshTool<String> planner) {
 *     SseEmitter emitter = new SseEmitter(0L); // no timeout
 *     MeshSse.forward(emitter, planner.stream(body));
 *     return emitter;
 * }
 * }</pre>
 */
public final class MeshSse {

    private static final Logger log = LoggerFactory.getLogger(MeshSse.class);

    private MeshSse() {
        // utility class
    }

    /**
     * Subscribe {@code publisher} to {@code emitter}, forwarding each chunk as a
     * {@code data: <chunk>\n\n} SSE frame, terminating with {@code [DONE]} on
     * normal completion, or an {@code event: error} frame on failure.
     *
     * <p>The method returns immediately after subscribing — the actual writing
     * happens asynchronously on whatever thread the publisher delivers
     * {@code onNext} signals on. The caller should return the {@link SseEmitter}
     * from their controller method so Spring streams it to the client.
     *
     * @param emitter   The Spring SSE emitter to write to
     * @param publisher The publisher whose chunks should be forwarded
     */
    public static void forward(SseEmitter emitter, Flow.Publisher<String> publisher) {
        if (emitter == null) throw new NullPointerException("emitter");
        if (publisher == null) throw new NullPointerException("publisher");

        ForwardingSubscriber sub = new ForwardingSubscriber(emitter);
        // Wire emitter terminal callbacks to subscription cancel BEFORE subscribing,
        // so a disconnection that races with the first chunk is still handled.
        emitter.onTimeout(sub::cancelSubscription);
        emitter.onError((Throwable t) -> sub.cancelSubscription());
        emitter.onCompletion(sub::cancelSubscription);

        publisher.subscribe(sub);
    }

    /**
     * Build an SSE {@code event: error} frame payload (a JSON object with
     * {@code error} and {@code type} fields). Mirrors the TypeScript
     * implementation so browser-side parsers behave identically.
     */
    private static String buildErrorJson(Throwable t) {
        String msg = t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName();
        String type = t.getClass().getSimpleName();
        // Manual JSON encoding to avoid pulling Jackson into MeshSse (keeps the
        // utility class self-contained). Escape the two characters that matter
        // for SSE/JSON safety inside a single-line string.
        return "{\"error\":\"" + escapeJson(msg) + "\",\"type\":\"" + escapeJson(type) + "\"}";
    }

    private static String escapeJson(String s) {
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        return sb.toString();
    }

    /**
     * Subscriber implementation that forwards chunks to an SseEmitter.
     *
     * <p>Backpressure: requests {@link Long#MAX_VALUE} up-front because SseEmitter
     * does not expose a flow-control mechanism — it buffers internally and lets
     * the servlet container apply TCP-level back pressure. This matches the
     * semantics of every other SSE bridge (Express, Flask, etc.).
     */
    private static final class ForwardingSubscriber implements Flow.Subscriber<String> {
        private final SseEmitter emitter;
        private final AtomicReference<Flow.Subscription> subscriptionRef = new AtomicReference<>();
        private final AtomicBoolean terminated = new AtomicBoolean(false);

        ForwardingSubscriber(SseEmitter emitter) {
            this.emitter = emitter;
        }

        void cancelSubscription() {
            Flow.Subscription s = subscriptionRef.get();
            if (s != null) {
                try {
                    s.cancel();
                } catch (Throwable t) {
                    log.debug("Subscription.cancel threw: {}", t.getMessage());
                }
            }
        }

        @Override
        public void onSubscribe(Flow.Subscription subscription) {
            if (!subscriptionRef.compareAndSet(null, subscription)) {
                // Already subscribed — per spec, cancel the duplicate
                subscription.cancel();
                return;
            }
            subscription.request(Long.MAX_VALUE);
        }

        @Override
        public void onNext(String chunk) {
            if (terminated.get()) return;
            try {
                emitter.send(SseEmitter.event().data(chunk));
            } catch (IOException | IllegalStateException e) {
                // Client disconnected or emitter already completed — cancel upstream
                if (terminated.compareAndSet(false, true)) {
                    cancelSubscription();
                    try {
                        emitter.completeWithError(e);
                    } catch (Throwable ignored) {
                        // emitter may already be terminal
                    }
                }
            }
        }

        @Override
        public void onError(Throwable throwable) {
            if (!terminated.compareAndSet(false, true)) return;
            try {
                emitter.send(SseEmitter.event()
                    .name("error")
                    .data(buildErrorJson(throwable)));
            } catch (IOException | IllegalStateException e) {
                log.debug("Failed to write SSE error frame: {}", e.getMessage());
            } finally {
                try {
                    emitter.completeWithError(throwable);
                } catch (Throwable ignored) {
                    // emitter may already be terminal
                }
            }
        }

        @Override
        public void onComplete() {
            if (!terminated.compareAndSet(false, true)) return;
            try {
                emitter.send(SseEmitter.event().data("[DONE]"));
            } catch (IOException | IllegalStateException e) {
                log.debug("Failed to write SSE [DONE] frame: {}", e.getMessage());
            } finally {
                try {
                    emitter.complete();
                } catch (Throwable ignored) {
                    // emitter may already be terminal
                }
            }
        }
    }
}
