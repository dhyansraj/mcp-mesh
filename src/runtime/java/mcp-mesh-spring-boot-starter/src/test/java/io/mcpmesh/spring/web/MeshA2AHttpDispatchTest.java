package io.mcpmesh.spring.web;

import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.MeshRuntime;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Regression test for the {@code MeshA2ADispatcherController} body-read
 * path over a real HTTP boundary (issue #932 follow-up).
 *
 * <p><strong>Background.</strong> The earlier slice test
 * ({@link MeshA2AControllerSliceTest}) drives the
 * {@link org.springframework.web.servlet.function.RouterFunction} directly via
 * {@code ServerRequest.create} with an explicit
 * {@link org.springframework.http.converter.StringHttpMessageConverter}. That
 * lets the test feed bodies into the dispatcher pipeline without involving
 * Spring Boot's actual message-converter resolution — which is precisely
 * what hid the bug surfaced by the Java A2A producer smoke test.
 *
 * <p>Under Spring Boot 4 / Jackson 3 (Spring 7.0.x), calling
 * {@code ServerRequest.body(String.class)} on a request with
 * {@code Content-Type: application/json} throws because no
 * {@code HttpMessageConverter<String>} is registered that accepts
 * {@code application/json} on the functional router path. The old
 * {@code readBody} swallowed the exception and returned an empty string,
 * which then parsed as a missing JSON-RPC method — so every well-formed
 * {@code tasks/send} produced a {@code -32601 Method not implemented:
 * 'null'} error with {@code id=null}.
 *
 * <p>This test reproduces the production failure mode by booting a real
 * Spring Boot context on a random port and POSTing via the JDK
 * {@link java.net.http.HttpClient} (Spring Boot 4 removed
 * {@code TestRestTemplate}; we want zero test-side message-converter
 * machinery so the only converter resolution that happens is on the producer
 * side — exactly what we want to exercise). The slice test cannot exercise
 * this path by construction.
 *
 * <p>The test covers the four canonical body-read outcomes per JSON-RPC
 * spec §4.1:
 * <ul>
 *   <li>Valid {@code tasks/send} → {@code result.status.state}, not an error;</li>
 *   <li>Valid {@code tasks/get} (unknown id) → {@code -32602 Invalid params};</li>
 *   <li>Malformed JSON body → {@code -32700 Parse error};</li>
 *   <li>Empty body → {@code -32700 Parse error};</li>
 *   <li>Valid JSON missing {@code method} → {@code -32600 Invalid Request};</li>
 *   <li>Unknown method → {@code -32601 Method not found} with the actual
 *       method name (not {@code 'null'}).</li>
 * </ul>
 */
@SpringBootTest(
    classes = MeshA2AHttpDispatchTest.TestApp.class,
    webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {
        // Keep the producer-agent metadata stable across the test JVM —
        // the runtime is stubbed below, but heartbeat scrubbing still
        // reads these from the environment.
        "mcpmesh.agent.name=http-dispatch-test-agent",
        "mcpmesh.agent.host=127.0.0.1",
        "logging.level.io.mcpmesh=WARN"
    }
)
@DisplayName("MeshA2A producer — real HTTP boundary regression (issue #932)")
class MeshA2AHttpDispatchTest {

    private static final ObjectMapper JSON = JsonMapper.builder().build();
    private static final String PATH = "/agents/http-test";

    @LocalServerPort
    private int port;

    private static final HttpClient HTTP_CLIENT = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build();

    private URI url() {
        return URI.create("http://127.0.0.1:" + port + PATH);
    }

    /**
     * POST a raw body to the producer surface as
     * {@code Content-Type: application/json}. We use the JDK
     * {@link HttpClient} (rather than Spring's {@code TestRestTemplate},
     * which was removed in Spring Boot 4) so the test layer adds zero
     * message-converter machinery — the only converter resolution that
     * happens is on the producer side, which is exactly what we want
     * to exercise.
     */
    private HttpResponse<String> post(String body) throws Exception {
        HttpRequest request = HttpRequest.newBuilder()
            .uri(url())
            .timeout(Duration.ofSeconds(10))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build();
        return HTTP_CLIENT.send(request, HttpResponse.BodyHandlers.ofString());
    }

    private JsonNode parse(String body) throws Exception {
        return JSON.readTree(body == null ? "" : body);
    }

    /** Pre-fix: this returned -32601 with method='null'. Post-fix: it must
     *  return a real Task envelope with state=completed. */
    @Test
    @DisplayName("POST tasks/send (valid JSON-RPC) → state=completed, not -32601")
    void tasksSendOverHttp_returnsCompletedState() throws Exception {
        String body = JSON.writeValueAsString(Map.of(
            "jsonrpc", "2.0",
            "id", 1,
            "method", "tasks/send",
            "params", Map.of(
                "id", "t-http-1",
                "message", Map.of("role", "user",
                    "parts", List.of(Map.of("type", "text", "text", "hello"))))));

        HttpResponse<String> resp = post(body);

        assertThat(resp.statusCode())
            .as("Body: %s", resp.body()).isEqualTo(200);
        JsonNode env = parse(resp.body());
        // Critical regression assertion: pre-fix this branch returned
        // {"error":{"code":-32601,"message":"Method not implemented: 'null'"}}
        // because readBody swallowed the converter exception.
        assertThat(env.has("error"))
            .as("Expected success envelope, got error: %s", resp.body())
            .isFalse();
        assertThat(env.get("id").asInt()).isEqualTo(1);
        JsonNode result = env.get("result");
        assertThat(result).isNotNull();
        assertThat(result.get("id").asText()).isEqualTo("t-http-1");
        assertThat(result.get("status").get("state").asText()).isEqualTo("completed");
    }

    /** Pre-fix: same -32601 method='null' bug. Post-fix: dispatcher reaches
     *  handleTasksGet which returns -32602 for the unknown id. */
    @Test
    @DisplayName("POST tasks/get (unknown id) → -32602 Invalid params, not -32601")
    void tasksGetOverHttp_unknownId_returnsInvalidParams() throws Exception {
        String body = JSON.writeValueAsString(Map.of(
            "jsonrpc", "2.0",
            "id", 2,
            "method", "tasks/get",
            "params", Map.of("id", "does-not-exist")));

        HttpResponse<String> resp = post(body);

        JsonNode env = parse(resp.body());
        assertThat(env.has("error"))
            .as("Body: %s", resp.body()).isTrue();
        assertThat(env.get("error").get("code").asInt())
            .as("Pre-fix this was -32601 method='null'; post-fix it must be -32602 unknown id")
            .isEqualTo(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS);
        assertThat(env.get("error").get("message").asText()).contains("Unknown task id");
    }

    /** Spec §4.1: malformed JSON → -32700 Parse error. Pre-fix the
     *  request never reached the dispatcher's JSON parse (because
     *  readBody dropped the body) so the same -32601 method='null'
     *  appeared. Post-fix the raw body reaches the dispatcher and
     *  Jackson's tree parse produces -32700 cleanly. */
    @Test
    @DisplayName("POST malformed JSON body → -32700 Parse error (not -32601)")
    void malformedJsonOverHttp_returnsParseError() throws Exception {
        HttpResponse<String> resp = post("not json");

        assertThat(resp.statusCode()).isEqualTo(400);
        JsonNode env = parse(resp.body());
        assertThat(env.get("error").get("code").asInt())
            .isEqualTo(MeshA2ADispatcher.JSONRPC_PARSE_ERROR);
    }

    /** Empty body must also produce a Parse error per spec §4.1. */
    @Test
    @DisplayName("POST empty body → -32700 Parse error")
    void emptyBodyOverHttp_returnsParseError() throws Exception {
        HttpResponse<String> resp = post("");

        assertThat(resp.statusCode()).isEqualTo(400);
        JsonNode env = parse(resp.body());
        assertThat(env.get("error").get("code").asInt())
            .isEqualTo(MeshA2ADispatcher.JSONRPC_PARSE_ERROR);
    }

    /** Spec §4.1: valid JSON missing required `method` → -32600
     *  Invalid Request. Pre-fix the dispatcher's default switch case
     *  emitted -32601 method='null' — wrong code, misleading message. */
    @Test
    @DisplayName("POST valid JSON missing 'method' → -32600 Invalid Request")
    void missingMethodOverHttp_returnsInvalidRequest() throws Exception {
        String body = JSON.writeValueAsString(Map.of(
            "jsonrpc", "2.0",
            "id", 3,
            "params", Map.of()));

        HttpResponse<String> resp = post(body);

        JsonNode env = parse(resp.body());
        assertThat(env.has("error"))
            .as("Body: %s", resp.body()).isTrue();
        assertThat(env.get("error").get("code").asInt())
            .as("Spec §4.1: missing method is -32600 Invalid Request, not -32601 method='null'")
            .isEqualTo(MeshA2ADispatcher.JSONRPC_INVALID_REQUEST);
    }

    /** Pre-fix: error message read "Method not implemented: 'null'" for
     *  any unknown method (because the body never reached the parser).
     *  Post-fix: the ACTUAL method name appears in the message. */
    @Test
    @DisplayName("POST unknown method → -32601 with real method name (not 'null')")
    void unknownMethodOverHttp_carriesActualMethodName() throws Exception {
        String body = JSON.writeValueAsString(Map.of(
            "jsonrpc", "2.0",
            "id", 4,
            "method", "nonexistent/foo",
            "params", Map.of()));

        HttpResponse<String> resp = post(body);

        JsonNode env = parse(resp.body());
        assertThat(env.get("error").get("code").asInt())
            .isEqualTo(MeshA2ADispatcher.JSONRPC_METHOD_NOT_FOUND);
        String msg = env.get("error").get("message").asText();
        assertThat(msg)
            .as("Pre-fix this said \"Method not implemented: 'null'\"; "
                + "post-fix it must carry the actual method name")
            .contains("nonexistent/foo")
            .doesNotContain("'null'");
        assertThat(env.get("id").asInt())
            .as("Pre-fix the id was null too because the body never reached the parser")
            .isEqualTo(4);
    }

    /** Regression for the body-size cap (CodeRabbit A8). A request body larger
     *  than {@link MeshA2ADispatcherController#DEFAULT_MAX_BODY_BYTES} (1 MiB)
     *  MUST be rejected with HTTP 400 + JSON-RPC -32700 rather than draining
     *  the entire stream into memory. */
    @Test
    @DisplayName("POST body > 1 MiB → 400 Parse error, NOT OOM")
    void oversizedBody_returnsParseErrorNotOom() throws Exception {
        // 1 MiB + 1 byte of arbitrary garbage. Doesn't need to be valid JSON —
        // the size cap must trip before the parser sees a single byte.
        int oversized = (int) MeshA2ADispatcherController.DEFAULT_MAX_BODY_BYTES + 1;
        char[] padding = new char[oversized];
        java.util.Arrays.fill(padding, 'x');
        String body = new String(padding);

        HttpResponse<String> resp = post(body);

        assertThat(resp.statusCode())
            .as("Oversized body MUST be rejected with 400 (got body=%s)", resp.body())
            .isEqualTo(400);
        JsonNode env = parse(resp.body());
        assertThat(env.get("error").get("code").asInt())
            .as("Oversize-body rejection MUST surface as JSON-RPC -32700 Parse error")
            .isEqualTo(MeshA2ADispatcher.JSONRPC_PARSE_ERROR);
    }

    // ─────────────────────────────────────────────────────────────────
    // Test fixtures
    // ─────────────────────────────────────────────────────────────────

    /** Spring Boot application stub — registers an A2A surface and pins
     *  a no-op {@link MeshRuntime} so the JVM does not try to load the
     *  native Rust core during the test.
     *
     *  <p>Relies on the starter's {@code AutoConfiguration.imports} file to
     *  wire {@code MeshAutoConfiguration} via Spring Boot's auto-configuration
     *  machinery. We do NOT {@code @Import} the auto-config explicitly because
     *  that pathway registers it as a user-config and breaks
     *  {@code @ConditionalOnMissingBean} ordering for the {@code meshRuntime}
     *  bean override. */
    @SpringBootApplication
    static class TestApp {

        @Component
        public static class HttpTestSkill {
            @MeshA2A(path = PATH, skillId = "http-test", skillName = "HTTP Test")
            public Map<String, Object> handle(Map<String, Object> message) {
                return Map.of("ok", true);
            }
        }

        /**
         * No-op {@link MeshRuntime} so the {@link org.springframework.context.SmartLifecycle}
         * processor doesn't spin up the native core. Mirrors the pattern
         * from {@link MeshA2AContextLoadTest} so the boot doesn't try to
         * load the FFI dylib on the test classpath.
         */
        @Bean
        public MeshRuntime meshRuntime(ApplicationContext applicationContext) {
            // Mirror MeshAutoConfiguration.buildAgentSpec()'s eager scan so the
            // bean-creation graph matches production — production scans BOTH
            // @Component and @Service, so the test must too if it wants to
            // exercise the same cycle scenario.
            applicationContext.getBeansWithAnnotation(Component.class);
            applicationContext.getBeansWithAnnotation(Service.class);

            AgentSpec spec = new AgentSpec();
            spec.setName("http-dispatch-test-agent");
            spec.setAgentId("http-dispatch-test-agent-00000000");

            return new MeshRuntime(spec) {
                private volatile boolean running;
                @Override public void start() { running = true; }
                @Override public void stop() { running = false; }
                @Override public boolean isRunning() { return running; }
            };
        }
    }
}
