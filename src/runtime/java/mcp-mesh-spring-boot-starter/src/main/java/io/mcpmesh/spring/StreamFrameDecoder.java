package io.mcpmesh.spring;

import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.types.MeshLlmStopReason;
import io.mcpmesh.types.MeshMaxIterationsException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;
import java.util.concurrent.Flow;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Decodes the typed {@code _mesh_frame} streaming envelope (issue #1369) on the
 * consumer side of a mesh-delegated LLM stream.
 *
 * <p>After #1355 a Python/TypeScript streaming provider frames EVERY chunk as a
 * typed JSON string keyed by the reserved {@code _mesh_frame} discriminator:
 * <ul>
 *   <li>text delta            → {@code {"_mesh_frame":"chunk","content":"<delta>"}}</li>
 *   <li>terminal, normal      → {@code {"_mesh_frame":"end"}}</li>
 *   <li>terminal, exhaustion  → {@code {"_mesh_frame":"end","stop_reason":"max_iterations"}}</li>
 * </ul>
 *
 * <p>This mirrors Python's {@code _stream_mesh_delegated} unwrap and TypeScript's
 * {@code stream()}: {@link #decode} wraps the raw upstream {@code Flow.Publisher<String>}
 * (from {@link McpHttpClient#streamTool}) and transforms it so the caller sees
 * plain text — never raw frame JSON — and observes streaming exhaustion as a
 * typed {@code onError(MeshMaxIterationsException)} terminal signal.
 *
 * <p>Java has no streaming <b>producer</b> (deferred, #1223); this is
 * consumer-side only, so only the frame parser + decode transform live here (no
 * encoder). The parser mirrors how {@code MeshLlmAgentProxy.extractStopReason}
 * unwraps the buffered envelope's JSON.
 */
final class StreamFrameDecoder {

    private static final Logger log = LoggerFactory.getLogger(StreamFrameDecoder.class);
    private static final ObjectMapper objectMapper = MeshObjectMappers.create();

    private StreamFrameDecoder() {}

    /**
     * Parse a stream chunk into a typed frame map, or {@code null}.
     *
     * <p>Reserved-key guard, byte-for-byte equivalent to Python's
     * {@code parse_stream_frame} and TypeScript's {@code parseStreamFrame}: a
     * well-formed frame is a JSON object carrying the reserved
     * {@code _mesh_frame} discriminator set to a recognized frame type
     * ({@code "chunk"} or {@code "end"}). Anything else — {@code null}, invalid
     * JSON, a JSON value that isn't an object, an object missing
     * {@code _mesh_frame}, or one whose {@code _mesh_frame} is unrecognized —
     * returns {@code null} so the consumer can apply a defensive passthrough
     * fallback. Because the discriminator is {@code _mesh_}-namespaced, an
     * UNFRAMED raw model delta that merely looks frame-ish (e.g. a literal
     * {@code {"type":"end"}} in the model's own text) does NOT match and is
     * passed through verbatim rather than misread as a control/text frame.
     */
    @SuppressWarnings("unchecked")
    static Map<String, Object> parseStreamFrame(String chunk) {
        if (chunk == null) {
            return null;
        }
        Object obj;
        try {
            obj = objectMapper.readValue(chunk, Object.class);
        } catch (JacksonException e) {
            return null;
        }
        if (!(obj instanceof Map)) {
            return null;
        }
        Map<String, Object> map = (Map<String, Object>) obj;
        Object type = map.get(MeshLlmStopReason.FRAME_KEY);
        if (!MeshLlmStopReason.FRAME_CHUNK.equals(type)
                && !MeshLlmStopReason.FRAME_END.equals(type)) {
            return null;
        }
        return map;
    }

    /**
     * Wrap {@code upstream} so downstream subscribers observe the decoded stream:
     * {@code chunk} frames unwrapped to their {@code content} text (null/non-string
     * coerced to {@code ""}), a plain {@code end} frame as {@code onComplete}, an
     * exhaustion {@code end} frame as {@code onError(MeshMaxIterationsException)},
     * and any non-frame chunk passed through verbatim (defensive fallback for an
     * unframed/old provider).
     *
     * <p>The frame→text mapping is 1:1 for every non-terminal frame and terminal
     * {@code end} frames end the stream, so downstream demand maps directly onto
     * upstream demand (1:1), preserving backpressure and ordering without
     * rebuffering. Downstream never touches the upstream {@code Subscription}
     * directly: it is handed a thin interposing {@code Subscription} so the decoder
     * remains the sole, serialized owner of the upstream (Reactive Streams §2.7).
     *
     * @param upstream      the raw String-chunk publisher (e.g. {@code streamTool})
     * @param maxIterations the configured loop cap, carried into the typed error
     */
    static Flow.Publisher<String> decode(Flow.Publisher<String> upstream, int maxIterations) {
        return subscriber -> upstream.subscribe(new DecodingSubscriber(subscriber, maxIterations));
    }

    /**
     * Interposing subscriber: decodes each upstream frame and re-signals to the
     * downstream subscriber.
     *
     * <p>Reactive Streams §2.7 requires the Subscriber to be the sole, serialized
     * caller of its upstream {@code Subscription}. To honor that, downstream is
     * handed a thin interposing {@code Subscription} (built in {@link #onSubscribe})
     * rather than the raw upstream one, so downstream {@code request}/{@code cancel}
     * and the decoder's own swallow-{@code end} cancel all funnel through a single
     * point. Cancel is idempotently serialized via {@link #cancelled}; the terminal
     * transition is serialized via {@link #terminated} (an {@link AtomicBoolean}, so
     * a downstream-thread §3.9 error can't race an upstream terminal). The terminal
     * flag is set before any downstream {@code onError}/{@code onComplete}, and
     * post-terminal upstream signals are ignored.
     */
    private static final class DecodingSubscriber implements Flow.Subscriber<String> {

        private final Flow.Subscriber<? super String> downstream;
        private final int maxIterations;
        private volatile Flow.Subscription upstream;
        private final AtomicBoolean terminated = new AtomicBoolean(false);
        private final AtomicBoolean cancelled = new AtomicBoolean(false);

        DecodingSubscriber(Flow.Subscriber<? super String> downstream, int maxIterations) {
            this.downstream = downstream;
            this.maxIterations = maxIterations;
        }

        @Override
        public void onSubscribe(Flow.Subscription subscription) {
            this.upstream = subscription;
            // Interpose a thin Subscription so downstream never touches the upstream
            // directly (§2.7). Non-terminal frames map 1:1 to text, so downstream
            // demand forwards straight to upstream demand, preserving backpressure.
            downstream.onSubscribe(new Flow.Subscription() {
                @Override
                public void request(long n) {
                    if (n <= 0) {
                        // §3.9: a non-positive request must signal onError with an
                        // IllegalArgumentException; do not forward it upstream.
                        if (terminated.compareAndSet(false, true)) {
                            cancelUpstream();
                            downstream.onError(new IllegalArgumentException(
                                "Reactive Streams §3.9: request amount must be positive, was " + n));
                        }
                        return;
                    }
                    if (!cancelled.get()) {
                        subscription.request(n);
                    }
                }

                @Override
                public void cancel() {
                    cancelUpstream();
                }
            });
        }

        /** Single, idempotent, serialized cancel path to the upstream (§2.7). */
        private void cancelUpstream() {
            Flow.Subscription u = upstream;
            if (u != null && cancelled.compareAndSet(false, true)) {
                u.cancel();
            }
        }

        @Override
        public void onNext(String chunk) {
            if (terminated.get()) {
                return;
            }
            Map<String, Object> frame = parseStreamFrame(chunk);
            if (frame == null) {
                // Not a well-formed frame — a provider that isn't yet framing
                // (older provider mid-rollout, or a bug). Degrade to plain
                // passthrough rather than crashing.
                downstream.onNext(chunk);
                return;
            }
            if (MeshLlmStopReason.FRAME_END.equals(frame.get(MeshLlmStopReason.FRAME_KEY))) {
                if (!terminated.compareAndSet(false, true)) {
                    return;
                }
                // Route through the single serialized cancel path so downstream and
                // the decoder never contend on the upstream Subscription.
                cancelUpstream();
                if (MeshLlmStopReason.STOP_REASON_MAX_ITERATIONS.equals(frame.get("stop_reason"))) {
                    log.warn("stream(mesh): provider signaled max_iterations exhaustion (max={})",
                        maxIterations);
                    downstream.onError(new MeshMaxIterationsException(maxIterations, maxIterations));
                } else {
                    // Normal terminal frame — complete cleanly, never forward it.
                    downstream.onComplete();
                }
                return;
            }
            // Text delta: unwrap and forward the plain content. Coerce a null /
            // non-string content to "" so a malformed frame can't leak a
            // non-String into the stream.
            Object content = frame.get("content");
            if (content instanceof String s) {
                downstream.onNext(s);
            } else {
                log.debug("stream(mesh): chunk frame content missing or non-string ({}); "
                        + "coercing to empty string",
                    content == null ? "null" : content.getClass().getSimpleName());
                downstream.onNext("");
            }
        }

        @Override
        public void onError(Throwable throwable) {
            if (!terminated.compareAndSet(false, true)) {
                return;
            }
            downstream.onError(throwable);
        }

        @Override
        public void onComplete() {
            if (!terminated.compareAndSet(false, true)) {
                return;
            }
            downstream.onComplete();
        }
    }
}
