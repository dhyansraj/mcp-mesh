package io.mcpmesh.spring.web;

import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.DefaultParameterNameDiscoverer;
import org.springframework.core.MethodParameter;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.ServletWebRequest;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Characterization tests for {@link MeshInjectArgumentResolver} — the
 * {@code @MeshRoute} injection path (issue #1401).
 *
 * <p><b>Why these exist.</b> Before this PR there was no unit test anywhere for
 * this resolver; its only coverage was end-to-end integration fixtures. The
 * conversion of {@code @MeshRoute} from name-based to positional binding touches
 * exactly this code, so today's behaviour is pinned <i>first</i>. These tests
 * describe what the resolver does now, not what it should do — when the
 * conversion lands, the rewrite of this file <b>is</b> the semantic change, made
 * visible in a diff.
 *
 * <p><b>The contract being pinned:</b> the resolver derives a capability
 * <i>string</i> — {@code @MeshInject}'s value when non-empty, otherwise the
 * parameter name — and looks it up in the map the interceptor put on the
 * request. Declaration order of {@code dependencies = {...}} is never consulted,
 * so a parameter's position in the signature is irrelevant.
 *
 * <p><b>On the no-{@code -parameters} case.</b> The test harness reproduces it
 * by not installing a {@code ParameterNameDiscoverer} on the
 * {@link MethodParameter}, which is the same null that Spring's
 * {@code StandardReflectionParameterNameDiscoverer} returns for a class compiled
 * without {@code -parameters} (it refuses to fall back on the synthetic
 * {@code arg0} names). This module compiles <i>with</i> {@code -parameters}, so
 * the real bytecode shape cannot be produced in-tree.
 */
@DisplayName("MeshInjectArgumentResolver: today's by-NAME binding (issue #1401 characterization)")
class MeshInjectArgumentResolverCharacterizationTest {

    private final MeshInjectArgumentResolver resolver = new MeshInjectArgumentResolver();

    // ─────────────────────────────────────────────────────────────────
    // Handlers under characterization
    // ─────────────────────────────────────────────────────────────────

    @SuppressWarnings("unused")
    static class Handlers {

        /** @MeshInject values agree with declaration order [alpha, beta]. */
        String agreeing(
                @MeshInject("alpha") McpMeshTool a,
                @MeshInject("beta") McpMeshTool b) {
            return "";
        }

        /**
         * @MeshInject values are the REVERSE of declaration order
         * [alpha, beta]. Under name binding this is correct code; under
         * positional binding the two parameters swap.
         */
        String disagreeing(
                @MeshInject("beta") McpMeshTool first,
                @MeshInject("alpha") McpMeshTool second) {
            return "";
        }

        /** @MeshInject names a capability that is not declared anywhere. */
        String undeclared(@MeshInject("nope") McpMeshTool ghost) {
            return "";
        }

        /** No annotation — the parameter NAME is the lookup key. */
        String parameterNameFallback(McpMeshTool alpha) {
            return "";
        }

        /**
         * No annotation, and the capability is kebab-case: the interceptor also
         * keys the map by {@code DependencySpec.getParameterName()}, which
         * defaults to the camelCased capability.
         */
        String camelCasedParameterName(McpMeshTool baseCap) {
            return "";
        }

        /** @MeshInject present but with an empty value — falls back to the name. */
        String emptyInjectValue(@MeshInject McpMeshTool alpha) {
            return "";
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // The pins
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("@MeshInject value agreeing with declaration order: each parameter gets its own proxy")
    void agreeingInjectValuesResolveToTheirOwnCapability() {
        McpMeshTool alpha = stub("alpha");
        McpMeshTool beta = stub("beta");
        ServletWebRequest request = requestWith(deps(alpha, beta));

        assertSame(alpha, resolve("agreeing", 0, request));
        assertSame(beta, resolve("agreeing", 1, request));
    }

    @Test
    @DisplayName("PIN: @MeshInject value WINS over parameter position — declaration order is ignored")
    void nameBeatsPositionToday() {
        McpMeshTool alpha = stub("alpha");
        McpMeshTool beta = stub("beta");
        ServletWebRequest request = requestWith(deps(alpha, beta));

        // Declaration order is [alpha, beta]; positional binding would give
        // parameter 0 the alpha proxy. Today the @MeshInject value decides.
        assertSame(beta, resolve("disagreeing", 0, request),
            "parameter 0 is annotated @MeshInject(\"beta\") and must receive the beta proxy today");
        assertSame(alpha, resolve("disagreeing", 1, request),
            "parameter 1 is annotated @MeshInject(\"alpha\") and must receive the alpha proxy today");
    }

    @Test
    @DisplayName("@MeshInject value matching no declared capability: null, no exception")
    void undeclaredInjectValueResolvesToNull() {
        ServletWebRequest request = requestWith(deps(stub("alpha"), stub("beta")));

        assertNull(resolve("undeclared", 0, request),
            "an unmatched capability is a warn-and-inject-null, not a failure");
    }

    @Test
    @DisplayName("No @MeshInject: the PARAMETER NAME is the lookup key")
    void parameterNameIsTheFallbackKey() {
        McpMeshTool alpha = stub("alpha");
        ServletWebRequest request = requestWith(deps(alpha));

        assertSame(alpha, resolve("parameterNameFallback", 0, request));
    }

    @Test
    @DisplayName("No @MeshInject, kebab-case capability: the camelCased DependencySpec name matches")
    void camelCasedParameterNameKeyMatches() {
        // The interceptor double-keys the map: capability AND
        // DependencySpec.getParameterName(), which camelCases "base-cap".
        McpMeshTool baseCap = stub("base-cap");
        Map<String, McpMeshTool> map = new LinkedHashMap<>();
        map.put("base-cap", baseCap);
        map.put("baseCap", baseCap);
        ServletWebRequest request = requestWith(map);

        assertSame(baseCap, resolve("camelCasedParameterName", 0, request));
    }

    @Test
    @DisplayName("@MeshInject with an empty value falls back to the parameter name")
    void emptyInjectValueFallsBackToParameterName() {
        McpMeshTool alpha = stub("alpha");
        ServletWebRequest request = requestWith(deps(alpha));

        assertSame(alpha, resolve("emptyInjectValue", 0, request));
    }

    @Test
    @DisplayName("No @MeshInject and no parameter name (compiled without -parameters): null")
    void noNameSignalResolvesToNull() {
        ServletWebRequest request = requestWith(deps(stub("alpha")));

        // A class compiled without -parameters cannot be produced in-tree (this
        // module compiles WITH it), so the shape is reproduced at the resolver's
        // seam: MethodParameter.getParameterName() returns null. Verified against
        // Spring 7.0.7 — for a class compiled without -parameters it returns null
        // both with and without a ParameterNameDiscoverer installed, because
        // StandardReflectionParameterNameDiscoverer refuses the synthetic argN
        // names.
        MethodParameter parameter = mock(MethodParameter.class);
        when(parameter.getParameterAnnotation(MeshInject.class)).thenReturn(null);
        when(parameter.getParameterName()).thenReturn(null);

        assertNull(resolver.resolveArgument(parameter, null, request, null),
            "a parameter with no @MeshInject value and no discoverable name binds to nothing today");
    }

    @Test
    @DisplayName("No mesh dependencies on the request (not a @MeshRoute handler): null")
    void noDependencyAttributeResolvesToNull() {
        ServletWebRequest request = new ServletWebRequest(new MockHttpServletRequest());

        assertNull(resolve("agreeing", 0, request));
    }

    @Test
    @DisplayName("supportsParameter claims McpMeshTool parameters with or without @MeshInject")
    void supportsMcpMeshToolParameters() {
        assertTrue(resolver.supportsParameter(named(methodOf("agreeing"), 0)));
        assertTrue(resolver.supportsParameter(named(methodOf("parameterNameFallback"), 0)));
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    private Object resolve(String methodName, int index, ServletWebRequest request) {
        return resolver.resolveArgument(named(methodOf(methodName), index), null, request, null);
    }

    /**
     * A {@link MethodParameter} with name discovery installed — mirroring what
     * Spring MVC's {@code InvocableHandlerMethod} does before calling a resolver.
     */
    private static MethodParameter named(Method method, int index) {
        MethodParameter parameter = new MethodParameter(method, index);
        parameter.initParameterNameDiscovery(new DefaultParameterNameDiscoverer());
        return parameter;
    }

    private static Method methodOf(String name) {
        for (Method m : Handlers.class.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError("No such handler: " + name);
    }

    private static ServletWebRequest requestWith(Map<String, McpMeshTool> dependencies) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR, dependencies);
        return new ServletWebRequest(request);
    }

    /** Build the interceptor's map keyed by capability (names equal capabilities here). */
    private static Map<String, McpMeshTool> deps(McpMeshTool... tools) {
        Map<String, McpMeshTool> map = new LinkedHashMap<>();
        for (McpMeshTool tool : tools) {
            map.put(tool.toString(), tool);
        }
        return map;
    }

    /** An identity-bearing {@link McpMeshTool} — the mock's name is its capability. */
    private static McpMeshTool stub(String capability) {
        return mock(McpMeshTool.class, capability);
    }
}
