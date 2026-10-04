package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshPositionalBinder;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.core.ResolvableType;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.lang.reflect.TypeVariable;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;

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
 * <p>The boot-time binding checks ({@link MeshLegacyBindingDetector}) need the
 * same question answered for route and A2A handlers, and the live resolvers
 * answer it at request time. Under positional binding the answer also fixes the
 * <i>slot ordinals</i> — which declared dependency each parameter gets — so a
 * second, subtly different predicate would not merely disagree about a
 * diagnostic, it would misbind. That is exactly the drift surface #1401 exists
 * to close, so it is written once — here — and the live resolvers call it:
 *
 * <ul>
 *   <li>{@link MeshInjectArgumentResolver#supportsParameter} →
 *       {@link #isRouteInjectable(Class)}; its slot ordinals →
 *       {@link #routeSlots(Method)}</li>
 *   <li>{@code MeshRouteBeanPostProcessor.enrichDependencyReturnTypes} →
 *       {@link #routeSlots(Method)}, so the {@code McpMeshTool<T>} generic lands
 *       on the dependency that parameter actually binds to</li>
 *   <li>{@code MeshA2ADispatcher.planArguments} → {@link #a2aSlots(Method)}</li>
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
 * <p>A2A's message-fallback rule ("the parameter at index 0 takes the message if
 * nothing else claimed it") does compete for index 0 with a slot declared first,
 * and slots win. That precedence is stated explicitly in
 * {@code MeshA2ADispatcher.planArguments} rather than left implicit in the order
 * of an if/else chain. {@code MeshJobSubmitter} does not compete either way: it
 * is framework-constructed from the surface rather than paired with a declared
 * dependency — not a slot here, and it consumes no declared index.
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
     * The {@code T} of an {@code McpMeshTool<T>} parameter — the type the
     * proxy injected there deserializes into — resolved against
     * {@code targetClass}, so a handler inherited from a generic base
     * ({@code Base<T>.h(McpMeshTool<T>)} on {@code Foo extends Base<Foo>})
     * yields {@code Foo}, not the variable {@code T}.
     *
     * <p>The result never contains a type variable or wildcard: one that cannot
     * be resolved falls back to its bound. A result of {@code Object} (raw
     * parameter, {@code McpMeshTool<Object>}, unbounded {@code T} or {@code ?})
     * is reported as {@code null} — the dynamic, untyped proxy.
     *
     * @param method      the handler method
     * @param position    signature position of the parameter
     * @param targetClass the bean class the handler is invoked on
     * @return the type argument, or {@code null} for the untyped proxy
     */
    public static Type proxyTypeArgument(Method method, int position, Class<?> targetClass) {
        if (!McpMeshTool.class.isAssignableFrom(method.getParameterTypes()[position])) {
            return null;
        }
        ResolvableType arg = ResolvableType
            .forMethodParameter(method, position, targetClass)
            .as(McpMeshTool.class)
            .getGeneric(0);
        Type reified;
        try {
            reified = reify(arg, new HashSet<>());
        } catch (SelfReferentialBound e) {
            // An unresolved self-bounded variable (E extends Enum<E>,
            // T extends Comparable<T>) has no finite reified form: keep only
            // its erased bound.
            reified = arg.resolve();
        }
        return reified == null || reified == Object.class ? null : reified;
    }

    /** Thrown by {@link #reify} on re-entering a type variable it is already expanding. */
    private static final class SelfReferentialBound extends RuntimeException {
        SelfReferentialBound() {
            super(null, null, false, false);
        }
    }

    /**
     * A concrete {@link Type} for {@code type}: a {@link Class}, or a
     * {@link ParameterizedType} whose arguments are themselves reified. Type
     * variables and wildcards resolve through {@code type}'s context, falling
     * back to their bound.
     */
    private static Type reify(ResolvableType type, Set<TypeVariable<?>> expanding) {
        if (type == ResolvableType.NONE) {
            return null;
        }
        Type raw = type.getType();
        if (raw instanceof Class<?>) {
            return raw;
        }
        if (raw instanceof ParameterizedType pt && isConcrete(pt)) {
            return pt;
        }
        // Path-scoped: a variable re-entered while it is still being expanded
        // is self-referential; the same variable in a sibling position is not.
        TypeVariable<?> variable = raw instanceof TypeVariable<?> v ? v : null;
        if (variable != null && !expanding.add(variable)) {
            throw new SelfReferentialBound();
        }
        try {
            return reifyResolved(type, expanding);
        } finally {
            if (variable != null) {
                expanding.remove(variable);
            }
        }
    }

    private static Type reifyResolved(ResolvableType type, Set<TypeVariable<?>> expanding) {
        Class<?> resolved = type.resolve();
        if (resolved == null) {
            return null;
        }
        ResolvableType[] generics = type.getGenerics();
        if (generics.length == 0 || resolved.getTypeParameters().length != generics.length) {
            return resolved;
        }
        Type[] args = new Type[generics.length];
        for (int i = 0; i < generics.length; i++) {
            Type a = reify(generics[i], expanding);
            args[i] = a != null ? a : Object.class;
        }
        return new ReifiedParameterizedType(resolved, args, resolved.getDeclaringClass());
    }

    private static boolean isConcrete(Type type) {
        if (type instanceof Class<?>) {
            return true;
        }
        if (type instanceof ParameterizedType pt) {
            for (Type a : pt.getActualTypeArguments()) {
                if (!isConcrete(a)) {
                    return false;
                }
            }
            return true;
        }
        return false;
    }

    /**
     * A {@link ParameterizedType} built from resolved parts. {@code equals} and
     * {@code hashCode} follow the JDK's contract, so it is interchangeable with
     * a reflected {@code ParameterizedType} as a map key.
     */
    private record ReifiedParameterizedType(Class<?> rawType, Type[] actualTypeArguments, Type ownerType)
            implements ParameterizedType {

        @Override
        public Type[] getActualTypeArguments() {
            return actualTypeArguments.clone();
        }

        @Override
        public Type getRawType() {
            return rawType;
        }

        @Override
        public Type getOwnerType() {
            return ownerType;
        }

        @Override
        public boolean equals(Object o) {
            return o instanceof ParameterizedType other
                && rawType.equals(other.getRawType())
                && Objects.equals(ownerType, other.getOwnerType())
                && Arrays.equals(actualTypeArguments, other.getActualTypeArguments());
        }

        @Override
        public int hashCode() {
            return Arrays.hashCode(actualTypeArguments) ^ Objects.hashCode(ownerType) ^ rawType.hashCode();
        }

        @Override
        public String getTypeName() {
            StringBuilder sb = new StringBuilder(rawType.getTypeName()).append('<');
            for (int i = 0; i < actualTypeArguments.length; i++) {
                if (i > 0) {
                    sb.append(", ");
                }
                sb.append(actualTypeArguments[i].getTypeName());
            }
            return sb.append('>').toString();
        }

        @Override
        public String toString() {
            return getTypeName();
        }
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
