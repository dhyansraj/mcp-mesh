package com.example.streamgateway;

import io.mcpmesh.FilterMode;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.spring.web.MeshSse;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Streaming max-iterations Java gateway — issue #1369 (PR #1371).
 *
 * <p>WHAT #1369 FIXED (the streaming half of Java's #1355 participation): a
 * Python streaming provider frames every stream chunk as a typed
 * {@code _mesh_frame} JSON string. The Java streaming consumer
 * ({@code MeshLlmAgentProxy.streamGenerate()}) used to be a raw
 * {@code Flow.Publisher<String>} passthrough, so it (a) leaked the frame JSON to
 * callers and (b) never surfaced streaming exhaustion. #1371 wraps the stream in
 * {@code StreamFrameDecoder}, which unwraps {@code chunk} frames to plain
 * content and, on an {@code end} frame carrying
 * {@code stop_reason == "max_iterations"}, terminates the publisher with
 * {@code onError(MeshMaxIterationsException)} — which {@link MeshSse#forward}
 * renders as {@code event: error\ndata: {"type":"MeshMaxIterationsException"}}
 * and OMITS {@code data: [DONE]}.
 *
 * <p>WHY A CAPTURE-INTO-HOLDER SHAPE: the mesh {@code MeshLlmAgent} proxy is
 * only injected by the framework into a {@code @MeshTool}+{@code @MeshLlm}
 * method's parameter — {@code @MeshRoute}/{@code @MeshDependency} inject
 * {@code McpMeshTool} proxies (mesh tools/producers), NOT a {@code MeshLlmAgent}
 * (Java has no streaming <em>producer</em>, deferred #1223). So the single
 * {@code @MeshLlm} bind tool captures its injected proxy into a shared holder
 * and the plain SSE routes forward {@code proxy.stream(...)} through
 * {@code MeshSse.forward}. This still exercises the exact #1369 code path
 * ({@code streamGenerate} → {@code StreamFrameDecoder} → {@code MeshSse}).
 *
 * <p>SINGLE {@code @MeshLlm} (issue #1141): the gateway declares EXACTLY ONE
 * {@code @MeshLlm} function so its per-funcId proxy binds reliably (multiple
 * {@code @MeshLlm} on one agent bind unreliably, #1141). Both routes share that
 * one proxy: the CAPPED route uses the annotation's {@code maxIterations = 1}
 * (forces exhaustion against the 4-step probe ticket); the NORMAL route raises
 * the cap per-call via {@code modelParams("max_iterations", 10)} so the loop can
 * complete and terminate with {@code [DONE]}.
 */
@MeshAgent(
    name = "stream-gateway-java",
    version = "1.0.0",
    description = "Java streaming @MeshLlm consumer + SSE gateway (issue #1369)",
    port = 9060
)
@SpringBootApplication
public class StreamGatewayApplication {

    private static final Logger log = LoggerFactory.getLogger(StreamGatewayApplication.class);

    public static void main(String[] args) {
        log.info("Starting Streaming Max-Iterations Java Gateway (single @MeshLlm)...");
        SpringApplication.run(StreamGatewayApplication.class, args);
    }

    /** Ticket context record (the bind tool ignores it; present so @MeshLlm has a contextParam). */
    public record TicketContext(String instruction) {}
}

/**
 * Process-wide holder for the single injected {@link MeshLlmAgent} proxy.
 *
 * <p>Shared between {@link TicketLlmBinder} (which captures the framework-
 * injected proxy) and {@link StreamController} (which forwards its stream).
 */
@Component
class LlmProxyHolder {
    private final AtomicReference<MeshLlmAgent> ref = new AtomicReference<>();

    void set(MeshLlmAgent agent) {
        ref.set(agent);
    }

    MeshLlmAgent get() {
        return ref.get();
    }

    boolean isBound() {
        MeshLlmAgent a = ref.get();
        return a != null && a.isAvailable();
    }
}

/**
 * The gateway's ONLY {@code @MeshLlm} function: a readiness/bind tool.
 *
 * <p>Called by the test via {@code meshctl call bindProxy} until it returns
 * {@code PROXY_BOUND}. On each call it captures the framework-injected
 * {@link MeshLlmAgent} proxy into {@link LlmProxyHolder} so the SSE routes can
 * forward its stream. It does NOT invoke the LLM, so it never increments the
 * probe counter (the counter is reset right before the measured capped call).
 */
@Component
class TicketLlmBinder {

    private static final Logger log = LoggerFactory.getLogger(TicketLlmBinder.class);

    /** Returned until the LLM proxy has bound — the test's readiness poll keys off this. */
    static final String UNAVAILABLE = "LLM_UNAVAILABLE";

    private final LlmProxyHolder holder;

    TicketLlmBinder(LlmProxyHolder holder) {
        this.holder = holder;
    }

    @MeshLlm(
        // Streaming provider variant: the ai.mcpmesh.stream tag is REQUIRED in
        // Java to resolve the Python provider's auto-generated
        // process_chat_stream tool.
        providerSelector = @Selector(capability = "llm", tags = {"+claude", "+provider", "ai.mcpmesh.stream"}),
        // Annotation cap = 1 -> forwarded as model_params.max_iterations on the
        // streaming path. The CAPPED route uses this directly; the NORMAL route
        // overrides it up via per-call modelParams.
        maxIterations = 1,
        systemPrompt = "You are a ticket-processing agent. You MUST use the advance_ticket "
            + "tool to make progress on a ticket; never guess, fabricate or predict a token, "
            + "a step number or a final_code. Call advance_ticket AT MOST ONCE per turn and "
            + "wait for its result before calling it again - the token for the next call only "
            + "exists in the previous call's response. Keep going until the tool reports status "
            + "COMPLETE, then reply with the final_code it returned.",
        contextParam = "ctx",
        filter = @Selector(capability = "iteration_probe"),
        filterMode = FilterMode.ALL,
        maxTokens = 2048,
        temperature = 0.0
    )
    @MeshTool(
        capability = "bindProxy",
        description = "Bind (capture) the streaming LLM proxy; returns PROXY_BOUND once resolved",
        tags = {"llm", "stream", "iteration", "java"}
    )
    public String bindProxy(
        @Param(value = "ctx", description = "Ticket context (unused by the bind tool)")
        StreamGatewayApplication.TicketContext ctx,
        MeshLlmAgent llm
    ) {
        if (llm == null || !llm.isAvailable()) {
            log.warn("Streaming LLM proxy not available yet");
            return UNAVAILABLE;
        }
        holder.set(llm);
        log.info("Captured streaming LLM proxy@{} into holder", System.identityHashCode(llm));
        return "PROXY_BOUND";
    }
}

/**
 * SSE gateway: forwards the captured streaming LLM proxy over Spring
 * {@link SseEmitter} via {@link MeshSse#forward}.
 *
 * <ul>
 *   <li>{@code POST /stream/capped} — annotation {@code maxIterations = 1}
 *       governs → the 4-step probe ticket forces exhaustion →
 *       {@code event: error} + {@code MeshMaxIterationsException}, no
 *       {@code [DONE]}.</li>
 *   <li>{@code POST /stream/normal} — per-call {@code max_iterations = 10}
 *       lets the loop complete → text chunks + {@code data: [DONE]}, no
 *       error frame.</li>
 * </ul>
 */
@RestController
class StreamController {

    private static final Logger log = LoggerFactory.getLogger(StreamController.class);

    /** Standard 4-round probe-ticket instruction (matches tc45/tc46/tc47). */
    private static final String DEFAULT_INSTRUCTION =
        "Process ticket ABC-1 to completion. Begin by calling advance_ticket with token "
        + "\"START\". Each response gives you a next_token; call advance_ticket again with it. "
        + "Keep going until the tool reports status COMPLETE, then reply with the final_code.";

    private final LlmProxyHolder holder;

    StreamController(LlmProxyHolder holder) {
        this.holder = holder;
    }

    private static String instructionFrom(Map<String, Object> body) {
        if (body != null && body.get("instruction") instanceof String s && !s.isBlank()) {
            return s;
        }
        return DEFAULT_INSTRUCTION;
    }

    private void emitUnavailable(SseEmitter emitter) {
        try {
            emitter.send(SseEmitter.event()
                .name("error")
                .data("{\"error\":\"LLM proxy not bound\",\"type\":\"ProxyUnavailable\"}"));
            emitter.complete();
        } catch (Exception e) {
            emitter.completeWithError(e);
        }
    }

    /**
     * CAPPED stream: uses the annotation's maxIterations=1. Against the 4-step
     * probe ticket the provider-managed streaming loop exhausts after one tool
     * round; #1369 surfaces that as MeshMaxIterationsException → SSE error frame.
     */
    @PostMapping("/stream/capped")
    public SseEmitter streamCapped(@RequestBody(required = false) Map<String, Object> body) {
        SseEmitter emitter = new SseEmitter(0L);
        MeshLlmAgent llm = holder.get();
        if (llm == null || !llm.isAvailable()) {
            emitUnavailable(emitter);
            return emitter;
        }
        String instruction = instructionFrom(body);
        log.info("Forwarding /stream/capped (max_iterations=1)");
        // stream(prompt) forwards the annotation cap (=1) on the wire.
        MeshSse.forward(emitter, llm.stream(instruction));
        return emitter;
    }

    /**
     * NORMAL stream: raises the cap per-call to 10 via the model_params escape
     * hatch so the loop can drive the ticket to COMPLETE and terminate cleanly
     * with [DONE] (regression control for the error-frame path).
     */
    @PostMapping("/stream/normal")
    public SseEmitter streamNormal(@RequestBody(required = false) Map<String, Object> body) {
        SseEmitter emitter = new SseEmitter(0L);
        MeshLlmAgent llm = holder.get();
        if (llm == null || !llm.isAvailable()) {
            emitUnavailable(emitter);
            return emitter;
        }
        String instruction = instructionFrom(body);
        log.info("Forwarding /stream/normal (max_iterations=10)");
        MeshSse.forward(
            emitter,
            llm.request()
                .user(instruction)
                .modelParams(Map.of("max_iterations", 10))
                .streamGenerate());
        return emitter;
    }
}
