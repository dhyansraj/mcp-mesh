package io.mcpmesh.spring;

import io.mcpmesh.core.MeshObjectMappers;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for the {@code modelParams} escape-hatch on the buffered
 * {@code generate()} path — issue #1019.
 *
 * <p>The Java SDK exposes a typed builder surface ({@code maxTokens},
 * {@code temperature}, {@code topP}, {@code stop}) whose values map to wire
 * {@code model_params} keys. For vendor-specific kwargs that the typed surface
 * doesn't expose (e.g., Gemini {@code thinking_config}, Anthropic
 * {@code output_config}, OpenAI {@code reasoning_effort}) callers can pass an
 * arbitrary {@code Map<String, Object>} via {@code .modelParams(...)}. The map
 * is merged into the wire {@code model_params} BEFORE typed setters so typed
 * values win on collision and the typed surface stays authoritative.
 *
 * <p>Mirrors {@code MeshLlmAgentProxyStreamTest}'s wiring: a real
 * {@link McpHttpClient} pointed at a {@link MockWebServer} that returns the
 * MCP tools/call shape the LLM provider produces. We inspect the captured
 * request body to assert the {@code model_params} merge semantics.
 */
@DisplayName("MeshLlmAgentProxy.generate() — modelParams escape hatch (issue #1019)")
class MeshLlmAgentProxyModelParamsTest {

    private MockWebServer server;
    private McpHttpClient client;
    private ObjectMapper mapper;
    private MeshLlmAgentProxy proxy;

    @BeforeAll
    static void initTlsConfig() throws Exception {
        // Pre-seed MeshTlsConfig.cached so tests don't hit native FFI
        Constructor<MeshTlsConfig> ctor = MeshTlsConfig.class.getDeclaredConstructor(
            boolean.class, String.class, String.class, String.class, String.class);
        ctor.setAccessible(true);
        MeshTlsConfig disabled = ctor.newInstance(false, "off", null, null, null);

        Field cachedField = MeshTlsConfig.class.getDeclaredField("cached");
        cachedField.setAccessible(true);
        cachedField.set(null, disabled);
    }

    @BeforeEach
    void setUp() throws Exception {
        server = new MockWebServer();
        server.start();
        mapper = MeshObjectMappers.create();
        client = new McpHttpClient(mapper);

        proxy = new MeshLlmAgentProxy("test.modelparams");
        // Configure with maxIterations=1 so generate() returns after a single LLM call.
        // The 8-arg overload leaves maxTokens/temperature at the sentinel defaults
        // (-1 / NaN), so neither key is injected unless a per-call setter supplies one.
        // parallelToolCalls=false.
        proxy.configure(client, null, null, null, "", "ctx", 1, false);
        proxy.updateProvider(
            server.url("/").toString().replaceAll("/$", ""),
            "process_chat",
            "mesh-delegated"
        );
    }

    @AfterEach
    void tearDown() throws Exception {
        if (client != null) client.close();
        server.shutdown();
    }

    // -------------------------------------------------------------------------
    // Mock helpers — return the MCP tools/call shape the LLM provider produces.
    // The inner `content[0].text` is a JSON-encoded mesh-provider response:
    //     { role, content, tool_calls?, _mesh_usage? }
    // -------------------------------------------------------------------------

    private MockResponse stubLlmResponse(String reply) {
        long id = System.currentTimeMillis();
        Map<String, Object> innerPayload = Map.of(
            "role", "assistant",
            "content", reply
        );
        String innerJson;
        try {
            innerJson = mapper.writeValueAsString(innerPayload);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        Map<String, Object> envelope = Map.of(
            "jsonrpc", "2.0",
            "id", id,
            "result", Map.of(
                "content", java.util.List.of(
                    Map.of("type", "text", "text", innerJson)
                )
            )
        );
        String body;
        try {
            body = mapper.writeValueAsString(envelope);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        return new MockResponse()
            .setBody(body)
            .setHeader("Content-Type", "application/json");
    }

    /**
     * Stub an LLM response that requests a single tool call. Mirrors the nested
     * MCP shape: {@code content[0].text} is a JSON object carrying {@code tool_calls}.
     */
    private MockResponse stubToolCallResponse(String callId, String toolName, Map<String, Object> args) {
        long id = System.currentTimeMillis();
        Map<String, Object> toolCall = Map.of(
            "id", callId,
            "type", "function",
            "function", Map.of(
                "name", toolName,
                "arguments", args
            )
        );
        Map<String, Object> innerPayload = Map.of(
            "role", "assistant",
            "content", "",
            "tool_calls", java.util.List.of(toolCall)
        );
        String innerJson;
        try {
            innerJson = mapper.writeValueAsString(innerPayload);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        Map<String, Object> envelope = Map.of(
            "jsonrpc", "2.0",
            "id", id,
            "result", Map.of(
                "content", java.util.List.of(
                    Map.of("type", "text", "text", innerJson)
                )
            )
        );
        String body;
        try {
            body = mapper.writeValueAsString(envelope);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        return new MockResponse()
            .setBody(body)
            .setHeader("Content-Type", "application/json");
    }

    /** Read the captured outbound request body and pull out the model_params node. */
    private JsonNode readModelParams(RecordedRequest request) throws Exception {
        String body = request.getBody().readUtf8();
        JsonNode root = mapper.readTree(body);
        JsonNode args = root.get("params").get("arguments");
        JsonNode req = args.get("request");
        JsonNode modelParams = req.get("model_params");
        assertNotNull(modelParams, "request.model_params must be present");
        return modelParams;
    }

    // -------------------------------------------------------------------------
    // Tests
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("modelParams keys flow into the wire request's model_params")
    void modelParamsKeysFlowThrough() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        String result = proxy.request()
            .user("hi")
            .modelParams(Map.of(
                "thinking_config", Map.of("thinking_budget", 0),
                "reasoning_effort", "high"
            ))
            .generate();

        assertEquals("ok", result);

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        JsonNode thinking = modelParams.get("thinking_config");
        assertNotNull(thinking, "thinking_config must be present in model_params");
        assertEquals(0, thinking.get("thinking_budget").asInt());
        assertEquals("high", modelParams.get("reasoning_effort").asText());

        // With sentinel defaults and no per-call setter, the typed keys are NOT
        // injected — the provider's own defaults apply (parity with Python/TS).
        assertFalse(modelParams.has("max_tokens"));
        assertFalse(modelParams.has("temperature"));
    }

    @Test
    @DisplayName("typed setter (.temperature) wins over modelParams on collision")
    void typedSetterWinsOnCollision() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        // Builder typed-temperature is 0.5; .modelParams supplies 0.9 for the
        // same key. The merge order in executeAgenticLoop must put the user
        // modelParams FIRST so the typed .put("temperature", ...) overwrites.
        Map<String, Object> userModelParams = new LinkedHashMap<>();
        userModelParams.put("temperature", 0.9);
        userModelParams.put("max_tokens", 999);                       // typed maxTokens overrides
        userModelParams.put("thinking_config", Map.of("thinking_budget", 0));

        proxy.request()
            .user("hi")
            .temperature(0.5)
            .maxTokens(200)
            .modelParams(userModelParams)
            .generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        assertEquals(0.5, modelParams.get("temperature").asDouble(), 1e-9,
            "typed .temperature(0.5) must win over modelParams temperature=0.9");
        assertEquals(200, modelParams.get("max_tokens").asInt(),
            "typed .maxTokens(200) must win over modelParams max_tokens=999");
        // Vendor-specific key (no typed equivalent) flows through untouched
        assertEquals(0, modelParams.get("thinking_config").get("thinking_budget").asInt());
    }

    @Test
    @DisplayName("vendor-specific keys flow through untouched (no key translation)")
    void vendorSpecificKeysUntouched() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        Map<String, Object> outputConfig = Map.of(
            "format", Map.of(
                "type", "json_schema",
                "schema", Map.of("type", "object")
            )
        );

        proxy.request()
            .user("hi")
            .modelParams(Map.of(
                "output_config", outputConfig,
                "extra_headers", Map.of("x-vendor-flag", "1")
            ))
            .generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        JsonNode oc = modelParams.get("output_config");
        assertNotNull(oc, "output_config must be present");
        assertEquals("json_schema", oc.get("format").get("type").asText());
        assertEquals("object", oc.get("format").get("schema").get("type").asText());

        JsonNode headers = modelParams.get("extra_headers");
        assertNotNull(headers);
        assertEquals("1", headers.get("x-vendor-flag").asText());
    }

    @Test
    @DisplayName("modelParams can set max_tokens when no typed .maxTokens() setter is used")
    void modelParamsCanSetMaxTokensWhenNoTypedSetter() throws Exception {
        // Regression: previously the unconditional `modelParams.put("max_tokens", defaults)`
        // clobbered any value the caller passed via .modelParams(Map.of("max_tokens", 999)).
        // TS path guards with `if (options?.maxOutputTokens) ...`; Java must match.
        server.enqueue(stubLlmResponse("ok"));

        proxy.request()
            .user("hi")
            // NO .maxTokens() typed setter — only the escape-hatch.
            .modelParams(Map.of("max_tokens", 999))
            .generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        assertEquals(999, modelParams.get("max_tokens").asInt(),
            "modelParams.max_tokens=999 must reach the wire when no typed .maxTokens() is set;"
            + " annotation default (4096) must NOT clobber it");
    }

    @Test
    @DisplayName("modelParams can set temperature when no typed .temperature() setter is used")
    void modelParamsCanSetTemperatureWhenNoTypedSetter() throws Exception {
        // Same regression shape as the max_tokens test above, for temperature.
        server.enqueue(stubLlmResponse("ok"));

        proxy.request()
            .user("hi")
            // NO .temperature() typed setter — only the escape-hatch.
            .modelParams(Map.of("temperature", 0.123))
            .generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        assertEquals(0.123, modelParams.get("temperature").asDouble(), 1e-9,
            "modelParams.temperature=0.123 must reach the wire when no typed .temperature() is set;"
            + " annotation default (0.7) must NOT clobber it");
    }

    @Test
    @DisplayName("successive .modelParams(...) calls REPLACE prior values (last-call-wins)")
    void modelParamsSuccessiveCallsReplace() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        Map<String, Object> m1 = Map.of(
            "thinking_config", Map.of("thinking_budget", 0),
            "reasoning_effort", "high"
        );
        Map<String, Object> m2 = Map.of(
            "reasoning_effort", "low"
        );

        proxy.request()
            .user("hi")
            .modelParams(m1)
            .modelParams(m2)
            .generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        // m2's keys present
        assertEquals("low", modelParams.get("reasoning_effort").asText(),
            "second .modelParams() call must overwrite reasoning_effort to 'low'");
        // m1-only keys absent (REPLACE semantics, not merge)
        assertFalse(modelParams.has("thinking_config"),
            "thinking_config from the FIRST .modelParams() call must be absent —"
            + " successive calls REPLACE, do not merge");
    }

    @Test
    @DisplayName("@MeshLlm(maxTokens, temperature) annotation defaults flow through to wire model_params")
    void annotationDefaultsFromMeshLlmFlowToWire() throws Exception {
        // Regression: MeshLlmAgentProxy previously hardcoded defaultMaxTokens=4096
        // and defaultTemperature=0.7. The @MeshLlm(maxTokens=…, temperature=…)
        // annotation values carried by MeshLlmRegistry.LlmConfig were never wired
        // through MeshEventProcessor → proxy.configure(...). Now the 10-arg
        // configure overload accepts them and writes them onto the proxy so a
        // user-supplied annotation value reaches the wire.
        server.enqueue(stubLlmResponse("ok"));

        // Re-configure proxy via the 10-arg overload simulating @MeshLlm(maxTokens=2000, temperature=0.3).
        proxy.configure(client, null, null, null, "", "ctx", 1, false, 2000, 0.3);

        proxy.request()
            .user("hi")
            // NO typed .maxTokens()/.temperature() and NO .modelParams() — defaults must surface.
            .generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        assertEquals(2000, modelParams.get("max_tokens").asInt(),
            "@MeshLlm(maxTokens=2000) must reach the wire — not the hardcoded 4096 default");
        assertEquals(0.3, modelParams.get("temperature").asDouble(), 1e-9,
            "@MeshLlm(temperature=0.3) must reach the wire — not the hardcoded 0.7 default");
    }

    @Test
    @DisplayName("@MeshLlm(model=...) per-tool override flows into the wire model_params.model (GAP C3)")
    void meshLlmModelOverrideFlowsToWire() throws Exception {
        // C3: @MeshLlm(model="anthropic/claude-3-5-sonnet-latest") must surface as
        // model_params.model on the wire so the provider can honor it (same-vendor).
        server.enqueue(stubLlmResponse("ok"));

        // 12-arg configure overload simulates @MeshLlm(model="anthropic/claude-3-5-sonnet-latest").
        proxy.configure(client, null, null, null, "", "ctx", 1, false,
            io.mcpmesh.MeshLlmDefaults.MAX_TOKENS_UNSET, io.mcpmesh.MeshLlmDefaults.TEMPERATURE_UNSET,
            io.mcpmesh.MeshLlmDefaults.OUTPUT_MODE_UNSET, "anthropic/claude-3-5-sonnet-latest");

        proxy.request().user("hi").generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        assertEquals("anthropic/claude-3-5-sonnet-latest", modelParams.get("model").asText(),
            "@MeshLlm(model=...) must reach the wire as model_params.model");
    }

    @Test
    @DisplayName("per-call .modelParams(model) wins over @MeshLlm(model=...) annotation (GAP C3)")
    void perCallModelOverridesAnnotation() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        // Annotation says one model; the per-call escape hatch supplies another.
        proxy.configure(client, null, null, null, "", "ctx", 1, false,
            io.mcpmesh.MeshLlmDefaults.MAX_TOKENS_UNSET, io.mcpmesh.MeshLlmDefaults.TEMPERATURE_UNSET,
            io.mcpmesh.MeshLlmDefaults.OUTPUT_MODE_UNSET, "anthropic/claude-3-5-sonnet-latest");

        proxy.request()
            .user("hi")
            .modelParams(Map.of("model", "anthropic/claude-3-5-haiku-latest"))
            .generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        assertEquals("anthropic/claude-3-5-haiku-latest", modelParams.get("model").asText(),
            "a per-call .modelParams(Map.of(\"model\", ...)) must win over the @MeshLlm(model=...) annotation");
    }

    @Test
    @DisplayName("unset @MeshLlm model → no model key on the wire (provider uses its own model)")
    void unsetModelOmitsKey() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        // Default 8-arg configure leaves the model override empty.
        proxy.request().user("hi").generate();

        RecordedRequest req = server.takeRequest();
        JsonNode modelParams = readModelParams(req);

        assertFalse(modelParams.has("model"),
            "with no @MeshLlm(model=...) and no per-call override, model_params.model must be absent");
    }

    @Test
    @DisplayName("parallelToolCalls annotation honors user modelParams override (issue #1026)")
    void parallelToolCallsHonorsUserModelParamsOverride() throws Exception {
        // Issue #1026: previously `if (parallelToolCalls) modelParams.put("parallel_tool_calls", true)`
        // sat AFTER userModelParams.putAll() with NO containsKey guard. If the
        // annotation enabled parallel-tool-calls but the caller passed `false`
        // via .modelParams() to disable for one call, the annotation value
        // silently clobbered the user's `false`. Now follows the same
        // containsKey-guard pattern as max_tokens / temperature.

        // Case A: annotation parallelToolCalls=true, user overrides to false.
        proxy.configure(client, null, null, null, "", "ctx", 1, true);
        server.enqueue(stubLlmResponse("ok"));
        proxy.request()
            .user("hi")
            .modelParams(Map.of("parallel_tool_calls", false))
            .generate();
        JsonNode modelParamsA = readModelParams(server.takeRequest());
        assertEquals(false, modelParamsA.get("parallel_tool_calls").asBoolean(),
            "user-supplied parallel_tool_calls=false in modelParams must survive over annotation=true");

        // Case B: annotation parallelToolCalls=true, no user override → annotation wins.
        server.enqueue(stubLlmResponse("ok"));
        proxy.request()
            .user("hi")
            .generate();
        JsonNode modelParamsB = readModelParams(server.takeRequest());
        assertEquals(true, modelParamsB.get("parallel_tool_calls").asBoolean(),
            "annotation parallelToolCalls=true must reach the wire when caller passes no override (regression guard)");

        // Case C: annotation parallelToolCalls=false, user passes true → user value wins.
        proxy.configure(client, null, null, null, "", "ctx", 1, false);
        server.enqueue(stubLlmResponse("ok"));
        proxy.request()
            .user("hi")
            .modelParams(Map.of("parallel_tool_calls", true))
            .generate();
        JsonNode modelParamsC = readModelParams(server.takeRequest());
        assertEquals(true, modelParamsC.get("parallel_tool_calls").asBoolean(),
            "user-supplied parallel_tool_calls=true in modelParams must reach the wire when annotation is false");
    }

    @Test
    @DisplayName("null/empty modelParams → behavior unchanged from before this change")
    void nullOrEmptyModelParamsIsNoOp() throws Exception {
        server.enqueue(stubLlmResponse("ok"));
        server.enqueue(stubLlmResponse("ok"));
        server.enqueue(stubLlmResponse("ok"));

        // Baseline: no .modelParams() call at all
        proxy.request().user("hi").generate();
        JsonNode baseline = readModelParams(server.takeRequest());

        // null map → must not throw, must produce identical wire shape
        proxy.request().user("hi").modelParams(null).generate();
        JsonNode nullCase = readModelParams(server.takeRequest());

        // empty map → must not throw, must produce identical wire shape
        proxy.request().user("hi").modelParams(Map.of()).generate();
        JsonNode emptyCase = readModelParams(server.takeRequest());

        assertEquals(baseline.toString(), nullCase.toString(),
            "null modelParams must produce the same model_params as no call");
        assertEquals(baseline.toString(), emptyCase.toString(),
            "empty modelParams must produce the same model_params as no call");
    }

    @Test
    @DisplayName("unset maxTokens/temperature are deferred to the provider; per-call and annotation values are honored")
    void sentinelDefaultsDeferToProvider() throws Exception {
        // Case A: nothing set → neither key on the wire (provider default applies).
        server.enqueue(stubLlmResponse("ok"));
        proxy.request().user("hi").generate();
        JsonNode unset = readModelParams(server.takeRequest());
        assertFalse(unset.has("max_tokens"),
            "unset maxTokens must NOT be injected — defer to provider");
        assertFalse(unset.has("temperature"),
            "unset temperature must NOT be injected — defer to provider");
        // NaN must never appear on the wire (would break JSON).
        assertFalse(unset.toString().contains("NaN"),
            "NaN must never appear in model_params");

        // Case B: per-call typed setters → both present.
        server.enqueue(stubLlmResponse("ok"));
        proxy.request().user("hi").temperature(0.3).maxTokens(2000).generate();
        JsonNode perCall = readModelParams(server.takeRequest());
        assertEquals(2000, perCall.get("max_tokens").asInt());
        assertEquals(0.3, perCall.get("temperature").asDouble(), 1e-9);

        // Case C: explicit annotation values via the 10-arg overload → both present.
        proxy.configure(client, null, null, null, "", "ctx", 1, false, 1500, 0.2);
        server.enqueue(stubLlmResponse("ok"));
        proxy.request().user("hi").generate();
        JsonNode annotated = readModelParams(server.takeRequest());
        assertEquals(1500, annotated.get("max_tokens").asInt());
        assertEquals(0.2, annotated.get("temperature").asDouble(), 1e-9);
    }

    @Test
    @DisplayName("agentic loop runs multiple iterations: tool_calls response → tool result fed back → final content (maxIterations=10)")
    void multiIterationAgenticLoopFeedsToolResultBack() throws Exception {
        // Default maxIterations is now 10 (parity with Python/TS). With a tool_calls
        // response followed by a content response, the loop must make TWO LLM calls,
        // feed the tool result back, and return the final content. With the old
        // default of 1 this would have stopped after the first call and returned
        // the (empty) content of the tool_calls response.
        proxy.configure(client, null, null, null, "", "ctx",
            io.mcpmesh.MeshLlmDefaults.MAX_ITERATIONS, false);

        // Iteration 1: LLM asks to call a (non-registered) tool.
        server.enqueue(stubToolCallResponse("call_1", "missing_tool", Map.of("q", "x")));
        // Iteration 2: LLM produces final content.
        server.enqueue(stubLlmResponse("final answer"));

        String result = proxy.request().user("do it").generate();
        assertEquals("final answer", result);

        // Two LLM calls were made.
        RecordedRequest first = server.takeRequest(2, TimeUnit.SECONDS);
        RecordedRequest second = server.takeRequest(2, TimeUnit.SECONDS);
        assertNotNull(first, "first LLM request must arrive");
        assertNotNull(second, "second LLM request (tool result fed back) must arrive within timeout");

        // The second request's messages must include the assistant tool_calls turn
        // and the fed-back tool result.
        JsonNode secondBody = mapper.readTree(second.getBody().readUtf8());
        JsonNode messages = secondBody.get("params").get("arguments").get("request").get("messages");
        assertNotNull(messages);
        boolean hasToolResult = false;
        for (JsonNode m : messages) {
            if ("tool".equals(m.path("role").asText())) {
                hasToolResult = true;
            }
        }
        assertTrue(hasToolResult,
            "second LLM call must include the fed-back tool result message");
    }
}
