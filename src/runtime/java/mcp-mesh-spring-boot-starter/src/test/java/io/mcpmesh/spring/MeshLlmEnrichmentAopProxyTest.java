package io.mcpmesh.spring;

import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.types.MeshLlmAgent;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.aop.support.AopUtils;

import java.lang.reflect.Method;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1164 MED-1: {@code @MeshLlm} provider enrichment must resolve for
 * AOP-proxied beans.
 *
 * <p>{@link MeshLlmRegistry#register} keys configs by
 * {@code AopUtils.getTargetClass(bean).getName()} (the post-processor unwraps
 * CGLIB proxies), but {@code enrichToolsWithLlmProvider} previously built its
 * lookup key from {@code meta.bean().getClass().getName()} — for a Spring-
 * proxied bean ({@code @Transactional}/{@code @Async}/{@code @Validated}) the
 * runtime class is {@code Foo$$SpringCGLIB$$0}, the lookup returned null, and
 * the {@code llm_provider} selector silently never reached the heartbeat.
 */
@DisplayName("enrichToolsWithLlmProvider — AOP-proxied bean key unwrap (issue #1164 MED-1)")
class MeshLlmEnrichmentAopProxyTest {

    public static class ChatAgent {
        @MeshTool(capability = "chat", description = "chat tool")
        @MeshLlm(providerSelector = @Selector(capability = "llm", tags = {"+claude"}))
        public String chat(@Param("question") String question, MeshLlmAgent llm) {
            return "ok";
        }
    }

    @Test
    @DisplayName("CGLIB-proxied @MeshLlm bean resolves its provider selector")
    void cglibProxiedMeshLlmBeanGetsLlmProviderEnrichment() throws Exception {
        // Build a REAL CGLIB proxy — the same shape @Transactional/@Async/
        // @Validated produce at runtime (class name contains $$).
        ProxyFactory pf = new ProxyFactory(new ChatAgent());
        pf.setProxyTargetClass(true);
        Object proxiedBean = pf.getProxy();
        assertNotEquals(ChatAgent.class, proxiedBean.getClass(),
            "Proxy runtime class must differ from the user class for this test to be meaningful");
        assertEquals(ChatAgent.class, AopUtils.getTargetClass(proxiedBean),
            "AopUtils must unwrap the proxy back to the user class");

        Method method = ChatAgent.class.getMethod("chat", String.class, MeshLlmAgent.class);

        // Registration mirrors the post-processors: MeshLlmRegistry keys by
        // the unwrapped target class; MeshToolRegistry stores the (proxied)
        // bean instance.
        MeshLlmRegistry llmRegistry = new MeshLlmRegistry();
        llmRegistry.register(ChatAgent.class, method, method.getAnnotation(MeshLlm.class));

        MeshToolRegistry toolRegistry = new MeshToolRegistry();
        toolRegistry.registerTool(proxiedBean, method, method.getAnnotation(MeshTool.class));

        List<AgentSpec.ToolSpec> tools = toolRegistry.getToolSpecs();
        MeshAutoConfiguration.enrichToolsWithLlmProvider(
            tools, toolRegistry, llmRegistry, MeshObjectMappers.create());

        AgentSpec.ToolSpec spec = tools.stream()
            .filter(t -> "chat".equals(t.getCapability()))
            .findFirst()
            .orElseThrow(() -> new AssertionError("chat tool spec missing"));

        assertNotNull(spec.getLlmProvider(),
            "llmProvider must be set on the tool spec even when the bean is AOP-proxied "
                + "(registration key uses AopUtils.getTargetClass; lookup must match)");
        assertTrue(spec.getLlmProvider().contains("\"capability\":\"llm\""),
            "llmProvider JSON must carry the selector capability. Got: " + spec.getLlmProvider());
        assertTrue(spec.getLlmProvider().contains("+claude"),
            "llmProvider JSON must carry the selector tags. Got: " + spec.getLlmProvider());
    }

    @Test
    @DisplayName("unproxied bean still resolves (regression guard)")
    void plainBeanStillResolves() throws Exception {
        ChatAgent bean = new ChatAgent();
        Method method = ChatAgent.class.getMethod("chat", String.class, MeshLlmAgent.class);

        MeshLlmRegistry llmRegistry = new MeshLlmRegistry();
        llmRegistry.register(ChatAgent.class, method, method.getAnnotation(MeshLlm.class));

        MeshToolRegistry toolRegistry = new MeshToolRegistry();
        toolRegistry.registerTool(bean, method, method.getAnnotation(MeshTool.class));

        List<AgentSpec.ToolSpec> tools = toolRegistry.getToolSpecs();
        MeshAutoConfiguration.enrichToolsWithLlmProvider(
            tools, toolRegistry, llmRegistry, MeshObjectMappers.create());

        assertNotNull(tools.get(0).getLlmProvider(),
            "llmProvider must be set for a plain (unproxied) bean");
    }
}
