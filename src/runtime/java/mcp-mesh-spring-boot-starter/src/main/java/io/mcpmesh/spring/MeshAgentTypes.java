package io.mcpmesh.spring;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Set;

/**
 * The "is this agent a gateway" rule, in ONE place (issue #1488).
 *
 * <p>It now has a single consumer: the heartbeat in
 * {@link MeshHealthCheckScheduler}. {@link MeshHealthController} was the second
 * — a gateway with a failing check kept heartbeating (correct) but answered 503
 * on {@code /ready}, so Kubernetes dropped it from its Service endpoints, the
 * same outcome the exemption exists to prevent reached by another route. RFC
 * #1502 closed that route for every agent type rather than for gateways alone:
 * readiness reports the mesh runtime and never the verdict, so the controller
 * has no rule to ask about.
 *
 * <p>This stays a shared type rather than folding back into the scheduler
 * because the exemption is a property of the agent type, not of the heartbeat,
 * and the next mechanism that needs it must find the rule rather than write a
 * second copy.
 */
final class MeshAgentTypes {

    private static final Logger log = LoggerFactory.getLogger(MeshAgentTypes.class);

    /**
     * Agent types whose own health verdict must never take them out of service.
     *
     * <p>A route ({@code api}) or A2A agent is a fan-out point that many
     * requests enter through: withdrawing a provider is correct, withdrawing the
     * gateway takes the application down — and removing it from Service
     * endpoints takes it down harder, because the gateway is where requests
     * enter. Python encodes the same asymmetry by giving its API and A2A
     * pipelines no health-refresh loop at all, and TypeScript by ignoring
     * {@code healthCheck} in {@code express.ts}.
     */
    private static final Set<String> GATEWAY_TYPES = Set.of("api", "a2a");

    private MeshAgentTypes() {
    }

    static boolean isGateway(String agentType) {
        return GATEWAY_TYPES.contains(agentType);
    }

    /**
     * The agent's declared type, or {@code ""} when it cannot be read.
     *
     * <p>Never throws: {@code runtime} is a lazy bean proxy that can raise while
     * the context is still coming up, and neither a probe nor the health-check
     * thread may fail because of it. An unknown type is treated as NOT a
     * gateway, which is the pre-existing behaviour for every other agent.
     */
    static String agentTypeOf(MeshRuntime runtime) {
        try {
            if (runtime != null && runtime.getAgentSpec() != null) {
                String type = runtime.getAgentSpec().getAgentType();
                return type == null ? "" : type;
            }
        } catch (Exception e) {
            log.debug("Could not read agent type: {}", e.toString());
        }
        return "";
    }
}
