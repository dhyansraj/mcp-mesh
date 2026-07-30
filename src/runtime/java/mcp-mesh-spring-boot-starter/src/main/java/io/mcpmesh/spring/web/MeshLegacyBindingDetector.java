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
 * The migration instrument for issue #1401: at boot, tell a user whether their
 * {@code @MeshRoute} / {@code @MeshA2A} handler means something different once
 * those sites move from name-based to positional dependency binding.
 *
 * <h2>What it compares</h2>
 *
 * <p>For each handler it enumerates the injectable slots in signature order
 * ({@link MeshInjectableSlots}) and pairs them positionally with the declared
 * {@code @MeshDependency} list — the binding of the future. Against that it puts
 * the binding of today: the capability name each slot resolves through, which is
 * {@code @MeshInject}'s value when non-empty and the parameter name otherwise.
 * Four outcomes per slot:
 *
 * <ul>
 *   <li><b>Agrees</b> — the name resolves to the same dependency the position
 *       would. Positional and by-name binding are identical here; nothing
 *       changes, and nothing is reported (DEBUG).</li>
 *   <li><b>Reordered</b> — the name resolves to a <i>different</i> declared
 *       dependency. The handler was written under name-binding with an order
 *       positional binding would change. <b>WARN</b> today; the conversion PR
 *       makes it fatal.</li>
 *   <li><b>Undeclared</b> — the name matches nothing declared. This is
 *       <i>already</i> broken: {@code MeshInjectArgumentResolver} warns and
 *       injects null at request time. Reported as an <b>ERROR</b>, because a
 *       boot-time error beats a per-request warning.</li>
 *   <li><b>No name available</b> — no {@code @MeshInject} value and the class
 *       was compiled without {@code -parameters}. Spring's
 *       {@code MethodParameter.getParameterName()} returns null (verified: the
 *       reflection {@code Parameter.getName()} yields {@code arg0}, and Spring's
 *       {@code StandardReflectionParameterNameDiscoverer} refuses to use it), so
 *       the route resolver already logs an error and injects null, and the A2A
 *       dispatcher already matches {@code "arg0"} against nothing. <b>There is
 *       no working code in this shape</b> — which is what makes the conversion
 *       safe. Reported as an <b>ERROR</b>.</li>
 * </ul>
 *
 * <h2>What it deliberately does not check</h2>
 *
 * <p><b>Arity.</b> Unlike {@code @MeshTool} (see
 * {@link MeshDiValidator#checkArity}), a route or A2A surface with more declared
 * dependencies than injectable parameters is <i>legitimate and documented</i>:
 * {@code MeshRouteUtils.getDependencies(request)} hands the whole resolved map
 * to the handler, and a dependency-declaring surface with zero parameters is the
 * canonical way to publish a capability edge that a constructor-injected
 * {@code @Qualifier} bean consumes. Reporting arity here would fire on correct
 * code. Every slot that actually goes unbound is caught by the per-slot analysis
 * above instead.
 *
 * @see MeshInjectableSlots
 * @see MeshDiValidator
 */
public final class MeshLegacyBindingDetector {

    private static final Logger log = LoggerFactory.getLogger(MeshLegacyBindingDetector.class);

    private MeshLegacyBindingDetector() {}

    /** How bad a handler's shape is. */
    public enum Severity {
        /** Positional and by-name binding agree — nothing changes. */
        OK,
        /** At least one slot's binding changes under positional pairing. */
        WARN,
        /** At least one slot binds to nothing today — already broken. */
        ERROR
    }

    /**
     * The verdict for one handler.
     *
     * @param severity worst per-slot outcome
     * @param message  the human-readable diagnostic; empty when {@code OK}
     */
    public record Finding(Severity severity, String message) {}

    /** Per-slot outcome. */
    private enum SlotVerdict { AGREES, REORDERED, UNDECLARED, NO_NAME }

    /**
     * Inspect a {@code @MeshRoute} handler and report through the logger,
     * honouring {@code MCP_MESH_STRICT_DI}.
     *
     * @param method the handler method
     * @param deps   the declared dependency specs in declaration order
     * @throws IllegalStateException when the shape is not {@code OK} and strict
     *         DI is enabled
     */
    public static void inspectRoute(Method method, List<MeshRouteRegistry.DependencySpec> deps) {
        report(analyze("@MeshRoute", method, MeshInjectableSlots.routeSlots(method), deps),
            MeshDiValidator.strictDiEnabled());
    }

    /**
     * Inspect a {@code @MeshA2A} handler and report through the logger,
     * honouring {@code MCP_MESH_STRICT_DI}.
     *
     * @param method the handler method
     * @param deps   the declared dependency specs in declaration order
     * @throws IllegalStateException when the shape is not {@code OK} and strict
     *         DI is enabled
     */
    public static void inspectA2A(Method method, List<MeshRouteRegistry.DependencySpec> deps) {
        report(analyze("@MeshA2A", method, MeshInjectableSlots.a2aSlots(method), deps),
            MeshDiValidator.strictDiEnabled());
    }

    /**
     * Apply the reporting policy to a finding. Package-private with an explicit
     * strictness flag because {@code MCP_MESH_STRICT_DI} cannot be set
     * in-process, so this is the seam tests drive.
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
            case ERROR -> {
                if (strict) {
                    throw new IllegalStateException(finding.message());
                }
                log.error("{}", finding.message());
            }
        }
    }

    /**
     * The pure analysis, with no logging and no strictness policy — the seam
     * tests use.
     *
     * @param site   the declaration site, e.g. {@code "@MeshRoute"}
     * @param method the handler method
     * @param slots  injectable slots in signature order
     * @param deps   the declared dependency specs in declaration order
     * @return the verdict; {@link Severity#OK} with a DEBUG-grade message when
     *         today's and tomorrow's bindings are identical
     */
    public static Finding analyze(
            String site,
            Method method,
            List<MeshPositionalBinder.Slot> slots,
            List<MeshRouteRegistry.DependencySpec> deps) {

        List<MeshRouteRegistry.DependencySpec> declared = deps == null ? List.of() : deps;
        Parameter[] params = method.getParameters();

        SlotVerdict[] verdicts = new SlotVerdict[slots.size()];
        String[] nameKeys = new String[slots.size()];
        boolean[] fromAnnotation = new boolean[slots.size()];
        int[] nameTarget = new int[slots.size()];

        Severity severity = Severity.OK;
        for (int k = 0; k < slots.size(); k++) {
            Parameter p = params[slots.get(k).parameterPosition()];
            MeshInject inject = p.getAnnotation(MeshInject.class);
            String key;
            if (inject != null && !inject.value().isEmpty()) {
                key = inject.value();
                fromAnnotation[k] = true;
            } else if (p.isNamePresent()) {
                key = p.getName();
            } else {
                key = null;
            }
            nameKeys[k] = key;
            nameTarget[k] = key == null ? -1 : matchIndex(declared, key);

            if (key == null) {
                verdicts[k] = SlotVerdict.NO_NAME;
            } else if (nameTarget[k] < 0) {
                verdicts[k] = SlotVerdict.UNDECLARED;
            } else if (nameTarget[k] == k) {
                verdicts[k] = SlotVerdict.AGREES;
            } else {
                verdicts[k] = SlotVerdict.REORDERED;
            }

            severity = switch (verdicts[k]) {
                case AGREES -> severity;
                case REORDERED -> severity == Severity.ERROR ? Severity.ERROR : Severity.WARN;
                case UNDECLARED, NO_NAME -> Severity.ERROR;
            };
        }

        return new Finding(severity,
            buildMessage(site, method, slots, declared, verdicts, nameKeys, fromAnnotation,
                nameTarget, severity));
    }

    /**
     * The declared dependency a name key resolves to today.
     *
     * <p>Mirrors both live lookups: the route path's map is double-keyed by
     * capability AND by {@code DependencySpec.getParameterName()}
     * ({@code MeshRouteHandlerInterceptor:155-157}); the A2A path scans the same
     * two fields in declaration order ({@code MeshA2ADispatcher:779-784}).
     * First declaration wins on a collision.
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
            String[] nameKeys,
            boolean[] fromAnnotation,
            int[] nameTarget,
            Severity severity) {

        String signature = signatureOf(method);
        if (severity == Severity.OK) {
            return site + " " + signature + ": name-based and positional dependency binding "
                + "agree for all " + slots.size() + " injectable parameter(s) — issue #1401 will "
                + "not change this handler.";
        }

        StringBuilder sb = new StringBuilder();
        sb.append(site).append(' ').append(signature).append(": ");
        if (severity == Severity.ERROR) {
            sb.append("at least one injectable parameter resolves to NO declared dependency and "
                + "is injected null today.");
        } else {
            sb.append("declaration order disagrees with parameter names, so this handler's "
                + "bindings WILL CHANGE.");
        }

        sb.append("\n  ").append(site).append(" binds mesh dependencies BY NAME today. mcp-mesh is "
            + "aligning every injection site on the positional contract (issue #1401): the Nth "
            + "declared dependency binds to the Nth injectable parameter, and names are not "
            + "consulted. @MeshTool already works this way, as does every Python and TypeScript "
            + "site.");

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
            sb.append("\n        ").append(pad("today (" + todayLabel(nameKeys[k], fromAnnotation[k]) + "):"))
                .append(todayTarget(deps, nameTarget[k], verdicts[k]));
            sb.append("\n        ").append(pad("after alignment (by position):"))
                .append(positionalTarget(deps, k));
        }

        appendPrescription(sb, slots, deps, verdicts, nameTarget);

        if (!MeshDiValidator.strictDiEnabled()) {
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
            int[] nameTarget) {

        boolean anyUnbound = false;
        boolean anyReordered = false;
        for (SlotVerdict v : verdicts) {
            anyUnbound |= v == SlotVerdict.UNDECLARED || v == SlotVerdict.NO_NAME;
            anyReordered |= v == SlotVerdict.REORDERED;
        }

        if (anyUnbound) {
            sb.append("\n  Fix the unbound parameter(s) first: give each one a @MeshInject value "
                + "naming a declared capability, or declare the capability it names in "
                + "dependencies = {...}. A parameter that binds to nothing today will bind to "
                + "whatever sits at its position after the alignment.");
        }

        if (!anyReordered) {
            return;
        }

        // A reorder can only express the current bindings when each slot names a
        // distinct dependency and every slot has a position to sit at.
        Set<Integer> targets = new LinkedHashSet<>();
        boolean injective = slots.size() <= deps.size();
        for (int k = 0; k < slots.size() && injective; k++) {
            if (nameTarget[k] < 0 || !targets.add(nameTarget[k])) {
                injective = false;
            }
        }

        sb.append("\n  Fix now — behaviour-preserving today, correct after the alignment.");
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
            sb.append(" Reorder dependencies = {...} to: ");
            for (int i = 0; i < reordered.size(); i++) {
                sb.append(i == 0 ? "" : ", ")
                    .append('[').append(i).append("] '").append(reordered.get(i)).append('\'');
            }
            sb.append("\n      (move each whole @MeshDependency — keep its tags, version, "
                + "required and schema attributes with its capability), or reorder the "
                + "parameters to match the current declaration order.");
        } else {
            sb.append(" Reorder dependencies = {...} so declaration order matches parameter "
                + "order, or reorder the parameters to match the declaration.");
        }
        sb.append("\n      Once the two agree, name-based and positional binding are identical "
            + "and this stops being reported.");
    }

    private static String todayLabel(String key, boolean fromAnnotation) {
        if (key == null) {
            return "no @MeshInject value, and no parameter name is available — "
                + "compiled without -parameters";
        }
        return fromAnnotation
            ? "by name, @MeshInject(\"" + key + "\")"
            : "by name, parameter name '" + key + "'";
    }

    private static String todayTarget(
            List<MeshRouteRegistry.DependencySpec> deps, int target, SlotVerdict verdict) {
        return switch (verdict) {
            case NO_NAME -> "injected null (already broken today)";
            case UNDECLARED -> "NO MATCH among the declared dependencies — "
                + "injected null (already broken today)";
            default -> "dependency[" + target + "] '" + deps.get(target).getCapability() + "'";
        };
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
