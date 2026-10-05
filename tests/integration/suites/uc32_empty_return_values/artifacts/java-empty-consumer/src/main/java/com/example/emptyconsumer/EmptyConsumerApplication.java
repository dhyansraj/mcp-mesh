package com.example.emptyconsumer;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Probes empty/null round-trips through injected mesh proxies (issue #1250).
 *
 * <p>Contract under test: a tool's return value must round-trip through the
 * injected proxy unchanged - {@code [] -> []}, {@code {} -> {}},
 * {@code "" -> ""}, {@code null -> null}. Emptiness and absence are
 * different values.
 *
 * <p>Two probes cover the two Java consumer paths from the issue:
 * <ul>
 *   <li>{@code probeRoundtrip} - untyped {@code McpMeshTool<Object>} proxy
 *       (previously leaked the raw MCP envelope on empty content)</li>
 *   <li>{@code probeTypedEmptyList} - typed
 *       {@code McpMeshTool<List<Object>>} (previously threw Jackson
 *       {@code MismatchedInputException} on empty content)</li>
 * </ul>
 *
 * <p>Two more probes cover issue #1630 (a provider returning several text
 * content blocks): {@code probeMultiText} (untyped - must receive every
 * block, in order) and {@code probeMultiTextAsString} (typed String - must
 * fail clearly instead of truncating to the first block).
 *
 * <p>Each probe reports EXACTLY what arrived: {@code valueJson} is compact
 * Jackson JSON of the received value, so a collapsed or misparsed value is
 * surfaced by the test assertions, never accommodated.
 */
@SpringBootApplication
@MeshAgent(
    name = "java-empty-consumer",
    version = "1.0.0",
    description = "Probes empty/null round-trips via injected dependencies (issue #1250)",
    port = 9052
)
public class EmptyConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(EmptyConsumerApplication.class);
    private static final ObjectMapper MAPPER = JsonMapper.builder().build();

    public static void main(String[] args) {
        SpringApplication.run(EmptyConsumerApplication.class, args);
    }

    /** Exactly what the consumer received from the injected proxy. */
    public record ProbeResult(String kind, boolean isNull, String valueType, String valueJson) {}

    /**
     * Round-trip the boundary value for {@code kind} through an untyped proxy.
     *
     * @param kind One of: empty_list, empty_dict, empty_string, null_value, nonempty_list
     * @param source Injected empty_value_source tool (untyped)
     * @return Report of exactly what arrived
     */
    @MeshTool(
        capability = "empty_probe",
        description = "Call empty_value_source(kind) and report exactly what came back (untyped proxy)",
        tags = {"empty", "roundtrip", "java"},
        dependencies = @Selector(capability = "empty_value_source")
    )
    public ProbeResult probeRoundtrip(
        @Param(value = "kind",
               description = "One of: empty_list, empty_dict, empty_string, null_value, nonempty_list")
        String kind,
        McpMeshTool<Object> source
    ) {
        Object value = source.call("kind", kind);
        log.info("probe_roundtrip kind={} received: {}", kind, value);
        return new ProbeResult(kind, value == null, typeName(value), toJson(value));
    }

    /**
     * Round-trip an empty list through a typed {@code List<Object>} proxy.
     *
     * @param source Injected empty_value_source tool, typed as List
     * @return Report of exactly what arrived
     */
    @MeshTool(
        capability = "empty_probe_typed",
        description = "Call empty_value_source for an empty list through a typed List proxy",
        tags = {"empty", "roundtrip", "java", "typed"},
        dependencies = @Selector(capability = "empty_value_source")
    )
    public ProbeResult probeTypedEmptyList(
        McpMeshTool<List<Object>> source
    ) {
        List<Object> value = source.call("kind", "empty_list");
        log.info("probe_typed_empty_list received: {}", value);
        return new ProbeResult("typed_empty_list", value == null, typeName(value), toJson(value));
    }

    /**
     * What a consumer received from a provider returning several text
     * content blocks (issue #1630).
     *
     * @param valueType  Java type of the received value (list, string, ...)
     * @param blockCount number of received items when a List arrived, else -1
     * @param texts      the {@code text} of each received block, in order
     * @param valueJson  compact Jackson JSON of the received value
     * @param error      exception message chain if the call threw, else null
     */
    public record MultiTextResult(String valueType, int blockCount, List<String> texts,
                                  String valueJson, String error) {}

    /**
     * Call multi_text_source through an untyped proxy and report every block
     * that arrived. Before #1630 only the first block ("alpha") survived.
     *
     * @param source Injected multi_text_source tool (untyped)
     * @return Report of exactly what arrived
     */
    @MeshTool(
        capability = "multi_text_probe",
        description = "Call multi_text_source and report every text block received (untyped proxy)",
        tags = {"multi-text", "roundtrip", "java"},
        dependencies = @Selector(capability = "multi_text_source")
    )
    public MultiTextResult probeMultiText(
        McpMeshTool<Object> source
    ) {
        Object value = source.call();
        log.info("probe_multi_text received: {}", value);
        List<String> texts = new ArrayList<>();
        int blockCount = -1;
        if (value instanceof List<?> items) {
            blockCount = items.size();
            for (Object item : items) {
                if (item instanceof Map<?, ?> block) {
                    texts.add(String.valueOf(block.get("text")));
                } else {
                    texts.add(String.valueOf(item));
                }
            }
        }
        return new MultiTextResult(typeName(value), blockCount, texts, toJson(value), null);
    }

    /**
     * Call multi_text_source through a {@code McpMeshTool<String>} proxy. A
     * String cannot hold several blocks, so the call must fail clearly
     * rather than silently return only the first block.
     *
     * @param source Injected multi_text_source tool, typed as String
     * @return Report of the value (if any) and the error message chain
     */
    @MeshTool(
        capability = "multi_text_probe_string",
        description = "Call multi_text_source through a typed String proxy and report the outcome",
        tags = {"multi-text", "roundtrip", "java", "typed"},
        dependencies = @Selector(capability = "multi_text_source")
    )
    public MultiTextResult probeMultiTextAsString(
        McpMeshTool<String> source
    ) {
        try {
            String value = source.call();
            log.info("probe_multi_text_as_string received: {}", value);
            return new MultiTextResult(typeName(value), -1, List.of(), toJson(value), null);
        } catch (RuntimeException e) {
            log.info("probe_multi_text_as_string failed: {}", e.toString());
            StringBuilder chain = new StringBuilder();
            for (Throwable t = e; t != null; t = t.getCause()) {
                if (chain.length() > 0) chain.append(" <- ");
                chain.append(t.getClass().getSimpleName()).append(": ").append(t.getMessage());
                if (t.getCause() == t) break;
            }
            return new MultiTextResult("error", -1, List.of(), null, chain.toString());
        }
    }

    private static String typeName(Object value) {
        if (value == null) return "null";
        if (value instanceof List) return "list";
        if (value instanceof Map) return "map";
        if (value instanceof String) return "string";
        return value.getClass().getSimpleName();
    }

    private static String toJson(Object value) {
        // Jackson 3 (tools.jackson) throws unchecked JacksonException
        return MAPPER.writeValueAsString(value);
    }
}
