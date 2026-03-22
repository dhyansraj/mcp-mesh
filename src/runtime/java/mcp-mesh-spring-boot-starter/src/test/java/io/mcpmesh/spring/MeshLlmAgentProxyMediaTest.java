package io.mcpmesh.spring;

import io.mcpmesh.spring.media.MediaFetchResult;
import io.mcpmesh.spring.media.MediaStore;
import io.mcpmesh.spring.media.MediaStoreException;
import io.mcpmesh.types.MeshLlmAgent;
import org.junit.jupiter.api.*;

import java.lang.reflect.Method;
import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for media support in MeshLlmAgentProxy's GenerateBuilder.
 *
 * <p>Verifies that media URIs are resolved via MediaStore and attached
 * as multipart content to the last user message.
 */
@DisplayName("MeshLlmAgentProxy media support")
class MeshLlmAgentProxyMediaTest {

    private static final byte[] PNG_BYTES = new byte[]{(byte) 0x89, 0x50, 0x4E, 0x47};
    private static final byte[] JPEG_BYTES = new byte[]{(byte) 0xFF, (byte) 0xD8, (byte) 0xFF};
    private static final String PNG_B64 = Base64.getEncoder().encodeToString(PNG_BYTES);
    private static final String JPEG_B64 = Base64.getEncoder().encodeToString(JPEG_BYTES);

    private static class TestMediaStore implements MediaStore {
        private final Map<String, MediaFetchResult> store = new HashMap<>();
        private boolean failOnFetch = false;
        private int fetchCount = 0;

        void put(String uri, byte[] data, String mimeType) {
            store.put(uri, new MediaFetchResult(data, mimeType));
        }

        void setFailOnFetch(boolean fail) {
            this.failOnFetch = fail;
        }

        int getFetchCount() {
            return fetchCount;
        }

        @Override
        public String upload(byte[] data, String filename, String mimeType) {
            String uri = "media://" + filename;
            store.put(uri, new MediaFetchResult(data, mimeType));
            return uri;
        }

        @Override
        public MediaFetchResult fetch(String uri) {
            fetchCount++;
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
    private MeshLlmAgentProxy proxy;

    @BeforeEach
    void setUp() {
        mediaStore = new TestMediaStore();
        mediaStore.put("media://photo.png", PNG_BYTES, "image/png");
        mediaStore.put("media://banner.jpg", JPEG_BYTES, "image/jpeg");

        proxy = new MeshLlmAgentProxy("test-function");
        proxy.setMediaStore(mediaStore);
        proxy.updateProvider("http://localhost:8080", "llm_generate", "openai");
    }

    // =========================================================================
    // Builder API surface tests
    // =========================================================================

    @Nested
    @DisplayName("GenerateBuilder media API")
    class BuilderApiTests {

        @Test
        @DisplayName("media(String...) accepts varargs")
        void mediaVarargs() {
            MeshLlmAgent.GenerateBuilder builder = proxy.request();
            assertNotNull(builder.media("media://photo.png", "media://banner.jpg"));
        }

        @Test
        @DisplayName("media(List<String>) accepts list")
        void mediaList() {
            MeshLlmAgent.GenerateBuilder builder = proxy.request();
            assertNotNull(builder.media(List.of("media://photo.png")));
        }

        @Test
        @DisplayName("media() is chainable with other builder methods")
        void mediaChaining() {
            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .system("You are a helpful assistant")
                .user("Describe this image")
                .media("media://photo.png")
                .maxTokens(1000)
                .temperature(0.5);
            assertNotNull(builder);
        }

        @Test
        @DisplayName("media(null) is safely ignored")
        void mediaNullSafe() {
            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .user("Hello")
                .media((String[]) null);
            assertNotNull(builder);
        }

        @Test
        @DisplayName("media(List null) is safely ignored")
        void mediaListNullSafe() {
            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .user("Hello")
                .media((List<String>) null);
            assertNotNull(builder);
        }
    }

    // =========================================================================
    // Message construction tests (via reflection on builder internals)
    // =========================================================================

    @Nested
    @DisplayName("multipart message construction")
    class MessageConstructionTests {

        /**
         * Use the internal attachMediaToLastUserMessage method via reflection
         * to test message construction without needing a real LLM provider.
         */
        @SuppressWarnings("unchecked")
        private List<Map<String, Object>> buildAndAttachMedia(String... uris) throws Exception {

            // Create builder via request()
            MeshLlmAgent.GenerateBuilder builder = proxy.request();
            builder.user("Describe this image");
            for (String uri : uris) {
                builder.media(uri);
            }

            // Use reflection to access the builder's private method
            // We test indirectly by checking the mediaUris field and resolveMediaUris
            Object builderObj = builder;
            Class<?> builderClass = builderObj.getClass();

            // Get the mediaUris field to verify they were set
            var mediaUrisField = builderClass.getDeclaredField("mediaUris");
            mediaUrisField.setAccessible(true);
            List<String> storedUris = (List<String>) mediaUrisField.get(builderObj);

            assertEquals(uris.length, storedUris.size());
            for (int i = 0; i < uris.length; i++) {
                assertEquals(uris[i], storedUris.get(i));
            }

            // Call resolveMediaUris via reflection
            var resolveMethod = builderClass.getDeclaredMethod("resolveMediaUris", String.class);
            resolveMethod.setAccessible(true);
            return (List<Map<String, Object>>) resolveMethod.invoke(builderObj, "openai");
        }

        @Test
        @DisplayName("single image URI resolves to OpenAI image_url block")
        void singleImageResolves() throws Exception {
            List<Map<String, Object>> parts = buildAndAttachMedia("media://photo.png");

            assertEquals(1, parts.size());
            Map<String, Object> imageBlock = parts.get(0);
            assertEquals("image_url", imageBlock.get("type"));

            @SuppressWarnings("unchecked")
            Map<String, Object> imageUrl = (Map<String, Object>) imageBlock.get("image_url");
            String url = (String) imageUrl.get("url");
            assertTrue(url.startsWith("data:image/png;base64,"));
            assertTrue(url.contains(PNG_B64));
        }

        @Test
        @DisplayName("multiple image URIs resolve to multiple blocks")
        void multipleImagesResolve() throws Exception {
            List<Map<String, Object>> parts = buildAndAttachMedia(
                "media://photo.png", "media://banner.jpg");

            assertEquals(2, parts.size());

            // First image
            assertEquals("image_url", parts.get(0).get("type"));

            // Second image
            assertEquals("image_url", parts.get(1).get("type"));
            @SuppressWarnings("unchecked")
            Map<String, Object> imageUrl = (Map<String, Object>) parts.get(1).get("image_url");
            String url = (String) imageUrl.get("url");
            assertTrue(url.startsWith("data:image/jpeg;base64,"));
        }

        @Test
        @DisplayName("failed fetch is gracefully skipped")
        void failedFetchSkipped() throws Exception {
            mediaStore.setFailOnFetch(true);
            List<Map<String, Object>> parts = buildAndAttachMedia("media://photo.png");

            assertTrue(parts.isEmpty());
        }

        @Test
        @DisplayName("unknown URI produces empty result (not exception)")
        void unknownUriSkipped() throws Exception {
            List<Map<String, Object>> parts = buildAndAttachMedia("media://nonexistent.png");

            assertTrue(parts.isEmpty());
        }

        @Test
        @DisplayName("Claude vendor format uses base64 image block")
        void claudeVendorFormat() throws Exception {
            proxy.updateProvider("http://localhost:8080", "llm_generate", "claude");

            MeshLlmAgent.GenerateBuilder builder = proxy.request();
            builder.user("Describe").media("media://photo.png");

            Object builderObj = builder;
            Class<?> builderClass = builderObj.getClass();
            var resolveMethod = builderClass.getDeclaredMethod("resolveMediaUris", String.class);
            resolveMethod.setAccessible(true);

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> parts =
                (List<Map<String, Object>>) resolveMethod.invoke(builderObj, "claude");

            assertEquals(1, parts.size());
            Map<String, Object> block = parts.get(0);
            assertEquals("image", block.get("type"));

            @SuppressWarnings("unchecked")
            Map<String, Object> source = (Map<String, Object>) block.get("source");
            assertEquals("base64", source.get("type"));
            assertEquals("image/png", source.get("media_type"));
            assertEquals(PNG_B64, source.get("data"));
        }
    }

    // =========================================================================
    // attachMediaToLastUserMessage tests
    // =========================================================================

    @Nested
    @DisplayName("attachMediaToLastUserMessage")
    class AttachMediaTests {

        @SuppressWarnings("unchecked")
        private void invokeAttach(Object builder, List<Map<String, Object>> messages) throws Exception {
            Class<?> builderClass = builder.getClass();
            // The method needs ProviderEndpoint as second param
            Class<?> providerEndpointClass = MeshLlmAgentProxy.ProviderEndpoint.class;
            var attachMethod = builderClass.getDeclaredMethod(
                "attachMediaToLastUserMessage", List.class, providerEndpointClass);
            attachMethod.setAccessible(true);

            var endpoint = new MeshLlmAgentProxy.ProviderEndpoint(
                "http://localhost:8080", "llm_generate", "openai");
            attachMethod.invoke(builder, messages, endpoint);
        }

        @Test
        @DisplayName("converts plain text user message to multipart with image")
        void convertPlainTextToMultipart() throws Exception {
            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .user("Describe this image")
                .media("media://photo.png");

            List<Map<String, Object>> messages = new ArrayList<>();
            messages.add(new LinkedHashMap<>(Map.of("role", "user", "content", "Describe this image")));

            invokeAttach(builder, messages);

            Map<String, Object> userMsg = messages.get(0);
            assertEquals("user", userMsg.get("role"));

            // Content should now be a list (multipart)
            assertInstanceOf(List.class, userMsg.get("content"));

            List<Object> content = (List<Object>) userMsg.get("content");
            assertEquals(2, content.size());

            // First part: text
            Map<String, Object> textPart = (Map<String, Object>) content.get(0);
            assertEquals("text", textPart.get("type"));
            assertEquals("Describe this image", textPart.get("text"));

            // Second part: image
            Map<String, Object> imagePart = (Map<String, Object>) content.get(1);
            assertEquals("image_url", imagePart.get("type"));
        }

        @Test
        @DisplayName("attaches to last user message when multiple present")
        void attachToLastUserMessage() throws Exception {
            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .user("First message")
                .user("Second message - describe this")
                .media("media://photo.png");

            List<Map<String, Object>> messages = new ArrayList<>();
            messages.add(new LinkedHashMap<>(Map.of("role", "user", "content", "First message")));
            messages.add(new LinkedHashMap<>(Map.of("role", "user", "content", "Second message - describe this")));

            invokeAttach(builder, messages);

            // First message should remain plain text
            assertInstanceOf(String.class, messages.get(0).get("content"));
            assertEquals("First message", messages.get(0).get("content"));

            // Second message should be multipart
            assertInstanceOf(List.class, messages.get(1).get("content"));
        }

        @Test
        @DisplayName("no-op when no user messages exist")
        void noUserMessage() throws Exception {
            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .system("You are helpful")
                .media("media://photo.png");

            List<Map<String, Object>> messages = new ArrayList<>();
            messages.add(new LinkedHashMap<>(Map.of("role", "system", "content", "You are helpful")));

            invokeAttach(builder, messages);

            // System message should remain unchanged
            assertInstanceOf(String.class, messages.get(0).get("content"));
        }

        @Test
        @DisplayName("no-op when MediaStore is null")
        void noMediaStore() throws Exception {
            proxy.setMediaStore(null);

            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .user("Describe this")
                .media("media://photo.png");

            List<Map<String, Object>> messages = new ArrayList<>();
            messages.add(new LinkedHashMap<>(Map.of("role", "user", "content", "Describe this")));

            invokeAttach(builder, messages);

            // Message should remain unchanged
            assertInstanceOf(String.class, messages.get(0).get("content"));
        }
    }

    // =========================================================================
    // MediaStore interaction
    // =========================================================================

    @Nested
    @DisplayName("MediaStore interaction")
    class MediaStoreInteractionTests {

        @Test
        @DisplayName("fetch is called for each media URI")
        void fetchCalledPerUri() throws Exception {
            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .user("Compare these images")
                .media("media://photo.png", "media://banner.jpg");

            Object builderObj = builder;
            Class<?> builderClass = builderObj.getClass();
            var resolveMethod = builderClass.getDeclaredMethod("resolveMediaUris", String.class);
            resolveMethod.setAccessible(true);
            resolveMethod.invoke(builderObj, "openai");

            assertEquals(2, mediaStore.getFetchCount());
        }

        @Test
        @DisplayName("partial failure resolves remaining URIs")
        void partialFailure() throws Exception {
            // Add a failing URI by not putting it in the store
            MeshLlmAgent.GenerateBuilder builder = proxy.request()
                .user("Compare these images")
                .media("media://nonexistent.png", "media://photo.png");

            Object builderObj = builder;
            Class<?> builderClass = builderObj.getClass();
            var resolveMethod = builderClass.getDeclaredMethod("resolveMediaUris", String.class);
            resolveMethod.setAccessible(true);

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> parts =
                (List<Map<String, Object>>) resolveMethod.invoke(builderObj, "openai");

            // Only the existing URI should resolve
            assertEquals(1, parts.size());
            assertEquals(2, mediaStore.getFetchCount());
        }
    }
}
