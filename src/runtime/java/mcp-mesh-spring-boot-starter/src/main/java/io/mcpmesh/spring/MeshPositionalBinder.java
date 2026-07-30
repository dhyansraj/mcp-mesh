package io.mcpmesh.spring;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/**
 * The positional dependency-pairing rule, in one place.
 *
 * <p><b>The contract.</b> Declared dependencies pair positionally with a
 * method's injectable parameters in <i>signature order</i>: the Nth declared
 * dependency binds to the Nth injectable slot. Parameter names are never
 * consulted. This is the same contract as Python and TypeScript.
 *
 * <p>The two index spaces differ whenever a non-proxy injectable slot sits in
 * the middle of the signature — today, a {@code MeshJob} parameter. For
 * example {@code dependencies = ["job_cap", "db_cap"]} against
 * {@code (MeshJob job, McpMeshTool db)} puts {@code db_cap} at DECLARED index
 * 1 but at proxy SLOT ordinal 0. Registry events carry the declared index
 * while a wrapper's proxy arrays are slot-ordinal arrays, so the two
 * translation tables produced here — {@link Binding#depIndexToSlot()} and
 * {@link Binding#slotToDepIndex()} — are what let one side talk to the other.
 *
 * <p><b>Slack in both directions is tolerated, not an error</b> (today):
 * declared dependencies beyond the available slots map to {@code -1} and are
 * dropped; slots beyond the declared list map to {@code -1} and receive
 * {@code null}. {@link Binding#describe()} renders both cases explicitly — it
 * exists so a future arity/order validator (issue #1401) has a ready-made,
 * human-readable statement of what the pairing actually did.
 *
 * <p><b>Role assignment belongs to the caller.</b> This class deliberately
 * does NOT classify parameters. Each injection site decides for itself which
 * parameters are injectable and what kind they are, and those rules genuinely
 * differ:
 * <ul>
 *   <li>{@code @MeshTool} ({@link MeshToolWrapper}) treats {@code McpMeshTool}
 *       parameters as proxy slots and a {@code MeshJob} parameter as a job
 *       slot, while exempting {@code A2AClient} and {@code @MeshService} view
 *       parameters, which are bound by other means.</li>
 *   <li>The {@code @MeshA2A} dispatch path additionally treats
 *       {@code @MeshInject} on a <i>non-</i>{@code McpMeshTool} parameter as
 *       an injectable slot, and carries a message-fallback rule ("the
 *       parameter at index 0 takes the message if nothing else claimed it")
 *       that can compete for index 0 with a genuine slot. That competition is
 *       a role-assignment decision, so it stays with the caller: the caller
 *       simply does not emit a {@link Slot} for a position it wants to hand
 *       the message. Feeding the surviving slots here then yields the same
 *       pairing tables the tool path uses.</li>
 * </ul>
 * Callers therefore hand in an already-enumerated {@link Slot} list; this
 * class only orders it and pairs it.
 *
 * @see MeshToolWrapper
 * @see MeshJobResolver
 */
public final class MeshPositionalBinder {

    private MeshPositionalBinder() {}

    /** What an injectable slot is for. */
    public enum SlotRole {
        /**
         * A dependency-proxy slot ({@code McpMeshTool}). Consumes one declared
         * dependency index AND owns a proxy slot ordinal.
         */
        PROXY,
        /**
         * A job slot ({@code MeshJob}). Consumes one declared dependency index
         * — so the capability the user typed {@code MeshJob} for is known —
         * but owns no proxy slot: it is filled by the dispatch path
         * (submitter or controller), never by a resolution event.
         */
        JOB
    }

    /**
     * One injectable parameter.
     *
     * @param parameterPosition signature position of the parameter
     * @param role              what the slot is for
     */
    public record Slot(int parameterPosition, SlotRole role) {
        public Slot {
            if (parameterPosition < 0) {
                throw new IllegalArgumentException(
                    "parameterPosition must be >= 0, got " + parameterPosition);
            }
            if (role == null) {
                throw new IllegalArgumentException("role is required");
            }
        }
    }

    /**
     * The pairing table for one method.
     *
     * <p>The {@code int[]} accessors expose the binder's own arrays rather
     * than copies — {@link #bind} builds them fresh per call, so the caller
     * that receives a {@code Binding} owns them. Treat them as read-only if
     * the {@code Binding} is shared.
     *
     * @param method          the bound method (diagnostics only)
     * @param capabilities    the FULL declared dependency list, in declaration
     *                        order
     * @param pairableDepCount how many leading entries of {@code capabilities}
     *                        take part in positional pairing; the remainder
     *                        (e.g. {@code @MeshService} view edges) always map
     *                        to {@code -1}
     * @param slots           injectable slots in signature order
     * @param depIndexToSlot  declared dep index → proxy slot ordinal; -1 = no
     *                        proxy slot (job-backed, non-pairable, or excess).
     *                        Length = {@code capabilities.size()}
     * @param slotToDepIndex  proxy slot ordinal → declared dep index; -1 = no
     *                        declared dependency backs the slot. Length =
     *                        {@link #proxySlotCount()}
     * @param jobDepIndex     declared dep index paired with the {@code JOB}
     *                        slot, or -1 when there is no job slot or nothing
     *                        declared reaches it
     */
    public record Binding(
        Method method,
        List<String> capabilities,
        int pairableDepCount,
        List<Slot> slots,
        int[] depIndexToSlot,
        int[] slotToDepIndex,
        int jobDepIndex
    ) {
        public Binding {
            capabilities = List.copyOf(capabilities);
            slots = List.copyOf(slots);
        }

        /** Number of {@code PROXY} slots — the length of {@link #slotToDepIndex()}. */
        public int proxySlotCount() {
            return slotToDepIndex.length;
        }

        /** Signature positions of the injectable slots, in signature order. */
        public List<Integer> slotPositions() {
            return slots.stream().map(Slot::parameterPosition).toList();
        }

        /**
         * A human-readable statement of what the pairing did: every declared
         * dependency with the parameter it landed on, every declared
         * dependency that found no parameter, and every injectable parameter
         * that no declared dependency reached.
         *
         * <p>This is the text a dependency-count / ordering validator should
         * print (issue #1401): it names both index spaces, so a user who
         * reordered {@code dependencies = {...}} without reordering
         * parameters can see the mismatch directly.
         */
        public String describe() {
            StringBuilder sb = new StringBuilder();
            sb.append("positional dependency pairing for ").append(signature()).append('\n');
            sb.append("  ").append(pairableDepCount)
                .append(pairableDepCount == 1
                    ? " declared dependency pairs with " : " declared dependencies pair with ")
                .append(slots.size())
                .append(slots.size() == 1 ? " injectable parameter" : " injectable parameters")
                .append(" in signature order:");

            if (pairableDepCount == 0 && slots.isEmpty()) {
                sb.append(" (nothing to pair)");
            }
            for (int k = 0; k < pairableDepCount; k++) {
                sb.append("\n    dependency[").append(k).append("] '")
                    .append(capabilityAt(k)).append("' -> ");
                if (k < slots.size()) {
                    Slot slot = slots.get(k);
                    sb.append(describeParameter(slot));
                    if (slot.role() == SlotRole.PROXY) {
                        sb.append(" [proxy slot ").append(depIndexToSlot[k]).append(']');
                    } else {
                        sb.append(" [job slot]");
                    }
                } else {
                    sb.append("(no injectable parameter — dropped)");
                }
            }
            for (int s = pairableDepCount; s < slots.size(); s++) {
                Slot slot = slots.get(s);
                sb.append("\n    (no declared dependency) -> ")
                    .append(describeParameter(slot))
                    .append(slot.role() == SlotRole.JOB
                        ? " — no declared capability backs the job slot"
                        : " — injected null");
            }
            int nonPairable = capabilities.size() - pairableDepCount;
            if (nonPairable > 0) {
                sb.append("\n  ").append(nonPairable)
                    .append(" further declared dependenc")
                    .append(nonPairable == 1 ? "y is" : "ies are")
                    .append(" bound by other means (e.g. @MeshService view edges) "
                        + "and take no part in positional pairing");
            }
            return sb.toString();
        }

        private String capabilityAt(int k) {
            return k < capabilities.size() ? capabilities.get(k) : "?";
        }

        private String describeParameter(Slot slot) {
            int pos = slot.parameterPosition();
            Parameter[] params = method.getParameters();
            if (pos >= params.length) {
                return "parameter " + pos + " (out of range)";
            }
            Parameter p = params[pos];
            return "parameter " + pos + " (" + p.getType().getSimpleName() + " "
                + p.getName() + ")";
        }

        private String signature() {
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

        @Override
        public String toString() {
            return "Binding[" + signature()
                + ", depIndexToSlot=" + Arrays.toString(depIndexToSlot)
                + ", slotToDepIndex=" + Arrays.toString(slotToDepIndex)
                + ", jobDepIndex=" + jobDepIndex + "]";
        }
    }

    /**
     * Pair a declared dependency list with a method's injectable slots.
     *
     * <p>Slots are sorted by signature position (the caller may supply them in
     * any order); the Nth slot then takes the Nth pairable declared
     * dependency. A {@code JOB} slot consumes its declared index but yields no
     * proxy mapping. Surplus on either side maps to {@code -1} — see the class
     * javadoc.
     *
     * @param method           the method being bound; used for diagnostics
     * @param slots            injectable slots (any order; sorted here). At
     *                         most one {@code JOB} slot
     * @param capabilities     the FULL declared dependency list in declaration
     *                         order; may be empty
     * @param pairableDepCount how many leading {@code capabilities} entries
     *                         take part in pairing. Clamped into
     *                         {@code [0, capabilities.size()]}
     * @return the pairing table
     * @throws IllegalArgumentException if {@code method}, {@code slots} or
     *         {@code capabilities} is null, if two slots share a parameter
     *         position, or if more than one {@code JOB} slot is supplied
     */
    public static Binding bind(
            Method method,
            List<Slot> slots,
            List<String> capabilities,
            int pairableDepCount) {

        if (method == null) {
            throw new IllegalArgumentException("method is required");
        }
        if (slots == null) {
            throw new IllegalArgumentException("slots is required");
        }
        if (capabilities == null) {
            throw new IllegalArgumentException("capabilities is required");
        }

        List<Slot> ordered = new ArrayList<>(slots);
        ordered.sort(Comparator.comparingInt(Slot::parameterPosition));

        int jobSlots = 0;
        for (int i = 0; i < ordered.size(); i++) {
            if (i > 0 && ordered.get(i).parameterPosition() == ordered.get(i - 1).parameterPosition()) {
                throw new IllegalArgumentException(
                    "duplicate injectable slot at parameter position "
                        + ordered.get(i).parameterPosition() + " of "
                        + method.getDeclaringClass().getName() + "." + method.getName());
            }
            if (ordered.get(i).role() == SlotRole.JOB && ++jobSlots > 1) {
                throw new IllegalArgumentException(
                    "more than one JOB slot supplied for "
                        + method.getDeclaringClass().getName() + "." + method.getName()
                        + "; at most one is allowed");
            }
        }

        int depCount = capabilities.size();
        int pairable = Math.max(0, Math.min(pairableDepCount, depCount));

        int proxySlotCount = 0;
        for (Slot slot : ordered) {
            if (slot.role() == SlotRole.PROXY) {
                proxySlotCount++;
            }
        }

        int[] depIndexToSlot = new int[depCount];
        int[] slotToDepIndex = new int[proxySlotCount];
        Arrays.fill(depIndexToSlot, -1);
        Arrays.fill(slotToDepIndex, -1);

        int jobDepIndex = -1;
        int proxyOrdinal = 0;
        for (int k = 0; k < ordered.size(); k++) {
            Slot slot = ordered.get(k);
            boolean paired = k < pairable;
            if (slot.role() == SlotRole.JOB) {
                if (paired) {
                    jobDepIndex = k;
                }
                continue;
            }
            int ordinal = proxyOrdinal++;
            if (paired) {
                depIndexToSlot[k] = ordinal;
                slotToDepIndex[ordinal] = k;
            }
        }

        return new Binding(
            method, capabilities, pairable, ordered,
            depIndexToSlot, slotToDepIndex, jobDepIndex);
    }

    /**
     * Convenience for the {@code @MeshTool} slot shape: {@code McpMeshTool}
     * parameter positions plus an optional {@code MeshJob} parameter position.
     *
     * @param proxyPositions   signature positions of the proxy parameters
     * @param jobPosition      signature position of the {@code MeshJob}
     *                         parameter, or null
     * @return the slot list in signature order
     */
    public static List<Slot> slots(List<Integer> proxyPositions, Integer jobPosition) {
        List<Slot> slots = new ArrayList<>();
        if (proxyPositions != null) {
            for (Integer pos : proxyPositions) {
                slots.add(new Slot(pos, SlotRole.PROXY));
            }
        }
        if (jobPosition != null) {
            slots.add(new Slot(jobPosition, SlotRole.JOB));
        }
        slots.sort(Comparator.comparingInt(Slot::parameterPosition));
        return slots;
    }
}
