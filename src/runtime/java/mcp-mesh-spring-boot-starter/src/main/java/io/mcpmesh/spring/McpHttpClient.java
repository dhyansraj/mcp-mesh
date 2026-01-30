package io.mcpmesh.spring;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.types.MeshToolCallException;
import okhttp3.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 * HTTP client for calling remote MCP servers.
 *
 * <p>Implements the MCP JSON-RPC protocol for tool invocation.
 */
public class McpHttpClient {

    private static final Logger log = LoggerFactory.getLogger(McpHttpClient.class);
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");

    private final OkHttpClient httpClient;
    private final ObjectMapper objectMapper;

    public McpHttpClient() {
        this.httpClient = new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .build();
        this.objectMapper = new ObjectMapper();
    }

    /**
     * Call a tool on a remote MCP server.
     *
     * @param endpoint     The MCP server endpoint (e.g., http://localhost:9000)
     * @param functionName The tool/function name to call
     * @param params       Parameters to pass to the tool
     * @param <T>          Expected return type
     * @return The tool result
     * @throws MeshToolCallException if the call fails
     */
    @SuppressWarnings("unchecked")
    public <T> T callTool(String endpoint, String functionName, Map<String, Object> params) {
        try {
            // Build MCP tools/call request
            // Use /mcp endpoint (stateless transport) - not /mcp/v1
            String url = endpoint.endsWith("/") ? endpoint + "mcp" : endpoint + "/mcp";

            Map<String, Object> request = Map.of(
                "jsonrpc", "2.0",
                "id", System.currentTimeMillis(),
                "method", "tools/call",
                "params", Map.of(
                    "name", functionName,
                    "arguments", params
                )
            );

            String requestBody = objectMapper.writeValueAsString(request);
            log.debug("Calling tool {} at {}: {}", functionName, url, requestBody);

            Request httpRequest = new Request.Builder()
                .url(url)
                .post(RequestBody.create(requestBody, JSON))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json, text/event-stream")
                .build();

            try (Response response = httpClient.newCall(httpRequest).execute()) {
                if (!response.isSuccessful()) {
                    throw new MeshToolCallException(functionName, functionName,
                        "HTTP " + response.code() + ": " + response.message());
                }

                ResponseBody body = response.body();
                if (body == null) {
                    throw new MeshToolCallException(functionName, functionName, "Empty response body");
                }

                String responseBody = body.string();
                log.debug("Tool response: {}", responseBody);

                // Handle SSE (Server-Sent Events) format from MCP servers
                // SSE format: "event: message\nid: ...\ndata: {JSON}\n\n"
                String jsonContent = responseBody;
                if (responseBody.startsWith("event:") || responseBody.contains("\ndata: ")) {
                    jsonContent = extractJsonFromSse(responseBody);
                    log.debug("Extracted JSON from SSE: {}", jsonContent);
                }

                // Parse JSON-RPC response
                JsonNode responseNode = objectMapper.readTree(jsonContent);

                if (responseNode.has("error")) {
                    JsonNode error = responseNode.get("error");
                    String errorMessage = error.has("message") ?
                        error.get("message").asText() : "Unknown error";
                    throw new MeshToolCallException(functionName, functionName, errorMessage);
                }

                if (responseNode.has("result")) {
                    JsonNode result = responseNode.get("result");

                    // Handle MCP content array response
                    if (result.has("content") && result.get("content").isArray()) {
                        JsonNode content = result.get("content");
                        if (content.size() > 0) {
                            JsonNode firstContent = content.get(0);
                            if (firstContent.has("text")) {
                                String text = firstContent.get("text").asText();
                                // Try to parse as JSON, otherwise return as string
                                try {
                                    return (T) objectMapper.readValue(text,
                                        new TypeReference<Map<String, Object>>() {});
                                } catch (Exception e) {
                                    return (T) text;
                                }
                            }
                        }
                    }

                    // Return result directly
                    return objectMapper.treeToValue(result, (Class<T>) Object.class);
                }

                return null;
            }
        } catch (MeshToolCallException e) {
            throw e;
        } catch (IOException e) {
            throw new MeshToolCallException(functionName, functionName, e);
        } catch (Exception e) {
            throw new MeshToolCallException(functionName, functionName, e);
        }
    }

    /**
     * Call a tool asynchronously.
     */
    public <T> CompletableFuture<T> callToolAsync(String endpoint, String functionName,
                                                   Map<String, Object> params) {
        return CompletableFuture.supplyAsync(() -> callTool(endpoint, functionName, params));
    }

    /**
     * List available tools on a remote MCP server.
     */
    public JsonNode listTools(String endpoint) {
        try {
            // Use /mcp endpoint (stateless transport)
            String url = endpoint.endsWith("/") ? endpoint + "mcp" : endpoint + "/mcp";

            Map<String, Object> request = Map.of(
                "jsonrpc", "2.0",
                "id", System.currentTimeMillis(),
                "method", "tools/list",
                "params", Map.of()
            );

            String requestBody = objectMapper.writeValueAsString(request);

            Request httpRequest = new Request.Builder()
                .url(url)
                .post(RequestBody.create(requestBody, JSON))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json, text/event-stream")
                .build();

            try (Response response = httpClient.newCall(httpRequest).execute()) {
                if (!response.isSuccessful()) {
                    log.warn("Failed to list tools at {}: HTTP {}", endpoint, response.code());
                    return null;
                }

                ResponseBody body = response.body();
                if (body == null) {
                    return null;
                }

                JsonNode responseNode = objectMapper.readTree(body.string());
                return responseNode.has("result") ? responseNode.get("result") : null;
            }
        } catch (Exception e) {
            log.warn("Failed to list tools at {}: {}", endpoint, e.getMessage());
            return null;
        }
    }

    /**
     * Extract JSON content from SSE (Server-Sent Events) format.
     *
     * <p>SSE format looks like:
     * <pre>
     * event: message
     * id: some-id
     * data: {"jsonrpc":"2.0","id":1,"result":{...}}
     * </pre>
     *
     * @param sseContent The SSE-formatted response
     * @return The extracted JSON content from the data: line
     */
    private String extractJsonFromSse(String sseContent) {
        // Find all data: lines and concatenate them (for multi-line data)
        StringBuilder jsonBuilder = new StringBuilder();
        for (String line : sseContent.split("\n")) {
            if (line.startsWith("data: ")) {
                jsonBuilder.append(line.substring(6)); // Remove "data: " prefix
            } else if (line.startsWith("data:")) {
                jsonBuilder.append(line.substring(5)); // Handle "data:" without space
            }
        }
        String json = jsonBuilder.toString().trim();
        return json.isEmpty() ? sseContent : json;
    }

    /**
     * Close the HTTP client and release resources.
     */
    public void close() {
        httpClient.dispatcher().executorService().shutdown();
        httpClient.connectionPool().evictAll();
    }
}
