package com.example.mediaconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.List;
import java.util.Map;

/**
 * MCP Mesh media consumer agent.
 *
 * <p>Demonstrates consuming {@code resource_link} content produced by the
 * media-producer agent. Depends on the producer's capabilities
 * ({@code report_generator}, {@code chart_generator}) and describes the
 * received resource links.
 *
 * <h2>Tools</h2>
 * <ul>
 *   <li>{@code summarize_report} — calls report_generator and describes the resource_link</li>
 *   <li>{@code describe_media} — calls chart_generator and describes the resource_link</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * meshctl start --registry-only
 *
 * # Start the producer first
 * cd examples/java/media-producer-agent
 * mvn spring-boot:run
 *
 * # Then start this consumer
 * cd examples/java/media-consumer-agent
 * mvn spring-boot:run
 *
 * meshctl call summarize_report '{"topic": "AI"}'
 * meshctl call describe_media '{"data": "Q1:30,Q2:45"}'
 * </pre>
 */
@MeshAgent(
    name = "media-consumer",
    version = "1.0.0",
    description = "Agent that consumes resource_links from the media-producer",
    port = 9221
)
@SpringBootApplication
public class MediaConsumerAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(MediaConsumerAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Media Consumer Agent...");
        SpringApplication.run(MediaConsumerAgentApplication.class, args);
    }

    /**
     * Request a report from the media-producer and describe the received resource_link.
     *
     * @param topic The topic for the report
     * @param reportGenerator Injected mesh proxy for report_generator capability
     * @return Description of the received resource_link
     */
    @MeshTool(
        capability = "report_summarizer",
        description = "Requests a report from the producer and describes the received resource_link",
        tags = {"media", "consumer", "report", "java"},
        dependencies = @Selector(capability = "report_generator")
    )
    @SuppressWarnings("unchecked")
    public String summarizeReport(
        @Param(value = "topic", description = "The topic for the report") String topic,
        McpMeshTool<Object> reportGenerator
    ) {
        if (topic == null || topic.isBlank()) {
            topic = "AI";
        }
        log.info("Requesting report on: {} from media-producer", topic);

        if (reportGenerator == null || !reportGenerator.isAvailable()) {
            return "Error: report_generator dependency not available";
        }

        Object result = reportGenerator.call("topic", topic);
        log.info("Received result from report_generator: {}", result);

        return describeResult(result, "media-producer");
    }

    /**
     * Request a chart from the media-producer and describe the received resource_link.
     *
     * @param data Comma-separated Label:Value pairs for the chart
     * @param chartGenerator Injected mesh proxy for chart_generator capability
     * @return Description of the received resource_link
     */
    @MeshTool(
        capability = "media_describer",
        description = "Requests a chart from the producer and describes the received media",
        tags = {"media", "consumer", "chart", "java"},
        dependencies = @Selector(capability = "chart_generator")
    )
    @SuppressWarnings("unchecked")
    public String describeMedia(
        @Param(value = "data", description = "Comma-separated Label:Value pairs") String data,
        McpMeshTool<Object> chartGenerator
    ) {
        if (data == null || data.isBlank()) {
            data = "Q1:30,Q2:45,Q3:60,Q4:50";
        }
        log.info("Requesting chart from media-producer with data: {}", data);

        if (chartGenerator == null || !chartGenerator.isAvailable()) {
            return "Error: chart_generator dependency not available";
        }

        Object result = chartGenerator.call("data", data);
        log.info("Received result from chart_generator: {}", result);

        return describeResult(result, "media-producer");
    }

    /**
     * Process a tool call result that may be a List (mixed/resource_link content),
     * a Map (single content item), or a String (text-only content).
     *
     * <p>{@code McpHttpClient.callTool()} returns:
     * <ul>
     *   <li>{@code List<Map<String, Object>>} for mixed content (resource_link, image, etc.)</li>
     *   <li>{@code String} for text-only responses</li>
     *   <li>{@code Map<String, Object>} for JSON-deserialized text</li>
     * </ul>
     */
    @SuppressWarnings("unchecked")
    private String describeResult(Object result, String source) {
        if (result == null) {
            return "Received null result from " + source;
        }

        if (result instanceof List<?> list) {
            // Mixed content: List<Map<String, Object>> — scan for resource_link items
            StringBuilder sb = new StringBuilder();
            for (Object item : list) {
                if (item instanceof Map<?, ?> map) {
                    String formatted = formatContentItem((Map<String, Object>) map, source);
                    if (!sb.isEmpty()) {
                        sb.append("\n---\n");
                    }
                    sb.append(formatted);
                }
            }
            return sb.isEmpty() ? "Received empty content list from " + source : sb.toString();
        }

        if (result instanceof Map<?, ?> map) {
            return formatContentItem((Map<String, Object>) map, source);
        }

        if (result instanceof String text) {
            return "Received text from " + source + ": " + text;
        }

        return "Received unexpected result type (" + result.getClass().getSimpleName() + ") from " + source + ": " + result;
    }

    /**
     * Format a single MCP content item (resource_link, text, or other).
     */
    @SuppressWarnings("unchecked")
    private String formatContentItem(Map<String, Object> item, String source) {
        String type = String.valueOf(item.getOrDefault("type", "unknown"));

        if ("resource_link".equals(type)) {
            String uri = String.valueOf(item.getOrDefault("uri", "unknown"));
            String name = String.valueOf(item.getOrDefault("name", "unknown"));
            String mime = String.valueOf(item.getOrDefault("mimeType", "unknown"));
            String desc = String.valueOf(item.getOrDefault("description", ""));
            Object size = item.get("size");
            String sizeInfo = size != null ? ", size=" + size + " bytes" : "";

            return String.format(
                "Received resource_link from %s:\n" +
                "  Name: %s\n" +
                "  URI:  %s\n" +
                "  Type: %s\n" +
                "  Description: %s%s",
                source, name, uri, mime, desc, sizeInfo);
        }

        if ("text".equals(type)) {
            String text = String.valueOf(item.getOrDefault("text", ""));
            return "Received text from " + source + ": " + text;
        }

        return "Received " + type + " content from " + source + ": " + item;
    }
}
