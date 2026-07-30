package io.mcpmesh.spring;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Locale;

/**
 * Dependency-injection validation for the positional pairing contract
 * (issue #1401).
 *
 * <p>Positional pairing is only safe when a dependency-count / slot-count
 * mismatch is <i>reported</i>. Without that, declaring one dependency too many
 * silently drops it ({@code depIndexToSlot = -1}) and declaring one too few
 * silently injects {@code null} — the two failure modes that make a reordered
 * declaration list indistinguishable from a correct one. Python has had this
 * check since {@code validate_mesh_dependencies}; this is its Java counterpart,
 * with the same default posture and the same opt-in knob.
 *
 * <h2>Posture</h2>
 * <ul>
 *   <li><b>Default: WARN.</b> Mesh DI is permissive by design — a mismatched
 *       arity still boots, still registers, and still serves.</li>
 *   <li><b>{@code MCP_MESH_STRICT_DI=true}: boot failure.</b> Same env var,
 *       same truthy spellings and the same message text as Python, so a team
 *       that wants rigor gets it in every runtime with one variable.</li>
 * </ul>
 *
 * <h2>Three things this deliberately does not count</h2>
 * <ul>
 *   <li><b>Non-pairable declared dependencies.</b> Arity is measured against
 *       {@link MeshPositionalBinder.Binding#pairableDepCount()}, never
 *       {@code capabilities.size()}. A {@code @MeshTool}'s declared list is the
 *       explicit {@code @Selector} prefix <i>plus</i> the RFC-1280
 *       {@code @MeshService} view-edge suffix, and view edges own no injectable
 *       parameter by construction. Counting the full list would report every
 *       view edge as a phantom excess dependency.</li>
 *   <li><b>{@code MeshLlmAgent} parameters.</b> They are invisible to arity
 *       checking <i>by construction, not by oversight</i>: {@code @MeshLlm} has
 *       no {@code dependencies} member, so an LLM agent slot lives in a
 *       separate index space and consumes nothing from the declared list. It is
 *       correct that neither side of this comparison counts it.</li>
 *   <li><b>The producer-side {@code MeshJob} parameter, which is OPTIONALLY
 *       declared.</b> {@code MeshJob} is two different things depending on
 *       {@code @MeshTool(task = ...)}. On a <i>consumer</i> it is a submitter
 *       proxy for a remote {@code task = true} capability and must be backed by
 *       a declared dependency — that capability is what the submitter binds to.
 *       On the <i>producer</i> — the {@code task = true} tool itself — it is the
 *       inbound job's controller, filled by the dispatch path, and
 *       {@code JobsRuntimeManager.wireConsumers} skips it outright
 *       ({@code if (meta.task()) continue}). Producers therefore usually declare
 *       nothing for it, yet a producer <i>may</i> still declare a capability at
 *       the job slot's index, and the pairing table honours the resulting index
 *       skew. Both counts are sound, so the caller passes a
 *       {@code minSlots}/{@code maxSlots} range rather than an exact count.</li>
 * </ul>
 *
 * @see MeshPositionalBinder
 */
public final class MeshDiValidator {

    private static final Logger log = LoggerFactory.getLogger(MeshDiValidator.class);

    /** Opt-in strictness knob, shared with Python and TypeScript. */
    public static final String STRICT_DI_ENV = "MCP_MESH_STRICT_DI";

    private MeshDiValidator() {}

    /**
     * Whether {@code MCP_MESH_STRICT_DI} is truthy.
     *
     * <p>Truthy spellings match {@link MeshSchemaSupport#clusterStrictEnabled()}
     * ({@code 1} / {@code true} / {@code yes}, case- and whitespace-insensitive)
     * so mesh's two strictness knobs never disagree about what "on" means.
     *
     * @return true when strict DI is enabled
     */
    public static boolean strictDiEnabled() {
        String v = System.getenv(STRICT_DI_ENV);
        if (v == null) {
            return false;
        }
        String lc = v.trim().toLowerCase(Locale.ROOT);
        return "1".equals(lc) || "true".equals(lc) || "yes".equals(lc);
    }

    /**
     * Report a dependency-count / injectable-slot-count mismatch, applying the
     * ambient {@link #strictDiEnabled()} policy.
     *
     * @param site     the declaration site, e.g. {@code "@MeshTool"}
     * @param binding  the pairing table produced by {@link MeshPositionalBinder}
     * @param minSlots lowest sound declared-dependency count
     * @param maxSlots highest sound declared-dependency count; equals
     *                 {@code minSlots} unless the site has an optionally-declared
     *                 slot (see the class javadoc on {@code MeshJob})
     * @throws IllegalStateException when the count is out of range and strict DI
     *         is on
     */
    public static void checkArity(
            String site, MeshPositionalBinder.Binding binding, int minSlots, int maxSlots) {
        checkArity(site, binding, minSlots, maxSlots, strictDiEnabled());
    }

    /**
     * Report a dependency-count / injectable-slot-count mismatch under an
     * explicit policy (the seam tests use — env vars are not settable in-process).
     *
     * @param site     the declaration site, e.g. {@code "@MeshTool"}
     * @param binding  the pairing table produced by {@link MeshPositionalBinder}
     * @param minSlots lowest sound declared-dependency count
     * @param maxSlots highest sound declared-dependency count
     * @param strict   true to throw instead of warning
     * @return the diagnostic that was emitted, or null when the arity is sound
     * @throws IllegalStateException when the count is out of range and
     *         {@code strict}
     */
    public static String checkArity(
            String site,
            MeshPositionalBinder.Binding binding,
            int minSlots,
            int maxSlots,
            boolean strict) {

        int declared = binding.pairableDepCount();
        int min = Math.max(0, Math.min(minSlots, maxSlots));
        int max = Math.max(min, maxSlots);
        if (declared >= min && declared <= max) {
            return null;
        }

        String message = arityMessage(site, binding, declared, min, max, strict);
        if (strict) {
            throw new IllegalStateException(message);
        }
        log.warn("{}", message);
        return message;
    }

    /**
     * Build the mismatch diagnostic. Modelled on Python's
     * {@code validate_mesh_dependencies} message: name the counts, name each
     * slot, state the positional rule explicitly, and prescribe the fix.
     */
    private static String arityMessage(
            String site,
            MeshPositionalBinder.Binding binding,
            int declared,
            int min,
            int max,
            boolean strict) {

        StringBuilder sb = new StringBuilder();
        sb.append(site).append(' ').append(signatureOf(binding))
            .append(" declares ").append(plural(declared, "dependency", "dependencies"))
            .append(" but has ")
            .append(plural(max, "dependency-backed injectable parameter",
                "dependency-backed injectable parameters"));
        if (min != max) {
            sb.append(", of which ").append(max - min)
                .append(" need not be declared");
        }
        sb.append(". Each injectable slot needs a corresponding dependency; ")
            .append("dependencies[i] pairs with the i-th injectable parameter in signature order ")
            .append("(parameter names are never matched). ");

        if (declared > max) {
            sb.append("The surplus declared ")
                .append(declared - max == 1 ? "dependency is" : "dependencies are")
                .append(" resolved and advertised but injected nowhere. ");
        } else {
            sb.append("The surplus ")
                .append(min - declared == 1 ? "parameter is" : "parameters are")
                .append(" injected null. ");
        }

        sb.append("Fix: declare ");
        if (min == max) {
            sb.append("exactly ").append(plural(max, "entry", "entries"));
        } else {
            sb.append(min).append(" or ").append(plural(max, "entry", "entries"));
        }
        sb.append(" in dependencies = {...}, or add/remove injectable parameters ")
            .append("(McpMeshTool / MeshJob) so the counts match.\n")
            .append(binding.describe());

        if (!strict) {
            sb.append("\n  Set ").append(STRICT_DI_ENV)
                .append("=true to fail startup on this instead of warning.");
        }
        return sb.toString();
    }

    private static String signatureOf(MeshPositionalBinder.Binding binding) {
        StringBuilder sb = new StringBuilder();
        sb.append(binding.method().getDeclaringClass().getName()).append('.')
            .append(binding.method().getName()).append('(');
        Class<?>[] types = binding.method().getParameterTypes();
        for (int i = 0; i < types.length; i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(types[i].getSimpleName());
        }
        return sb.append(')').toString();
    }

    private static String plural(int n, String singular, String pluralForm) {
        return n + " " + (n == 1 ? singular : pluralForm);
    }
}
