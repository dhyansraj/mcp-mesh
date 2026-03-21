package io.mcpmesh.spring.media;

import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.util.*;

@DisplayName("MediaResolver")
class MediaResolverTest {

    private static final byte[] PNG_BYTES = new byte[]{(byte) 0x89, 0x50, 0x4E, 0x47};
    private static final String PNG_B64 = Base64.getEncoder().encodeToString(PNG_BYTES);

    /**
     * Simple in-memory MediaStore for testing.
     */
    private static class TestMediaStore implements MediaStore {
        private final Map<String, MediaFetchResult> store = new HashMap<>();
        private boolean failOnFetch = false;

        void put(String uri, byte[] data, String mimeType) {
            store.put(uri, new MediaFetchResult(data, mimeType));
        }

        void setFailOnFetch(boolean fail) {
            this.failOnFetch = fail;
        }

        @Override
        public String upload(byte[] data, String filename, String mimeType) {
            String uri = "media://" + filename;
            store.put(uri, new MediaFetchResult(data, mimeType));
            return uri;
        }

        @Override
        public MediaFetchResult fetch(String uri) {
            if (failOnFetch) {
                throw new MediaStoreException("Simulated fetch failure for " + uri);
            }
            MediaFetchResult result = store.get(uri);
            if (result == null) {
                throw new MediaStoreException("Not found: " + uri);
            }
            return result;
        }

        @Override
        public boolean exists(String uri) {
            return store.containsKey(uri);
        }
    }

    private TestMediaStore mediaStore;

    @BeforeEach
    void setUp() {
        mediaStore = new TestMediaStore();
        mediaStore.put("media://photo.png", PNG_BYTES, "image/png");
        mediaStore.put("media://doc.pdf", "pdf-content".getBytes(), "application/pdf");
    }

    @Nested
    @DisplayName("resolveResourceLinks with Claude vendor")
    class ClaudeTests {

        @Test
        @DisplayName("resolves image resource_link to base64 image block")
        void testResolveImageResourceLinkClaude() {
            Map<String, Object> resourceLink = new LinkedHashMap<>();
            resourceLink.put("type", "resource_link");
            resourceLink.put("uri", "media://photo.png");
            resourceLink.put("mimeType", "image/png");
            resourceLink.put("name", "photo.png");

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                resourceLink, "claude", mediaStore);

            assertNotNull(result);
            assertFalse(result.isEmpty());

            // First item should be the image block
            Map<String, Object> imageBlock = result.get(0);
            assertEquals("image", imageBlock.get("type"));

            @SuppressWarnings("unchecked")
            Map<String, Object> source = (Map<String, Object>) imageBlock.get("source");
            assertEquals("base64", source.get("type"));
            assertEquals("image/png", source.get("media_type"));
            assertEquals(PNG_B64, source.get("data"));
        }

        @Test
        @DisplayName("anthropic vendor alias works same as claude")
        void testAnthropicAlias() {
            Map<String, Object> resourceLink = Map.of(
                "type", "resource_link",
                "uri", "media://photo.png",
                "mimeType", "image/png"
            );

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                resourceLink, "anthropic", mediaStore);

            assertNotNull(result);
            Map<String, Object> imageBlock = result.get(0);
            assertEquals("image", imageBlock.get("type"));
        }
    }

    @Nested
    @DisplayName("resolveResourceLinks with OpenAI vendor")
    class OpenAiTests {

        @Test
        @DisplayName("resolves image resource_link to data URL format")
        void testResolveImageResourceLinkOpenai() {
            Map<String, Object> resourceLink = Map.of(
                "type", "resource_link",
                "uri", "media://photo.png",
                "mimeType", "image/png",
                "name", "photo.png"
            );

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                resourceLink, "openai", mediaStore);

            assertNotNull(result);
            assertFalse(result.isEmpty());

            Map<String, Object> imageBlock = result.get(0);
            assertEquals("image_url", imageBlock.get("type"));

            @SuppressWarnings("unchecked")
            Map<String, Object> imageUrl = (Map<String, Object>) imageBlock.get("image_url");
            String url = (String) imageUrl.get("url");
            assertTrue(url.startsWith("data:image/png;base64,"));
            assertTrue(url.contains(PNG_B64));
            assertEquals("high", imageUrl.get("detail"));
        }

        @Test
        @DisplayName("gpt vendor alias works same as openai")
        void testGptAlias() {
            Map<String, Object> resourceLink = Map.of(
                "type", "resource_link",
                "uri", "media://photo.png",
                "mimeType", "image/png"
            );

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                resourceLink, "gpt", mediaStore);

            assertNotNull(result);
            Map<String, Object> imageBlock = result.get(0);
            assertEquals("image_url", imageBlock.get("type"));
        }
    }

    @Nested
    @DisplayName("non-image and passthrough")
    class NonImageTests {

        @Test
        @DisplayName("non-image resource_link becomes text description")
        void testResolveNonImagePassthrough() {
            Map<String, Object> resourceLink = new LinkedHashMap<>();
            resourceLink.put("type", "resource_link");
            resourceLink.put("uri", "media://doc.pdf");
            resourceLink.put("mimeType", "application/pdf");
            resourceLink.put("name", "report.pdf");

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                resourceLink, "claude", mediaStore);

            assertNotNull(result);
            assertEquals(1, result.size());
            assertEquals("text", result.get(0).get("type"));
            String text = (String) result.get(0).get("text");
            assertTrue(text.contains("report.pdf"));
            assertTrue(text.contains("application/pdf"));
        }

        @Test
        @DisplayName("plain string returns null (no resolution needed)")
        void testResolvePlainString() {
            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                "Hello, world!", "claude", mediaStore);

            assertNull(result);
        }

        @Test
        @DisplayName("null toolResult returns null")
        void testResolveNull() {
            assertNull(MediaResolver.resolveResourceLinks(null, "claude", mediaStore));
        }

        @Test
        @DisplayName("null mediaStore returns null")
        void testResolveNullMediaStore() {
            Map<String, Object> resourceLink = Map.of(
                "type", "resource_link",
                "uri", "media://photo.png",
                "mimeType", "image/png"
            );
            assertNull(MediaResolver.resolveResourceLinks(resourceLink, "claude", null));
        }
    }

    @Nested
    @DisplayName("mixed content lists")
    class MixedContentTests {

        @Test
        @DisplayName("resolves mixed text + resource_link list")
        void testResolveMixedContent() {
            List<Map<String, Object>> mixedContent = new ArrayList<>();
            mixedContent.add(Map.of("type", "text", "text", "Here is the chart:"));
            mixedContent.add(Map.of(
                "type", "resource_link",
                "uri", "media://photo.png",
                "mimeType", "image/png",
                "name", "chart.png"
            ));

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                mixedContent, "claude", mediaStore);

            assertNotNull(result);
            // Should have: text block + image block + image label text
            assertTrue(result.size() >= 2);

            // First should be the text item
            assertEquals("text", result.get(0).get("type"));
            assertEquals("Here is the chart:", result.get(0).get("text"));

            // Second should be the image
            assertEquals("image", result.get(1).get("type"));
        }

        @Test
        @DisplayName("list without resource_links returns null")
        void testResolveTextOnlyList() {
            List<Map<String, Object>> textOnly = List.of(
                Map.of("type", "text", "text", "Just text")
            );

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                textOnly, "claude", mediaStore);

            assertNull(result);
        }
    }

    @Nested
    @DisplayName("error handling")
    class ErrorHandlingTests {

        @Test
        @DisplayName("fetch failure produces graceful text fallback")
        void testResolveFetchFailure() {
            mediaStore.setFailOnFetch(true);

            Map<String, Object> resourceLink = new LinkedHashMap<>();
            resourceLink.put("type", "resource_link");
            resourceLink.put("uri", "media://photo.png");
            resourceLink.put("mimeType", "image/png");
            resourceLink.put("name", "photo.png");

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                resourceLink, "claude", mediaStore);

            assertNotNull(result);
            assertEquals(1, result.size());
            assertEquals("text", result.get(0).get("type"));
            String text = (String) result.get(0).get("text");
            assertTrue(text.contains("unavailable"));
            assertTrue(text.contains("photo.png"));
        }

        @Test
        @DisplayName("resource_link missing uri produces text fallback")
        void testResolveMissingUri() {
            Map<String, Object> resourceLink = new LinkedHashMap<>();
            resourceLink.put("type", "resource_link");
            resourceLink.put("mimeType", "image/png");
            resourceLink.put("name", "photo.png");

            List<Map<String, Object>> result = MediaResolver.resolveResourceLinks(
                resourceLink, "claude", mediaStore);

            assertNotNull(result);
            assertEquals(1, result.size());
            assertEquals("text", result.get(0).get("type"));
            String text = (String) result.get(0).get("text");
            assertTrue(text.contains("missing URI"));
        }
    }

    @Nested
    @DisplayName("vendor format helpers")
    class FormatTests {

        @Test
        @DisplayName("formatForClaude produces correct structure")
        void testFormatForClaude() {
            Map<String, Object> block = MediaResolver.formatForClaude("abc123", "image/jpeg");
            assertEquals("image", block.get("type"));

            @SuppressWarnings("unchecked")
            Map<String, Object> source = (Map<String, Object>) block.get("source");
            assertEquals("base64", source.get("type"));
            assertEquals("image/jpeg", source.get("media_type"));
            assertEquals("abc123", source.get("data"));
        }

        @Test
        @DisplayName("formatForOpenai produces correct data URL")
        void testFormatForOpenai() {
            Map<String, Object> block = MediaResolver.formatForOpenai("abc123", "image/jpeg");
            assertEquals("image_url", block.get("type"));

            @SuppressWarnings("unchecked")
            Map<String, Object> imageUrl = (Map<String, Object>) block.get("image_url");
            assertEquals("data:image/jpeg;base64,abc123", imageUrl.get("url"));
            assertEquals("high", imageUrl.get("detail"));
        }
    }

    @Nested
    @DisplayName("serializeForToolResult")
    class SerializationTests {

        @Test
        @DisplayName("serializes resolved content to JSON string")
        void testSerialize() {
            List<Map<String, Object>> content = List.of(
                Map.of("type", "text", "text", "Hello")
            );

            String json = MediaResolver.serializeForToolResult(content);
            assertNotNull(json);
            assertTrue(json.contains("\"type\""));
            assertTrue(json.contains("\"text\""));
            assertTrue(json.contains("Hello"));
        }

        @Test
        @DisplayName("null input returns empty string")
        void testSerializeNull() {
            assertEquals("", MediaResolver.serializeForToolResult(null));
        }

        @Test
        @DisplayName("empty list returns empty string")
        void testSerializeEmpty() {
            assertEquals("", MediaResolver.serializeForToolResult(List.of()));
        }
    }
}
