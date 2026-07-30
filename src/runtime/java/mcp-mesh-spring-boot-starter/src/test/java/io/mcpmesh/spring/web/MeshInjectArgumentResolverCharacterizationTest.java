package io.mcpmesh.spring.web;

import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.DefaultParameterNameDiscoverer;
import org.springframework.core.MethodParameter;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.ServletWebRequest;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

/**
 * Characterization tests for {@link MeshInjectArgumentResolver} — the
 * {@code @MeshRoute} injection path (issue #1401).
 *
 * <p><b>What changed.</b> This file previously pinned by-NAME binding: the
 * resolver derived a capability string from {@code @MeshInject}'s value or the
 * parameter name and looked it up in a capability-keyed map, so declaration
 * order was irrelevant. It now pins the POSITIONAL contract: the Nth
 * {@code McpMeshTool} parameter in signature order receives the Nth declared
 * dependency, and no name — annotation value or parameter name — is consulted at
 * request time. The diff against the previous revision of this file <b>is</b> the
 * semantic change.
 *
 * <p>The three cases that used to prove name binding are kept and inverted:
 * {@code disagreeing} (annotation values reversed), {@code parameterNameFallback}
 * (no annotation), and {@code camelCasedParameterName}. Each now asserts the
 * opposite of what it asserted before.
 *
 * <p>{@code @MeshInject} still exists, but as an assertion checked at boot by
 * {@link MeshLegacyBindingDetector} — nothing in this resolver reads it, which is
 * what {@link #annotationIsInertAtRequestTime()} pins.
 */
@DisplayName("MeshInjectArgumentResolver: POSITIONAL binding (issue #1401)")
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
         * [alpha, beta]. This shape no longer reaches the resolver — it fails
         * the boot — but the resolver must still bind by position if it does.
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

        /** No annotation — nothing about the name matters any more. */
        String parameterNameFallback(McpMeshTool alpha) {
            return "";
        }

        /** A parameter named after the SECOND declared capability, sitting first. */
        String misleadingName(McpMeshTool beta, McpMeshTool alpha) {
            return "";
        }

        /** No annotation, kebab-case capability — no camelCase key to match. */
        String camelCasedParameterName(McpMeshTool baseCap) {
            return "";
        }

        /** @MeshInject present but with an empty value — asserts nothing. */
        String emptyInjectValue(@MeshInject McpMeshTool alpha) {
            return "";
        }

        /** Non-injectable parameters between the slots must not shift them. */
        String interleaved(
                String body,
                McpMeshTool first,
                int count,
                McpMeshTool second) {
            return "";
        }

        /** Three slots — the middle one is the unavailable dependency. */
        String three(McpMeshTool a, McpMeshTool b, McpMeshTool c) {
            return "";
        }

        /** More injectable parameters than declared dependencies. */
        String moreSlotsThanDeps(McpMeshTool a, McpMeshTool b) {
            return "";
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // The contract
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("The Nth McpMeshTool parameter receives the Nth declared dependency")
    void slotOrdinalSelectsTheDependency() {
        McpMeshTool alpha = stub("alpha");
        McpMeshTool beta = stub("beta");
        ServletWebRequest request = requestWith(List.of("alpha", "beta"), alpha, beta);

        assertSame(alpha, resolve("agreeing", 0, request));
        assertSame(beta, resolve("agreeing", 1, request));
    }

    @Test
    @DisplayName("PIN: POSITION wins — a reversed @MeshInject value does not swap the proxies")
    void positionBeatsName() {
        McpMeshTool alpha = stub("alpha");
        McpMeshTool beta = stub("beta");
        ServletWebRequest request = requestWith(List.of("alpha", "beta"), alpha, beta);

        // Declaration order is [alpha, beta]. Parameter 0 is annotated
        // @MeshInject("beta"), which under the pre-3.4 rule handed it the beta
        // proxy. Position decides now — and this exact shape is refused at boot
        // (MeshLegacyBindingDetectorTest), so the value can never be a lie in
        // practice.
        assertSame(alpha, resolve("disagreeing", 0, request),
            "slot 0 takes dependency[0] regardless of what @MeshInject says");
        assertSame(beta, resolve("disagreeing", 1, request),
            "slot 1 takes dependency[1] regardless of what @MeshInject says");
    }

    @Test
    @DisplayName("PIN: a parameter NAME matching another capability does not redirect the binding")
    void parameterNameIsNotConsulted() {
        McpMeshTool alpha = stub("alpha");
        McpMeshTool beta = stub("beta");
        ServletWebRequest request = requestWith(List.of("alpha", "beta"), alpha, beta);

        // Parameter 0 is literally named "beta". Under the pre-3.4 rule it
        // received the beta proxy; it now receives dependency[0].
        assertSame(alpha, resolve("misleadingName", 0, request));
        assertSame(beta, resolve("misleadingName", 1, request));
    }

    @Test
    @DisplayName("PIN: @MeshInject is inert at request time — the resolver never reads it")
    void annotationIsInertAtRequestTime() {
        McpMeshTool alpha = stub("alpha");
        ServletWebRequest request = requestWith(List.of("alpha"), alpha);

        // Three slot-0 parameters with three different annotation states, one
        // declared dependency: all three bind identically.
        assertSame(alpha, resolve("agreeing", 0, request), "@MeshInject(\"alpha\")");
        assertSame(alpha, resolve("emptyInjectValue", 0, request), "@MeshInject with no value");
        assertSame(alpha, resolve("parameterNameFallback", 0, request), "no annotation");
        assertSame(alpha, resolve("undeclared", 0, request),
            "even a @MeshInject value naming nothing declared binds by position");
    }

    @Test
    @DisplayName("A kebab-case capability needs no camelCase parameter name to bind")
    void kebabCaseCapabilityBindsWithoutANameMatch() {
        McpMeshTool baseCap = stub("base-cap");
        ServletWebRequest request = requestWith(List.of("base-cap"), baseCap);

        assertSame(baseCap, resolve("camelCasedParameterName", 0, request));
    }

    @Test
    @DisplayName("Non-injectable parameters between slots do not shift the slot ordinals")
    void onlyInjectableParametersCount() {
        McpMeshTool alpha = stub("alpha");
        McpMeshTool beta = stub("beta");
        ServletWebRequest request = requestWith(List.of("alpha", "beta"), alpha, beta);

        // Signature is (String, McpMeshTool, int, McpMeshTool): the slots are at
        // positions 1 and 3, but they are ordinals 0 and 1.
        assertSame(alpha, resolve("interleaved", 1, request));
        assertSame(beta, resolve("interleaved", 3, request));
    }

    // ─────────────────────────────────────────────────────────────────
    // Slot preservation (issue #1390) — the trap positional binding must not
    // reintroduce
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("SLOT PRESERVATION: an unavailable MIDDLE dependency does not shift the later ones")
    void unavailableMiddleDependencyHoldsItsOwnSlot() {
        McpMeshTool a = stub("a");
        McpMeshTool c = stub("c");
        // The interceptor null-pads: dependency[1] is unavailable, so index 1
        // is null and index 2 still holds c.
        ServletWebRequest request = requestWith(List.of("a", "b", "c"), a, null, c);

        assertSame(a, resolve("three", 0, request), "slot 0 keeps its own proxy");
        assertNull(resolve("three", 1, request),
            "the unavailable dependency leaves ITS OWN slot null");
        assertSame(c, resolve("three", 2, request),
            "slot 2 must still receive 'c' — it must not slide up into slot 1");
    }

    @Test
    @DisplayName("SLOT PRESERVATION: only the middle dependency available fills only the middle slot")
    void availableMiddleDependencyDoesNotSlideDown() {
        McpMeshTool b = stub("b");
        ServletWebRequest request = requestWith(List.of("a", "b", "c"), null, b, null);

        assertNull(resolve("three", 0, request));
        assertSame(b, resolve("three", 1, request),
            "the single available dependency lands in ITS slot, not slot 0");
        assertNull(resolve("three", 2, request));
    }

    @Test
    @DisplayName("More injectable parameters than dependencies: the surplus is null, not shifted")
    void surplusSlotIsNull() {
        McpMeshTool alpha = stub("alpha");
        ServletWebRequest request = requestWith(List.of("alpha"), alpha);

        assertSame(alpha, resolve("moreSlotsThanDeps", 0, request));
        assertNull(resolve("moreSlotsThanDeps", 1, request),
            "no dependency is declared at index 1");
    }

    // ─────────────────────────────────────────────────────────────────
    // Edges
    // ─────────────────────────────────────────────────────────────────

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
     * Names are now irrelevant to binding; the discoverer stays so the tests
     * prove that under the same conditions the old rule ran in.
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

    /**
     * Build a request carrying exactly what {@code MeshRouteHandlerInterceptor}
     * stores: the route metadata plus a positional, null-padded proxy list whose
     * length equals the declared dependency count.
     */
    private static ServletWebRequest requestWith(
            List<String> capabilities, McpMeshTool... resolved) {
        if (capabilities.size() != resolved.length) {
            throw new AssertionError("the interceptor null-pads to the declared count");
        }
        List<MeshRouteRegistry.DependencySpec> declared = new ArrayList<>();
        for (String capability : capabilities) {
            declared.add(new MeshRouteRegistry.DependencySpec(
                capability, new String[0], "", capability));
        }
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute(MeshRouteHandlerInterceptor.MESH_ROUTE_METADATA_ATTR,
            new MeshRouteRegistry.RouteMetadata("Handlers.test", declared, "", false));
        request.setAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR,
            java.util.Collections.unmodifiableList(Arrays.asList(resolved)));
        return new ServletWebRequest(request);
    }

    /** An identity-bearing {@link McpMeshTool} — the mock's name is its capability. */
    private static McpMeshTool stub(String capability) {
        return mock(McpMeshTool.class, capability);
    }
}
