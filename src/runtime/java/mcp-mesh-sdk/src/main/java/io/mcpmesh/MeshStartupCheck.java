package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as this agent's startup check (RFC #1502).
 *
 * <p>{@link MeshHealthCheck} answers "can I serve <b>right now</b>?" — a transient
 * answer, and a failing one only pauses the heartbeat so the registry stops
 * selecting this agent until it recovers. {@code @MeshStartupCheck} answers the
 * other question: "is this agent configured such that it can <b>ever</b> serve?"
 * A missing API key is not going to fix itself, and without this hook it looks
 * exactly like a vendor outage — the agent sits unregistered, the pod runs, and
 * nothing is loud.
 *
 * <h2>What ships today (RFC #1502 step 1)</h2>
 *
 * <p>The verdict is served from {@code GET}/{@code HEAD} {@code /startupz}, and
 * that is the whole effect: a failing check answers 503 there. Nothing else
 * changes — the agent is not withdrawn, the heartbeat is untouched, and
 * {@code /livez} and {@code /ready} answer exactly as they did.
 *
 * <p>The agent Helm chart's {@code startupProbe} still points at {@code /livez},
 * so nothing acts on the verdict yet. Repointing it at {@code /startupz} is
 * step 2, and it is what this hook exists for: a pod whose startup check never
 * passes then never becomes ready, never registers, and ends up in
 * {@code CrashLoopBackOff} — which is the point.
 *
 * <p>The message on a failing verdict is served to any caller who can reach the
 * pod, so name the setting that is missing without including its value:
 * {@code "ANTHROPIC_API_KEY is not set"}, never the key itself.
 *
 * <h2>Shape</h2>
 *
 * <p>Annotate exactly one no-argument method on a Spring bean. The return type
 * must be either {@code boolean} ({@code true} = start, {@code false} = do not)
 * or {@link MeshHealth}, whose {@link MeshHealthStatus#HEALTHY} is the only
 * status that passes. Anything else fails the boot with an actionable message
 * rather than being silently ignored.
 *
 * <p>Escaped as {@code &#64;} rather than wrapped in {@code {@code ...}}: an
 * annotation is the first token on those lines, and Javadoc reads a leading
 * {@code @} as a block tag even inside a code block.
 *
 * <pre>
 * &#64;Component
 * public class VendorStartup {
 *
 *     &#64;MeshStartupCheck
 *     public boolean configured() {
 *         return System.getenv("ANTHROPIC_API_KEY") != null;
 *     }
 * }
 * </pre>
 *
 * <h2>The verdict rules are the OPPOSITE of {@link MeshHealthCheck}'s</h2>
 *
 * <p>A check that <b>throws</b> FAILS the probe here; the same throw from a
 * health check is {@link MeshHealthStatus#DEGRADED} and keeps the agent
 * heartbeating. Both rules follow from the same principle applied to different
 * questions: a buggy probe must not withdraw a working provider from a mesh
 * that may have no other one, but an indeterminate answer at boot is not a
 * reason to let a possibly-misconfigured agent through. The cost of being wrong
 * is also asymmetric — a false failure crash-loops one pod that was never
 * serving, a false pass silently registers a broken one.
 *
 * <p>For the same reason there is no partial credit: {@code DEGRADED},
 * {@code UNKNOWN} and an unrecognized return all fail.
 *
 * <h2>Every agent type, and no cache</h2>
 *
 * <p>Unlike {@link MeshHealthCheck}, this hook is honoured on {@code api}
 * (route) and {@code a2a} agents too. It never withdraws a running fan-out
 * point; it only stops a misconfigured one from coming up, and a gateway with a
 * broken config should never come up.
 *
 * <p>The check runs once per request. A {@code startupProbe} stops polling after
 * its first success, so it runs a handful of times at most and there is nothing
 * to cache — hence no {@code ttlSeconds} here. Keep it fast: the chart's probe
 * {@code timeoutSeconds} is 5.
 *
 * @see MeshHealthCheck
 * @see MeshHealth
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface MeshStartupCheck {
}
