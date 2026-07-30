package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshPositionalBinder;
import io.mcpmesh.types.McpMeshTool;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.ArrayList;
import java.util.List;

/**
 * "Is this parameter an injectable dependency slot?" for the two web
 * injection sites — {@code @MeshRoute} and {@code @MeshA2A} — in one place
 * (issue #1401).
 *
 * <h2>Why this exists as its own component</h2>
 *
 * <p>{@link MeshPositionalBinder} deliberately does not classify parameters:
 * it takes an already-enumerated slot list, because the {@code @MeshTool} rules
 * live inside {@code MeshToolWrapper.analyzeParameters} tangled with
 * {@code @Param} validation, generic extraction and boot-time
 * {@code @A2AConsumer} checks. Re-deriving them in the binder would duplicate
 * that classification.
 *
 * <p>The legacy-shape detector ({@link MeshLegacyBindingDetector}) needs the
 * same question answered for route and A2A handlers at boot, and the live
 * resolvers answer it at request time. Writing the predicate twice is exactly
 * the drift surface #1401 exists to close, so it is written once — here — and
 * the live resolvers call it:
 *
 * <ul>
 *   <li>{@link MeshInjectArgumentResolver#supportsParameter} →
 *       {@link #isRouteInjectable(Class)}</li>
 *   <li>{@code MeshA2ADispatcher.invokeHandler}'s dependency branch →
 *       {@link #isA2AInjectable(Parameter)}</li>
 * </ul>
 *
 * <h2>The two rules genuinely differ</h2>
 *
 * <p>They are not accidentally different, so this class exposes two methods
 * rather than pretending one rule covers both:
 *
 * <ul>
 *   <li><b>Route</b> keys purely off the parameter <i>type</i>. Spring MVC asks
 *       {@code supportsParameter} before it knows anything else, and a
 *       {@code @MeshInject} on a non-{@code McpMeshTool} parameter must fall
 *       through to Spring's own resolvers rather than being claimed here.</li>
 *   <li><b>A2A</b> additionally treats {@code @MeshInject} on <i>any</i>
 *       parameter type as a dependency slot: the dispatcher owns the whole
 *       argument array (there is no Spring MVC resolver chain behind it), so
 *       the annotation is the user's unambiguous statement of intent.</li>
 * </ul>
 *
 * <p>A2A's message-fallback rule ("the parameter at index 0 takes the message
 * if nothing else claimed it") does not compete with these slots: the
 * dependency branch is evaluated <i>first</i> in {@code invokeHandler}, so a
 * slot always wins index 0. Neither does {@code MeshJobSubmitter}, which is
 * framework-constructed from the surface rather than paired with a declared
 * dependency — it is not a slot here, and it consumes no declared index.
 *
 * @see MeshLegacyBindingDetector
 * @see MeshPositionalBinder
 */
public final class MeshInjectableSlots {

    private MeshInjectableSlots() {}

    /**
     * Whether a {@code @MeshRoute} handler parameter of this type is a mesh
     * dependency slot.
     *
     * @param parameterType the declared parameter type
     * @return true when the framework injects a mesh proxy here
     */
    public static boolean isRouteInjectable(Class<?> parameterType) {
        return McpMeshTool.class.isAssignableFrom(parameterType);
    }

    /**
     * Whether a {@code @MeshA2A} handler parameter is a mesh dependency slot.
     *
     * @param param the handler parameter
     * @return true when the dispatcher fills this slot from a declared
     *         {@code @MeshDependency}
     */
    public static boolean isA2AInjectable(Parameter param) {
        return param.getAnnotation(MeshInject.class) != null
            || McpMeshTool.class.isAssignableFrom(param.getType());
    }

    /**
     * Injectable slots of a {@code @MeshRoute} handler, in signature order.
     *
     * @param method the handler method
     * @return proxy slots in signature order (possibly empty)
     */
    public static List<MeshPositionalBinder.Slot> routeSlots(Method method) {
        List<MeshPositionalBinder.Slot> slots = new ArrayList<>();
        Parameter[] params = method.getParameters();
        for (int i = 0; i < params.length; i++) {
            if (isRouteInjectable(params[i].getType())) {
                slots.add(new MeshPositionalBinder.Slot(i, MeshPositionalBinder.SlotRole.PROXY));
            }
        }
        return slots;
    }

    /**
     * Injectable slots of a {@code @MeshA2A} handler, in signature order.
     *
     * @param method the handler method
     * @return proxy slots in signature order (possibly empty)
     */
    public static List<MeshPositionalBinder.Slot> a2aSlots(Method method) {
        List<MeshPositionalBinder.Slot> slots = new ArrayList<>();
        Parameter[] params = method.getParameters();
        for (int i = 0; i < params.length; i++) {
            if (isA2AInjectable(params[i])) {
                slots.add(new MeshPositionalBinder.Slot(i, MeshPositionalBinder.SlotRole.PROXY));
            }
        }
        return slots;
    }
}
