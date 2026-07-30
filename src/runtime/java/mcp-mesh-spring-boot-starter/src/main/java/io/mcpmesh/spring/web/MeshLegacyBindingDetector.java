package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshDiValidator;
import io.mcpmesh.spring.MeshPositionalBinder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Boot-time guard for the positional dependency contract (issue #1401): it
 * checks {@code @MeshInject} as an <b>assertion</b>, and reports handlers still
 * shaped for the name-based binding that {@code @MeshRoute} / {@code @MeshA2A}
 * used before 3.4.
 *
 * <h2>The contract this enforces</h2>
 *
 * <p>Every mesh injection site now pairs dependencies with parameters
 * <i>positionally</i>: the Nth declared dependency binds to the Nth injectable
 * parameter in signature order, and <b>parameter names are never consulted</b>.
 * {@code @MeshTool} always worked this way; as of 3.4 so do {@code @MeshRoute}
 * and {@code @MeshA2A}, matching Python and TypeScript.
 *
 * <h2>Two checks, two severities</h2>
 *
 * <p>For each handler it enumerates the injectable slots in signature order
 * ({@link MeshInjectableSlots}) and pairs them positionally with the declared
 * dependency list ({@link MeshPositionalBinder}). Then, per slot:
 *
 * <ul>
 *   <li><b>{@code @MeshInject} carries a value → ERROR unless it names the
 *       dependency positional pairing assigns.</b> The annotation no longer
 *       <i>selects</i> a dependency; it <i>asserts</i> the one position already
 *       chose. Correctly-ordered code is unaffected and gains a compile-time-ish
 *       safety net; a value that disagrees is a boot failure rather than the
 *       silent rebinding it would otherwise be. It is deliberately NOT an
 *       override — an override would put two matching rules back inside one
 *       annotation family, which is the hazard #1401 exists to close.</li>
 *   <li><b>No {@code @MeshInject}, but the parameter's NAME resolves to a
 *       different declared dependency → WARN.</b> This is the 3.3-and-earlier
 *       shape: the handler was written when the name decided, so it binds
 *       differently now. It is a warning, not an error, because names carry no
 *       meaning under the new contract and a coincidence must not fail a boot.
 *       Adding a {@code @MeshInject} that agrees with the position silences it
 *       and turns the slot into an asserted one. Applies only to the two sites
 *       that <i>were</i> name-based — {@code @MeshTool} never consulted names,
 *       so a name coincidence there is not a migration signal
 *       ({@link #analyzeTool}).</li>
 * </ul>
 *
 * <h2>What is no longer reported</h2>
 *
 * <p>PR A (the warning-only predecessor of this class) raised an ERROR for a
 * parameter with no {@code @MeshInject} value and no name — a class compiled
 * without {@code -parameters}. Under name binding that parameter bound to
 * nothing and was injected null; under positional binding it binds correctly,
 * because names were the only thing missing. That shape is now <b>OK</b>. The
 * same goes for a parameter whose name happens to match no declared capability.
 *
 * <h2>What it deliberately does not check</h2>
 *
 * <p><b>Arity.</b> Unlike {@code @MeshTool} (see
 * {@link MeshDiValidator#checkArity}), a route or A2A surface with more declared
 * dependencies than injectable parameters is <i>legitimate and documented</i>:
 * {@link MeshRouteUtils#getDependencies} hands the resolved set to the handler
 * by capability, and a dependency-declaring surface with zero parameters is the
 * canonical way to publish a capability edge that a constructor-injected
 * {@code @Qualifier} bean consumes. Reporting arity here would fire on correct
 * code.
 *
 * @see MeshInjectableSlots
 * @see MeshPositionalBinder
 * @see MeshDiValidator
 */
public final class MeshLegacyBindingDetector {

    private static final Logger log = LoggerFactory.getLogger(MeshLegacyBindingDetector.class);

    private MeshLegacyBindingDetector() {}

    /** How bad a handler's shape is. */
    public enum Severity {
        /** Nothing to report: every asserted slot agrees with its position. */
        OK,
        /**
         * A parameter's NAME points at a different declared dependency than its
         * position does — the 3.3 shape. Logged; fatal under
         * {@code MCP_MESH_STRICT_DI}.
         */
        WARN,
        /**
         * A {@code @MeshInject} value contradicts positional pairing. Always
         * fatal.
         */
        ERROR
    }

    /**
     * The verdict for one handler.
     *
     * @param severity worst per-slot outcome
     * @param message  the human-readable diagnostic; a DEBUG-grade summary when
     *                 {@code OK}
     */
    public record Finding(Severity severity, String message) {}

    /** Per-slot outcome. */
    private enum SlotVerdict {
        /** Nothing to say about this slot. */
        OK,
        /** {@code @MeshInject} names something other than the paired dependency. */
        ASSERTION_VIOLATED,
        /** The parameter name resolves to a different declared dependency. */
        NAME_CROSSOVER
    }

    /**
     * Inspect a {@code @MeshRoute} handler and enforce the contract.
     *
     * @param method the handler method
     * @param deps   the declared dependency specs in declaration order
     * @throws IllegalStateException on a {@code @MeshInject} assertion failure,
     *         or on any finding when {@code MCP_MESH_STRICT_DI} is enabled
     */
    public static void inspectRoute(Method method, List<MeshRouteRegistry.DependencySpec> deps) {
        report(analyze("@MeshRoute", method, MeshInjectableSlots.routeSlots(method), deps),
            MeshDiValidator.strictDiEnabled());
    }

    /**
     * Inspect a {@code @MeshA2A} handler and enforce the contract.
     *
     * @param method the handler method
     * @param deps   the declared dependency specs in declaration order
     * @throws IllegalStateException on a {@code @MeshInject} assertion failure,
     *         or on any finding when {@code MCP_MESH_STRICT_DI} is enabled
     */
    public static void inspectA2A(Method method, List<MeshRouteRegistry.DependencySpec> deps) {
        report(analyze("@MeshA2A", method, MeshInjectableSlots.a2aSlots(method), deps),
            MeshDiValidator.strictDiEnabled());
    }

    /**
     * Inspect a {@code @MeshTool} binding. Only the {@code @MeshInject}
     * assertion applies here — see {@link #analyzeTool}.
     *
     * @param binding the pairing table built by {@link MeshPositionalBinder}
     * @throws IllegalStateException on a {@code @MeshInject} assertion failure
     */
    public static void inspectTool(MeshPositionalBinder.Binding binding) {
        report(analyzeTool(binding), MeshDiValidator.strictDiEnabled());
    }

    /**
     * Apply the reporting policy to a finding. Package-private with an explicit
     * strictness flag because {@code MCP_MESH_STRICT_DI} cannot be set
     * in-process, so this is the seam tests drive.
     *
     * @param finding the verdict to report
     * @param strict  whether {@code MCP_MESH_STRICT_DI} is on, promoting WARN to
     *                a boot failure. {@link Severity#ERROR} is fatal either way
     */
    static void report(Finding finding, boolean strict) {
        switch (finding.severity()) {
            case OK -> {
                if (log.isDebugEnabled() && !finding.message().isEmpty()) {
                    log.debug("{}", finding.message());
                }
            }
            case WARN -> {
                if (strict) {
                    throw new IllegalStateException(finding.message());
                }
                log.warn("{}", finding.message());
            }
            // A @MeshInject value that contradicts the position is never a
            // survivable shape: the annotation is an assertion, so a false one
            // stops the boot regardless of MCP_MESH_STRICT_DI.
            case ERROR -> throw new IllegalStateException(finding.message());
        }
    }

    /**
     * The pure analysis for the two formerly name-based sites, with no logging
     * and no strictness policy — the seam tests use.
     *
     * @param site   the declaration site, e.g. {@code "@MeshRoute"}
     * @param method the handler method
     * @param slots  injectable slots in signature order
     * @param deps   the declared dependency specs in declaration order
     * @return the verdict; {@link Severity#OK} with a DEBUG-grade message when
     *         the handler is already on the positional contract
     */
    public static Finding analyze(
            String site,
            Method method,
            List<MeshPositionalBinder.Slot> slots,
            List<MeshRouteRegistry.DependencySpec> deps) {
        return analyze(site, method, slots, deps == null ? List.of() : deps, true);
    }

    /**
     * The pure analysis for {@code @MeshTool}.
     *
     * <p>Only the {@code @MeshInject} assertion is checked. The name-crossover
     * warning is a <i>migration</i> signal for the two sites whose binding rule
     * changed in 3.4; {@code @MeshTool} has always been positional, so a
     * parameter whose name happens to equal another declared capability says
     * nothing about that method's history and must not be reported.
     *
     * @param binding the pairing table built by {@link MeshPositionalBinder};
     *                only its {@link MeshPositionalBinder.Binding#pairableDepCount()}
     *                leading capabilities take part (a {@code @MeshService} view
     *                edge owns no injectable parameter)
     * @return the verdict
     */
    public static Finding analyzeTool(MeshPositionalBinder.Binding binding) {
        List<MeshRouteRegistry.DependencySpec> specs = new ArrayList<>();
        for (String capability : binding.capabilities().subList(0, binding.pairableDepCount())) {
            specs.add(new MeshRouteRegistry.DependencySpec(
                capability, new String[0], "", capability));
        }
        return analyze("@MeshTool", binding.method(), binding.slots(), specs, false);
    }

    private static Finding analyze(
            String site,
            Method method,
            List<MeshPositionalBinder.Slot> slots,
            List<MeshRouteRegistry.DependencySpec> deps,
            boolean namesUsedToBind) {

        Parameter[] params = method.getParameters();

        SlotVerdict[] verdicts = new SlotVerdict[slots.size()];
        String[] assertedKeys = new String[slots.size()];
        String[] nameKeys = new String[slots.size()];
        int[] nameTarget = new int[slots.size()];

        Severity severity = Severity.OK;
        for (int k = 0; k < slots.size(); k++) {
            Parameter p = params[slots.get(k).parameterPosition()];
            MeshInject inject = p.getAnnotation(MeshInject.class);
            nameTarget[k] = -1;

            if (inject != null && !inject.value().isEmpty()) {
                assertedKeys[k] = inject.value();
                verdicts[k] = refersTo(deps, k, inject.value())
                    ? SlotVerdict.OK : SlotVerdict.ASSERTION_VIOLATED;
                // The assertion diagnostic prints where the value WOULD have
                // pointed under the old rule, so the reorder can be prescribed.
                nameTarget[k] = matchIndex(deps, inject.value());
            } else if (namesUsedToBind && p.isNamePresent()) {
                nameKeys[k] = p.getName();
                nameTarget[k] = matchIndex(deps, p.getName());
                verdicts[k] = (nameTarget[k] >= 0 && nameTarget[k] != k)
                    ? SlotVerdict.NAME_CROSSOVER : SlotVerdict.OK;
            } else {
                // No assertion and no name signal. Under positional binding
                // this is a perfectly ordinary slot — names are not consulted,
                // so there is nothing left to disagree about.
                verdicts[k] = SlotVerdict.OK;
            }

            severity = switch (verdicts[k]) {
                case OK -> severity;
                case NAME_CROSSOVER -> severity == Severity.ERROR ? Severity.ERROR : Severity.WARN;
                case ASSERTION_VIOLATED -> Severity.ERROR;
            };
        }

        return new Finding(severity,
            buildMessage(site, method, slots, deps, verdicts, assertedKeys, nameKeys,
                nameTarget, severity));
    }

    /**
     * Whether {@code key} refers to the dependency positional pairing puts at
     * slot {@code k}.
     *
     * <p>The declared {@code @MeshDependency(name = ...)} alias counts as well
     * as the capability itself: {@code name} is an explicit, user-authored
     * second spelling of the same edge (and defaults to the camelCased
     * capability), so accepting it keeps
     * {@code @MeshDependency(capability = "base-cap") + @MeshInject("baseCap")}
     * a legal assertion. It never lets the annotation point at a
     * <i>different</i> dependency — that is the whole check.
     */
    private static boolean refersTo(
            List<MeshRouteRegistry.DependencySpec> deps, int k, String key) {
        if (k >= deps.size()) {
            return false;
        }
        MeshRouteRegistry.DependencySpec dep = deps.get(k);
        return key.equals(dep.getCapability()) || key.equals(dep.getParameterName());
    }

    /**
     * The declared dependency a name key resolved to under the pre-3.4 rule.
     *
     * <p>Mirrors both former lookups: the route path's map was double-keyed by
     * capability AND by {@code DependencySpec.getParameterName()}; the A2A path
     * scanned the same two fields in declaration order. First declaration wins
     * on a collision. Used for diagnostics only — nothing binds this way now.
     */
    private static int matchIndex(List<MeshRouteRegistry.DependencySpec> deps, String key) {
        for (int i = 0; i < deps.size(); i++) {
            MeshRouteRegistry.DependencySpec dep = deps.get(i);
            if (key.equals(dep.getCapability()) || key.equals(dep.getParameterName())) {
                return i;
            }
        }
        return -1;
    }

    private static String buildMessage(
            String site,
            Method method,
            List<MeshPositionalBinder.Slot> slots,
            List<MeshRouteRegistry.DependencySpec> deps,
            SlotVerdict[] verdicts,
            String[] assertedKeys,
            String[] nameKeys,
            int[] nameTarget,
            Severity severity) {

        String signature = signatureOf(method);
        if (severity == Severity.OK) {
            return site + " " + signature + ": positional dependency binding is consistent for all "
                + slots.size() + " injectable parameter(s).";
        }

        StringBuilder sb = new StringBuilder();
        sb.append(site).append(' ').append(signature).append(": ");
        if (severity == Severity.ERROR) {
            sb.append("a @MeshInject value contradicts the dependency its parameter's POSITION "
                + "binds to.");
        } else {
            sb.append("parameter names disagree with declaration order, so these parameters do "
                + "NOT bind the way their names suggest.");
        }

        sb.append("\n  ").append(site).append(" binds mesh dependencies BY POSITION (issue #1401): "
            + "the Nth declared dependency binds to the Nth injectable parameter, and parameter "
            + "names are never consulted. @MeshTool, and every Python and TypeScript site, work "
            + "the same way. @MeshInject no longer SELECTS a dependency — it ASSERTS the one "
            + "positional pairing assigns.");

        sb.append("\n  ").append(deps.size())
            .append(deps.size() == 1 ? " declared dependency: " : " declared dependencies: ")
            .append(renderDeps(deps));

        Parameter[] params = method.getParameters();
        for (int k = 0; k < slots.size(); k++) {
            Parameter p = params[slots.get(k).parameterPosition()];
            sb.append("\n    slot ").append(k)
                .append(" = parameter ").append(slots.get(k).parameterPosition())
                .append(" (").append(p.getType().getSimpleName()).append(' ')
                .append(p.isNamePresent() ? p.getName() : "<unnamed>").append(')');
            if (verdicts[k] == SlotVerdict.OK) {
                sb.append("\n        ").append(pad("binds (by position):"))
                    .append(positionalTarget(deps, k)).append(" — OK");
                continue;
            }
            sb.append("\n        ").append(pad(claimLabel(assertedKeys[k], nameKeys[k])))
                .append(claimTarget(deps, nameTarget[k]));
            sb.append("\n        ").append(pad("binds (by position):"))
                .append(positionalTarget(deps, k));
        }

        appendPrescription(sb, slots, deps, verdicts, nameTarget, severity);

        if (severity == Severity.WARN && !MeshDiValidator.strictDiEnabled()) {
            sb.append("\n  Set ").append(MeshDiValidator.STRICT_DI_ENV)
                .append("=true to fail startup on this instead of logging it.");
        }
        return sb.toString();
    }

    private static void appendPrescription(
            StringBuilder sb,
            List<MeshPositionalBinder.Slot> slots,
            List<MeshRouteRegistry.DependencySpec> deps,
            SlotVerdict[] verdicts,
            int[] nameTarget,
            Severity severity) {

        // A reorder can only express what the names/assertions claim when each
        // slot claims a distinct declared dependency and every slot has a
        // position to sit at.
        Set<Integer> targets = new LinkedHashSet<>();
        boolean injective = slots.size() <= deps.size();
        for (int k = 0; k < slots.size() && injective; k++) {
            if (nameTarget[k] < 0 || !targets.add(nameTarget[k])) {
                injective = false;
            }
        }

        sb.append(severity == Severity.ERROR
            ? "\n  Fix — pick one:"
            : "\n  If this handler was written for mcp-mesh 3.3 or earlier (when @MeshRoute and "
                + "@MeshA2A bound by name), fix it — pick one:");

        if (injective) {
            List<String> reordered = new ArrayList<>();
            for (int k = 0; k < slots.size(); k++) {
                reordered.add(deps.get(nameTarget[k]).getCapability());
            }
            for (int i = 0; i < deps.size(); i++) {
                if (!targets.contains(i)) {
                    reordered.add(deps.get(i).getCapability());
                }
            }
            sb.append("\n    • reorder dependencies = {...} to: ");
            for (int i = 0; i < reordered.size(); i++) {
                sb.append(i == 0 ? "" : ", ")
                    .append('[').append(i).append("] '").append(reordered.get(i)).append('\'');
            }
            sb.append("\n      (move each whole @MeshDependency — keep its tags, version, "
                + "required and schema attributes with its capability)");
        } else {
            sb.append("\n    • reorder dependencies = {...} so declaration order matches "
                + "parameter order");
        }
        sb.append("\n    • or reorder the parameters to match the declaration order");

        boolean anyAssertion = false;
        boolean anyCrossover = false;
        for (SlotVerdict v : verdicts) {
            anyAssertion |= v == SlotVerdict.ASSERTION_VIOLATED;
            anyCrossover |= v == SlotVerdict.NAME_CROSSOVER;
        }
        if (anyAssertion) {
            sb.append("\n    • or correct the @MeshInject value on each parameter to name the "
                + "dependency at that parameter's position (@MeshInject is an assertion — "
                + "dropping it entirely is also valid, and binding is unchanged either way)");
        }
        if (anyCrossover) {
            sb.append("\n    • or, if the current bindings are already what you want, add "
                + "@MeshInject(\"<capability>\") to each parameter to assert it — that pins "
                + "the pairing and silences this warning");
        }
    }

    private static String claimLabel(String assertedKey, String nameKey) {
        if (assertedKey != null) {
            return "@MeshInject(\"" + assertedKey + "\") asserts:";
        }
        return "parameter name '" + nameKey + "' used to bind:";
    }

    private static String claimTarget(List<MeshRouteRegistry.DependencySpec> deps, int target) {
        if (target < 0) {
            return "NO MATCH among the declared dependencies";
        }
        return "dependency[" + target + "] '" + deps.get(target).getCapability() + "'";
    }

    private static String positionalTarget(List<MeshRouteRegistry.DependencySpec> deps, int k) {
        if (k >= deps.size()) {
            return "no dependency declared at index " + k + " — injected null";
        }
        return "dependency[" + k + "] '" + deps.get(k).getCapability() + "'";
    }

    private static String renderDeps(List<MeshRouteRegistry.DependencySpec> deps) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < deps.size(); i++) {
            sb.append(i == 0 ? "" : ", ")
                .append('[').append(i).append("] '").append(deps.get(i).getCapability()).append('\'');
        }
        return deps.isEmpty() ? "(none)" : sb.toString();
    }

    /** Left-pad a label to a fixed width so the two comparison lines line up. */
    private static String pad(String label) {
        int width = 48;
        if (label.length() >= width) {
            return label + " ";
        }
        return label + " ".repeat(width - label.length());
    }

    private static String signatureOf(Method method) {
        StringBuilder sb = new StringBuilder();
        sb.append(method.getDeclaringClass().getName()).append('.')
            .append(method.getName()).append('(');
        Class<?>[] types = method.getParameterTypes();
        for (int i = 0; i < types.length; i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(types[i].getSimpleName());
        }
        return sb.append(')').toString();
    }
}
