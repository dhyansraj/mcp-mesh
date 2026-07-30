package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.spring.web.MeshA2A;
import io.mcpmesh.spring.web.MeshA2ABeanPostProcessor;
import io.mcpmesh.spring.web.MeshA2ARegistry;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshInject;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.spring.web.MeshRouteBeanPostProcessor;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@code @MeshInject} is a checked assertion at every injection site (issue
 * #1401): its value must name the dependency positional pairing assigns, or the
 * application does not boot.
 *
 * <p>These tests drive the real boot components — the two bean post-processors
 * and the {@code MeshToolWrapper} constructor — rather than the analyzer, so
 * what is pinned is that the check is actually wired in, with a diagnostic a
 * user can act on. The correctly-ordered twin of each broken handler is
 * asserted to boot clean, because a guard that can stop a boot must not fire on
 * correct code.
 *
 * <p>{@code @MeshTool} is included because the annotation was <b>silently
 * ignored</b> there before 3.4 — the wrapper never imported it — which meant it
 * meant two different things depending on where it was written.
 */
@DisplayName("@MeshInject is a checked assertion at boot (issue #1401)")
class MeshInjectAssertionBootTest {

    // ─────────────────────────────────────────────────────────────────
    // @MeshRoute
    // ─────────────────────────────────────────────────────────────────

    @RestController
    @SuppressWarnings("unused")
    public static class ReorderedRouteController {
        @GetMapping("/bad")
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "get_employee"),
            @MeshDependency(capability = "employee_count")})
        public String handler(
                @MeshInject("employee_count") McpMeshTool statsTool,
                @MeshInject("get_employee") McpMeshTool employeeTool) {
            return "";
        }
    }

    @RestController
    @SuppressWarnings("unused")
    public static class CorrectRouteController {
        @GetMapping("/good")
        @MeshRoute(dependencies = {
            @MeshDependency(capability = "employee_count"),
            @MeshDependency(capability = "get_employee")})
        public String handler(
                @MeshInject("employee_count") McpMeshTool statsTool,
                @MeshInject("get_employee") McpMeshTool employeeTool) {
            return "";
        }
    }

    @Test
    @DisplayName("@MeshRoute: a reordered handler fails the boot, naming both orderings and the fix")
    void reorderedRouteFailsBoot() {
        MeshRouteBeanPostProcessor processor =
            new MeshRouteBeanPostProcessor(new MeshRouteRegistry());

        IllegalStateException e = assertThrows(IllegalStateException.class, () ->
            processor.postProcessAfterInitialization(new ReorderedRouteController(), "bad"));

        String m = e.getMessage();
        assertTrue(m.contains("@MeshRoute"), m);
        assertTrue(m.contains("ReorderedRouteController.handler"), m);
        assertTrue(m.contains("@MeshInject value contradicts"), m);
        assertTrue(m.contains("2 declared dependencies: [0] 'get_employee', [1] 'employee_count'"), m);
        assertTrue(m.contains("@MeshInject(\"employee_count\") asserts:"), m);
        assertTrue(m.contains("dependency[1] 'employee_count'"), m);
        assertTrue(m.contains("dependency[0] 'get_employee'"), m);
        assertTrue(m.contains(
            "reorder dependencies = {...} to: [0] 'employee_count', [1] 'get_employee'"), m);
    }

    @Test
    @DisplayName("@MeshRoute: the correctly-ordered twin boots clean")
    void correctRouteBoots() {
        new MeshRouteBeanPostProcessor(new MeshRouteRegistry())
            .postProcessAfterInitialization(new CorrectRouteController(), "good");
    }

    // ─────────────────────────────────────────────────────────────────
    // @MeshA2A
    // ─────────────────────────────────────────────────────────────────

    @SuppressWarnings("unused")
    public static class ReorderedA2ABean {
        @MeshA2A(path = "/bad", skillId = "bad", skillName = "bad", dependencies = {
            @MeshDependency(capability = "alpha"),
            @MeshDependency(capability = "beta")})
        public Object handler(
                Map<String, Object> message,
                @MeshInject("beta") McpMeshTool first,
                @MeshInject("alpha") McpMeshTool second) {
            return Map.of();
        }
    }

    @SuppressWarnings("unused")
    public static class CorrectA2ABean {
        @MeshA2A(path = "/good", skillId = "good", skillName = "good", dependencies = {
            @MeshDependency(capability = "beta"),
            @MeshDependency(capability = "alpha")})
        public Object handler(
                Map<String, Object> message,
                @MeshInject("beta") McpMeshTool first,
                @MeshInject("alpha") McpMeshTool second) {
            return Map.of();
        }
    }

    @Test
    @DisplayName("@MeshA2A: a reordered handler fails the boot")
    void reorderedA2AFailsBoot() {
        MeshA2ABeanPostProcessor processor = new MeshA2ABeanPostProcessor(new MeshA2ARegistry());

        IllegalStateException e = assertThrows(IllegalStateException.class, () ->
            processor.postProcessAfterInitialization(new ReorderedA2ABean(), "bad"));

        String m = e.getMessage();
        assertTrue(m.contains("@MeshA2A"), m);
        assertTrue(m.contains("@MeshInject value contradicts"), m);
        assertTrue(m.contains("reorder dependencies = {...} to: [0] 'beta', [1] 'alpha'"), m);
    }

    @Test
    @DisplayName("@MeshA2A: the correctly-ordered twin boots clean")
    void correctA2ABoots() {
        new MeshA2ABeanPostProcessor(new MeshA2ARegistry())
            .postProcessAfterInitialization(new CorrectA2ABean(), "good");
    }

    // ─────────────────────────────────────────────────────────────────
    // @MeshTool — where @MeshInject used to be silently ignored
    // ─────────────────────────────────────────────────────────────────

    @SuppressWarnings("unused")
    public static class ToolBean {
        @MeshTool(capability = "reordered", dependencies = {
            @Selector(capability = "alpha"),
            @Selector(capability = "beta")})
        public Object reordered(
                @Param("id") String id,
                @MeshInject("beta") McpMeshTool first,
                @MeshInject("alpha") McpMeshTool second) {
            return Map.of();
        }

        @MeshTool(capability = "correct", dependencies = {
            @Selector(capability = "beta"),
            @Selector(capability = "alpha")})
        public Object correct(
                @Param("id") String id,
                @MeshInject("beta") McpMeshTool first,
                @MeshInject("alpha") McpMeshTool second) {
            return Map.of();
        }
    }

    @Test
    @DisplayName("@MeshTool: a contradicting @MeshInject now fails the boot instead of being ignored")
    void reorderedToolFailsBoot() {
        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> wrapper("reordered", List.of("alpha", "beta")));

        String m = e.getMessage();
        assertTrue(m.contains("@MeshTool"), m);
        assertTrue(m.contains("@MeshInject value contradicts"), m);
        assertTrue(m.contains("reorder dependencies = {...} to: [0] 'beta', [1] 'alpha'"), m);
    }

    @Test
    @DisplayName("@MeshTool: the correctly-ordered twin constructs clean")
    void correctToolBoots() throws Exception {
        wrapper("correct", List.of("beta", "alpha"));
    }

    private static MeshToolWrapper wrapper(String methodName, List<String> capabilities)
            throws Exception {
        Method method = null;
        for (Method m : ToolBean.class.getDeclaredMethods()) {
            if (m.getName().equals(methodName)) {
                method = m;
            }
        }
        if (method == null) {
            throw new AssertionError("No such tool: " + methodName);
        }
        return new MeshToolWrapper(
            "ToolBean." + methodName, methodName, "test", new ToolBean(), method,
            capabilities, JsonMapper.builder().build());
    }
}
