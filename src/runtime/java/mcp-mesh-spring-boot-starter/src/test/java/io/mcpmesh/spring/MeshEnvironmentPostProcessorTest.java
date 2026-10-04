package io.mcpmesh.spring;

import io.mcpmesh.MeshAgent;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.core.env.MapPropertySource;
import org.springframework.mock.env.MockEnvironment;

import java.util.Map;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1592: the env-to-Spring-property mapping (TLS, port, media) applies to
 * every app the mesh runtime runs in — not only one whose MAIN class carries
 * {@code @MeshAgent}; a consumer-only app under {@code MCP_MESH_TLS_MODE} used
 * to serve plain HTTP. An app that did not opt in with {@code @MeshAgent} gets
 * the mapped values at the LOWEST precedence, so its own explicit
 * configuration still wins.
 */
class MeshEnvironmentPostProcessorTest {

    @MeshAgent(name = "annotated")
    static class AnnotatedMain {
    }

    /** A consumer-only app: no @MeshAgent anywhere on the main class. */
    static class ConsumerOnlyMain {
    }

    private static final Function<String, String> NO_ENV = k -> null;

    private static Function<String, String> env(Map<String, String> vars) {
        return vars::get;
    }

    private static MockEnvironment tlsEnvironment() {
        MockEnvironment env = new MockEnvironment();
        env.setProperty("MCP_MESH_TLS_MODE", "strict");
        env.setProperty("MCP_MESH_TLS_CERT", "/certs/agent.pem");
        env.setProperty("MCP_MESH_TLS_KEY", "/certs/agent-key.pem");
        env.setProperty("MCP_MESH_TLS_CA", "/certs/ca.pem");
        return env;
    }

    private static void process(MockEnvironment env, Class<?> main, Function<String, String> getenv) {
        new MeshEnvironmentPostProcessor().process(env, new SpringApplication(main), getenv);
    }

    @Test
    void annotatedMainClassGetsTls() {
        MockEnvironment env = tlsEnvironment();
        process(env, AnnotatedMain.class, NO_ENV);

        assertEquals("/certs/agent.pem", env.getProperty("server.ssl.certificate"));
        assertEquals("need", env.getProperty("server.ssl.client-auth"));
    }

    @Test
    void consumerOnlyAppGetsTlsToo() {
        MockEnvironment env = tlsEnvironment();
        process(env, ConsumerOnlyMain.class, NO_ENV);

        assertEquals("/certs/agent.pem", env.getProperty("server.ssl.certificate"),
            "a consumer-only app under MCP_MESH_TLS_MODE must not serve plain HTTP");
        assertEquals("/certs/agent-key.pem", env.getProperty("server.ssl.certificate-private-key"));
        assertEquals("/certs/ca.pem", env.getProperty("server.ssl.trust-certificate"));
    }

    @Test
    void consumerOnlyAppWithTlsModeButNoCertStillFailsFast() {
        MockEnvironment env = new MockEnvironment();
        env.setProperty("MCP_MESH_TLS_MODE", "strict");
        assertThrows(IllegalStateException.class, () -> process(env, ConsumerOnlyMain.class, NO_ENV));
    }

    @Test
    void consumerOnlyApp_explicitServerPortWins_meshPortOnlyFillsTheGap() {
        Function<String, String> getenv = env(Map.of("MCP_MESH_HTTP_PORT", "8080"));

        MockEnvironment configured = new MockEnvironment();
        configured.setProperty("server.port", "9090");
        process(configured, ConsumerOnlyMain.class, getenv);
        assertEquals("9090", configured.getProperty("server.port"),
            "the app's own server.port must win over the Helm chart's MCP_MESH_HTTP_PORT");

        MockEnvironment unconfigured = new MockEnvironment();
        process(unconfigured, ConsumerOnlyMain.class, getenv);
        assertEquals("8080", unconfigured.getProperty("server.port"), "fills the gap");
    }

    @Test
    void consumerOnlyApp_explicitSslWins() {
        MockEnvironment env = tlsEnvironment();
        env.setProperty("server.ssl.certificate", "/app/own.pem");
        process(env, ConsumerOnlyMain.class, NO_ENV);
        assertEquals("/app/own.pem", env.getProperty("server.ssl.certificate"));
    }

    @Test
    void consumerOnlyApp_meshValuesStayAboveDefaultProperties() {
        MockEnvironment env = new MockEnvironment();
        env.getPropertySources().addLast(
            new MapPropertySource("defaultProperties", Map.of("server.port", "1111")));
        process(env, ConsumerOnlyMain.class, env(Map.of("MCP_MESH_HTTP_PORT", "8080")));
        assertEquals("8080", env.getProperty("server.port"));
    }

    @Test
    void meshAgentMain_meshPortStillOverridesTheAppsOwn() {
        MockEnvironment env = new MockEnvironment();
        env.setProperty("server.port", "9090");
        process(env, AnnotatedMain.class, env(Map.of("MCP_MESH_HTTP_PORT", "8080")));
        assertEquals("8080", env.getProperty("server.port"), "unchanged @MeshAgent behaviour");
    }

    @Test
    void bootstrapContextIsSkipped() {
        MockEnvironment env = tlsEnvironment();
        env.getPropertySources().addFirst(new MapPropertySource(
            MeshEnvironmentPostProcessor.BOOTSTRAP_PROPERTY_SOURCE, Map.of()));
        process(env, AnnotatedMain.class, env(Map.of("MCP_MESH_HTTP_PORT", "8080")));

        assertNull(env.getProperty("server.port"));
        assertNull(env.getProperty("server.ssl.certificate"));
    }

    @Test
    void excludingMeshAutoConfigurationOptsOut_commaForm() {
        MockEnvironment env = tlsEnvironment();
        env.setProperty("spring.autoconfigure.exclude",
            "com.example.Other," + MeshAutoConfiguration.class.getName());
        process(env, ConsumerOnlyMain.class, NO_ENV);

        assertNull(env.getProperty("server.ssl.certificate"));
    }

    @Test
    void excludingMeshAutoConfigurationOptsOut_yamlListForm() {
        MockEnvironment env = tlsEnvironment();
        env.setProperty("spring.autoconfigure.exclude[0]", "com.example.Other");
        env.setProperty("spring.autoconfigure.exclude[1]", MeshAutoConfiguration.class.getName());
        process(env, ConsumerOnlyMain.class, NO_ENV);

        assertNull(env.getProperty("server.ssl.certificate"));
    }

    // Issue #1596: the Java runtime cannot serve the SPIRE provider. It used to
    // reach the native core and fail with Vault-specific advice; it now refuses
    // up front with a message that names the actual limitation.
    @Test
    void spireProviderIsRefusedBeforeTheCoreWithAnAccurateMessage() {
        MockEnvironment env = new MockEnvironment();
        env.setProperty("MCP_MESH_TLS_MODE", "strict");
        Function<String, String> getenv = env(Map.of(
            "MCP_MESH_TLS_PROVIDER", "spire",
            "MCP_MESH_AGENT_NAME", "java-agent"));

        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> process(env, AnnotatedMain.class, getenv));
        assertEquals(
            "MCP_MESH_TLS_PROVIDER=spire is not supported by the Java runtime; use file or vault.",
            e.getMessage());
        assertNull(e.getCause(), "the refusal must not come from a native TLS attempt");
    }

    @Test
    void spireProviderIsRefusedEvenWithCertFilesPresent() {
        MockEnvironment env = tlsEnvironment();
        Function<String, String> getenv = env(Map.of("MCP_MESH_TLS_PROVIDER", " SPIRE "));

        IllegalStateException e = assertThrows(IllegalStateException.class,
            () -> process(env, AnnotatedMain.class, getenv));
        assertEquals(MeshTlsConfig.SPIRE_UNSUPPORTED_MESSAGE, e.getMessage());
    }

    @Test
    void spireProviderIsIgnoredWhileTlsIsOff() {
        MockEnvironment env = new MockEnvironment();
        env.setProperty("MCP_MESH_TLS_MODE", "off");

        assertDoesNotThrow(() -> process(env, AnnotatedMain.class,
            env(Map.of("MCP_MESH_TLS_PROVIDER", "spire"))));
        assertNull(env.getProperty("server.ssl.certificate"));
    }

    @Test
    void requireSupportedProviderAcceptsFileAndVault() {
        assertDoesNotThrow(() -> MeshTlsConfig.requireSupportedProvider("strict", "file"));
        assertDoesNotThrow(() -> MeshTlsConfig.requireSupportedProvider("auto", "vault"));
        assertDoesNotThrow(() -> MeshTlsConfig.requireSupportedProvider("auto", null));
        assertDoesNotThrow(() -> MeshTlsConfig.requireSupportedProvider(null, "spire"));
        assertThrows(IllegalStateException.class,
            () -> MeshTlsConfig.requireSupportedProvider("auto", "spire"));
    }
}
