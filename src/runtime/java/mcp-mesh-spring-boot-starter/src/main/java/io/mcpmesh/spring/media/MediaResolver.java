package io.mcpmesh.spring.media;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.ObjectMapper;

import java.util.*;

/**
 * Resolves resource_link URIs in tool results to provider-native multimodal content.
 *
 * <p>When an LLM provider executes a tool that returns a {@code resource_link}
 * (e.g., an image URI from MediaStore), this resolver fetches the media and
 * converts it into provider-specific content blocks that the LLM can "see".
 *
 * <p>Supported vendors:
 * <ul>
 *   <li><b>claude</b> (Anthropic) — {@code {"type": "image", "source": {"type": "base64", ...}}}</li>
 *   <li><b>openai</b> — {@code {"type": "image_url", "image_url": {"url": "data:...;base64,...", "detail": "high"}}}</li>
 *   <li><b>gemini</b> — {@code {"type": "image", "source": {"type": "base64", ...}}} (same as Claude)</li>
 * </ul>
 *
 * <p>Only image MIME types are resolved to inline media. Non-image resource_links
 * are converted to text descriptions.
 */
public class MediaResolver {

    private static final Logger log = LoggerFactory.getLogger(MediaResolver.class);

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static final Set<String> IMAGE_MIME_TYPES = Set.of(
        "image/png", "image/jpeg", "image/gif", "image/webp"
    );

    private MediaResolver() {
        // Utility class
    }

    /**
     * Resolve resource_links in a tool result to provider-native content blocks.
     *
     * <p>Handles three result shapes:
     * <ol>
     *   <li>{@code List<Map>} — mixed content from McpHttpClient (text + resource_link items)</li>
     *   <li>{@code Map} with {@code "type": "resource_link"} — single resource_link</li>
     *   <li>{@code String} — plain text or JSON string</li>
     * </ol>
     *
     * @param toolResult The raw tool result (String, Map, List)
     * @param vendor     Provider name: "anthropic", "claude", "openai", "gpt", "gemini", "google"
     * @param mediaStore The MediaStore to fetch media from (may be null)
     * @return List of content parts for the LLM message, or null if no resolution needed
     */
    @SuppressWarnings("unchecked")
    public static List<Map<String, Object>> resolveResourceLinks(
            Object toolResult, String vendor, MediaStore mediaStore) {

        if (toolResult == null || mediaStore == null) {
            return null;
        }

        String normalizedVendor = normalizeVendor(vendor);

        if (toolResult instanceof List<?> listResult) {
            return resolveList(listResult, normalizedVendor, mediaStore);
        }

        if (toolResult instanceof Map<?, ?> mapResult) {
            Map<String, Object> map = (Map<String, Object>) mapResult;
            if ("resource_link".equals(map.get("type"))) {
                return resolveResourceLinkItem(map, normalizedVendor, mediaStore);
            }
            return null;
        }

        if (toolResult instanceof String strResult) {
            return resolveString(strResult, normalizedVendor, mediaStore);
        }

        return null;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> resolveList(
            List<?> listResult, String vendor, MediaStore mediaStore) {

        boolean hasResourceLink = false;
        for (Object item : listResult) {
            if (item instanceof Map<?, ?> map && "resource_link".equals(map.get("type"))) {
                hasResourceLink = true;
                break;
            }
        }

        if (!hasResourceLink) {
            return null;
        }

        List<Map<String, Object>> resolved = new ArrayList<>();
        for (Object item : listResult) {
            if (item instanceof Map<?, ?> rawMap) {
                Map<String, Object> map = (Map<String, Object>) rawMap;
                String type = (String) map.get("type");

                if ("resource_link".equals(type)) {
                    List<Map<String, Object>> parts = resolveResourceLinkItem(map, vendor, mediaStore);
                    resolved.addAll(parts);
                } else if ("text".equals(type)) {
                    resolved.add(Map.of("type", "text", "text", map.getOrDefault("text", "")));
                } else {
                    // Unknown type, keep as text representation
                    resolved.add(Map.of("type", "text", "text", map.toString()));
                }
            } else if (item instanceof String str) {
                resolved.add(Map.of("type", "text", "text", str));
            }
        }

        return resolved;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> resolveResourceLinkItem(
            Map<String, Object> resourceLink, String vendor, MediaStore mediaStore) {

        String uri = (String) resourceLink.get("uri");
        String mimeType = (String) resourceLink.get("mimeType");
        String name = (String) resourceLink.get("name");

        if (uri == null) {
            log.warn("resource_link missing uri field");
            return List.of(Map.of("type", "text",
                "text", "[Resource: " + (name != null ? name : "unknown") + " (missing URI)]"));
        }

        // Only resolve image MIME types
        if (mimeType == null || !IMAGE_MIME_TYPES.contains(mimeType.toLowerCase())) {
            log.debug("Skipping non-image resource_link: uri={}, mimeType={}", uri, mimeType);
            String desc = name != null ? name : uri;
            String typeInfo = mimeType != null ? " (" + mimeType + ")" : "";
            return List.of(Map.of("type", "text",
                "text", "[Resource: " + desc + typeInfo + "]"));
        }

        try {
            MediaFetchResult fetchResult = mediaStore.fetch(uri);
            String base64Data = Base64.getEncoder().encodeToString(fetchResult.data());
            String resolvedMimeType = fetchResult.mimeType() != null ? fetchResult.mimeType() : mimeType;

            log.debug("Resolved resource_link: uri={}, mimeType={}, size={}",
                uri, resolvedMimeType, fetchResult.data().length);

            Map<String, Object> imageBlock = formatForVendor(base64Data, resolvedMimeType, vendor);
            List<Map<String, Object>> result = new ArrayList<>();
            result.add(imageBlock);

            // Add a text label if a name is available
            if (name != null && !name.isEmpty()) {
                result.add(Map.of("type", "text", "text", "[Image: " + name + "]"));
            }

            return result;
        } catch (Exception e) {
            log.warn("Failed to fetch resource_link: uri={}, error={}", uri, e.getMessage());
            String desc = name != null ? name : uri;
            return List.of(Map.of("type", "text",
                "text", "[Image unavailable: " + desc + " - " + e.getMessage() + "]"));
        }
    }

    private static List<Map<String, Object>> resolveString(
            String strResult, String vendor, MediaStore mediaStore) {
        // Only attempt JSON parsing for strings that look like resource_links
        if (!strResult.contains("resource_link")) {
            return null;
        }

        try {
            // Try parsing as a JSON object
            @SuppressWarnings("unchecked")
            Map<String, Object> parsed = MAPPER.readValue(strResult, Map.class);
            if ("resource_link".equals(parsed.get("type"))) {
                return resolveResourceLinkItem(parsed, vendor, mediaStore);
            }
        } catch (Exception ignored) {
            // Not valid JSON or not a resource_link — fall through
        }

        try {
            // Try parsing as a JSON array
            @SuppressWarnings("unchecked")
            List<Object> parsed = MAPPER.readValue(strResult, List.class);
            return resolveList(parsed, vendor, mediaStore);
        } catch (Exception ignored) {
            // Not a JSON array — no resolution needed
        }

        return null;
    }

    // =========================================================================
    // Vendor-specific formatters
    // =========================================================================

    static Map<String, Object> formatForVendor(String base64Data, String mimeType, String vendor) {
        return switch (vendor) {
            case "openai" -> formatForOpenai(base64Data, mimeType);
            default -> formatForClaude(base64Data, mimeType); // Claude + Gemini use same format
        };
    }

    static Map<String, Object> formatForClaude(String base64Data, String mimeType) {
        return Map.of(
            "type", "image",
            "source", Map.of(
                "type", "base64",
                "media_type", mimeType,
                "data", base64Data
            )
        );
    }

    static Map<String, Object> formatForOpenai(String base64Data, String mimeType) {
        return Map.of(
            "type", "image_url",
            "image_url", Map.of(
                "url", "data:" + mimeType + ";base64," + base64Data,
                "detail", "high"
            )
        );
    }

    // =========================================================================
    // Serialization helpers
    // =========================================================================

    /**
     * Serialize resolved content blocks to a JSON string suitable for tool result.
     *
     * <p>Since {@code ToolExecutorCallback.execute()} returns {@code String},
     * the resolved multimodal content must be serialized. The LLM will see
     * the base64 image data inline in the tool result text.
     *
     * @param resolvedContent The resolved content blocks
     * @return JSON string representation of the content
     */
    public static String serializeForToolResult(List<Map<String, Object>> resolvedContent) {
        if (resolvedContent == null || resolvedContent.isEmpty()) {
            return "";
        }

        try {
            return MAPPER.writeValueAsString(resolvedContent);
        } catch (Exception e) {
            log.warn("Failed to serialize resolved content: {}", e.getMessage());
            // Fallback: extract text parts only
            StringBuilder sb = new StringBuilder();
            for (Map<String, Object> part : resolvedContent) {
                if ("text".equals(part.get("type"))) {
                    if (sb.length() > 0) sb.append("\n");
                    sb.append(part.get("text"));
                }
            }
            return sb.toString();
        }
    }

    private static String normalizeVendor(String vendor) {
        if (vendor == null) return "claude";
        return switch (vendor.toLowerCase()) {
            case "anthropic", "claude" -> "claude";
            case "openai", "gpt" -> "openai";
            case "gemini", "google" -> "gemini";
            default -> vendor.toLowerCase();
        };
    }
}
