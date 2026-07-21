package com.example.maxiterations;

import io.mcpmesh.FilterMode;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * DEDICATED minimal Java consumer for tc47 — issue #1356 (PR #1359).
 *
 * <p>Java consumer-side {@code max_iterations} forwarding is BRAND NEW in that
 * PR ({@code MeshLlmAgentProxy} now puts {@code model_params.max_iterations} on
 * the wire when the cap was explicitly configured) and has no end-to-end
 * coverage at all — the Java unit tests mock the provider side, and the Python
 * unit tests mock the consumer side. This agent closes the cross-runtime gap:
 * JAVA consumer -> PYTHON provider-managed agentic loop.
 *
 * <p>WHY A DEDICATED AGENT (not the shared {@code llm-mesh-agent} analyst): the
 * same reason tc44 has one. A confirmed pre-existing bug (#1141) makes
 * per-funcId LLM-provider proxies bind UNRELIABLY when a single agent declares
 * MANY {@code @MeshLlm} functions. This agent declares EXACTLY ONE, the normal
 * case, so its proxy binds reliably and the tc measures only the thing under
 * test.
 *
 * <p>WHY {@code maxIterations = 1} AND NOTHING ELSE: with the Java consumer
 * forwarding the cap, the Python provider's loop must stop after ONE tool round.
 * The tc measures that by reading iteration-probe-agent's invocation counter,
 * NOT by matching the provider's "Maximum tool call iterations reached"
 * sentinel — issue #1355 is going to replace that sentinel with a structured
 * signal.
 *
 * <p>NOTE ON THE JAVA-LOCAL LOOP: {@code maxIterations} also caps this agent's
 * OWN loop. That is not what makes the count come out at 1 — the Java proxy
 * sends {@code _mesh_endpoint} with each tool, so the PYTHON provider executes
 * the tools inside ITS loop and returns a finished message; the Java-local loop
 * makes exactly one provider call either way. If the cap were NOT forwarded, the
 * Python loop would run the ticket to completion (4 tool rounds) inside that
 * single provider call. The tc additionally asserts the provider-managed path
 * was taken, so the count cannot be explained by the Java-local cap.
 *
 * <p>RETURN TYPE IS {@code String}: when the loop is capped the provider returns
 * its exhaustion payload instead of a completed answer; a structured record
 * return type would turn that into an unrelated deserialization error rather
 * than the observable under test.
 */
@MeshAgent(
    name = "max-iterations-java",
    version = "1.0.0",
    description = "Dedicated single-@MeshLlm Java consumer forwarding maxIterations=1 (issue #1356)",
    port = 9047
)
@SpringBootApplication
public class MaxIterationsAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(MaxIterationsAgentApplication.class);

    /** Returned when the LLM proxy has not bound yet — the tc's readiness poll keys off this. */
    static final String UNAVAILABLE = "LLM_UNAVAILABLE";

    public static void main(String[] args) {
        log.info("Starting Max-Iterations Java Consumer (single @MeshLlm)...");
        SpringApplication.run(MaxIterationsAgentApplication.class, args);
    }

    /**
     * The ONLY {@code @MeshLlm} function on this agent: drive the probe ticket
     * with an explicit cap of ONE iteration.
     *
     * <p>The filter selects ONLY {@code capability="iteration_probe"}
     * ({@code advance_ticket}). The probe agent's {@code probe_count} and
     * {@code probe_reset} tools sit on different capabilities, so the model can
     * neither read nor reset the counter it is being measured with.
     */
    @MeshLlm(
        providerSelector = @Selector(capability = "llm", tags = {"+claude", "+provider"}),
        // THE THING UNDER TEST: explicitly configured, therefore forwarded as
        // model_params.max_iterations to the Python provider-managed loop.
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
        capability = "runTicket",
        description = "Drive the probe ticket using the advance_ticket tool (capped at 1 iteration)",
        tags = {"llm", "ticket", "iteration", "java"}
    )
    public String runTicket(
        @Param(value = "ctx", description = "Ticket context") TicketContext ctx,
        MeshLlmAgent llm
    ) {
        log.info("Running ticket: {}", ctx.instruction());

        if (llm == null || !llm.isAvailable()) {
            log.warn("LLM provider not available yet");
            return UNAVAILABLE;
        }

        try {
            String result = llm.request()
                .user(ctx.instruction())
                .maxTokens(2048)
                .temperature(0.0)
                .generate();

            var meta = llm.request().lastMeta();
            if (meta != null) {
                log.info("Ticket run completed: {} iterations, {}ms latency",
                    meta.iterations(), meta.latencyMs());
            }

            return result;

        } catch (Exception e) {
            log.error("Ticket run failed: {}", e.getMessage(), e);
            return "ERROR: " + e.getMessage();
        }
    }

    /**
     * Ticket context record.
     */
    public record TicketContext(String instruction) {}
}
