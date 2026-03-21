package io.mcpmesh.spring.media;

import io.modelcontextprotocol.spec.McpSchema.ResourceLink;
import org.junit.jupiter.api.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.File;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("MeshMedia")
class MeshMediaTest {

    /**
     * In-memory MediaStore that records uploads for verification.
     */
    private static class TestMediaStore implements MediaStore {
        private final Map<String, MediaFetchResult> store = new HashMap<>();

        @Override
        public String upload(byte[] data, String filename, String mimeType) {
            String uri = "media://" + filename;
            store.put(uri, new MediaFetchResult(data, mimeType));
            return uri;
        }

        @Override
        public MediaFetchResult fetch(String uri) {
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

    /**
     * Minimal MultipartFile stub for testing without a full servlet container.
     */
    private static class StubMultipartFile implements MultipartFile {
        private final String name;
        private final String originalFilename;
        private final String contentType;
        private final byte[] content;

        StubMultipartFile(String name, String originalFilename, String contentType, byte[] content) {
            this.name = name;
            this.originalFilename = originalFilename;
            this.contentType = contentType;
            this.content = content;
        }

        @Override public String getName() { return name; }
        @Override public String getOriginalFilename() { return originalFilename; }
        @Override public String getContentType() { return contentType; }
        @Override public boolean isEmpty() { return content.length == 0; }
        @Override public long getSize() { return content.length; }
        @Override public byte[] getBytes() { return content; }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(content); }
        @Override public void transferTo(File dest) { throw new UnsupportedOperationException(); }
    }

    private TestMediaStore store;

    @BeforeEach
    void setUp() {
        store = new TestMediaStore();
    }

    // ── URI-based mediaResult (existing behavior) ───────────────────────

    @Nested
    @DisplayName("URI-based mediaResult")
    class UriBasedTests {

        @Test
        @DisplayName("creates ResourceLink with uri, name, and mimeType")
        void basicMediaResult() {
            ResourceLink link = MeshMedia.mediaResult("file:///tmp/img.png", "img.png", "image/png");

            assertEquals("file:///tmp/img.png", link.uri());
            assertEquals("img.png", link.name());
            assertEquals("image/png", link.mimeType());
        }

        @Test
        @DisplayName("creates ResourceLink with description and size")
        void mediaResultWithMetadata() {
            ResourceLink link = MeshMedia.mediaResult(
                "s3://bucket/chart.png", "chart.png", "image/png", "Sales chart", 4096L);

            assertEquals("s3://bucket/chart.png", link.uri());
            assertEquals("chart.png", link.name());
            assertEquals("image/png", link.mimeType());
            assertEquals("Sales chart", link.description());
            assertEquals(4096L, link.size());
        }
    }

    // ── Bytes-based mediaResult ─────────────────────────────────────────

    @Nested
    @DisplayName("bytes-based mediaResult")
    class BytesBasedTests {

        @Test
        @DisplayName("uploads bytes and returns ResourceLink with correct fields")
        void testMediaResultFromBytes() {
            byte[] data = "chart-data".getBytes();
            ResourceLink link = MeshMedia.mediaResult(data, "chart.png", "image/png", store);

            assertEquals("media://chart.png", link.uri());
            assertEquals("chart.png", link.name());
            assertEquals("image/png", link.mimeType());
            assertEquals((long) data.length, link.size());
            assertTrue(store.exists("media://chart.png"));

            MediaFetchResult fetched = store.fetch("media://chart.png");
            assertArrayEquals(data, fetched.data());
        }

        @Test
        @DisplayName("uploads bytes with name override and description")
        void testMediaResultFromBytesWithName() {
            byte[] data = new byte[]{0x01, 0x02, 0x03};
            ResourceLink link = MeshMedia.mediaResult(
                data, "output.bin", "application/octet-stream",
                "Binary Output", "Generated binary data", store);

            assertEquals("media://output.bin", link.uri());
            assertEquals("Binary Output", link.name());
            assertEquals("application/octet-stream", link.mimeType());
            assertEquals("Generated binary data", link.description());
            assertEquals(3L, link.size());
        }

        @Test
        @DisplayName("null name falls back to filename")
        void testMediaResultFromBytesNullName() {
            byte[] data = "test".getBytes();
            ResourceLink link = MeshMedia.mediaResult(
                data, "fallback.txt", "text/plain", null, null, store);

            assertEquals("fallback.txt", link.name());
        }
    }

    // ── saveUpload ──────────────────────────────────────────────────────

    @Nested
    @DisplayName("saveUpload")
    class SaveUploadTests {

        @Test
        @DisplayName("saves MultipartFile and returns URI")
        void testSaveUpload() throws IOException {
            byte[] content = "hello world".getBytes();
            MultipartFile file = new StubMultipartFile(
                "file", "greeting.txt", "text/plain", content);

            String uri = MeshMedia.saveUpload(file, store);

            assertEquals("media://greeting.txt", uri);
            assertTrue(store.exists(uri));
            assertArrayEquals(content, store.fetch(uri).data());
        }

        @Test
        @DisplayName("falls back to defaults when filename and contentType are null")
        void testSaveUploadNullDefaults() throws IOException {
            byte[] content = new byte[]{0x00};
            MultipartFile file = new StubMultipartFile("file", null, null, content);

            String uri = MeshMedia.saveUpload(file, store);

            assertEquals("media://upload", uri);
            assertEquals("application/octet-stream", store.fetch(uri).mimeType());
        }

        @Test
        @DisplayName("saves with filename and mimeType overrides")
        void testSaveUploadWithOverrides() throws IOException {
            byte[] content = "data".getBytes();
            MultipartFile file = new StubMultipartFile(
                "file", "original.txt", "text/plain", content);

            String uri = MeshMedia.saveUpload(file, store, "renamed.csv", "text/csv");

            assertEquals("media://renamed.csv", uri);
            assertEquals("text/csv", store.fetch(uri).mimeType());
        }

        @Test
        @DisplayName("override with null values falls back to original")
        void testSaveUploadOverridesWithNull() throws IOException {
            byte[] content = "data".getBytes();
            MultipartFile file = new StubMultipartFile(
                "file", "original.txt", "text/plain", content);

            String uri = MeshMedia.saveUpload(file, store, null, null);

            assertEquals("media://original.txt", uri);
            assertEquals("text/plain", store.fetch(uri).mimeType());
        }
    }

    // ── saveUploadResult ────────────────────────────────────────────────

    @Nested
    @DisplayName("saveUploadResult")
    class SaveUploadResultTests {

        @Test
        @DisplayName("returns MediaUploadResult with all fields populated")
        void testSaveUploadResult() throws IOException {
            byte[] content = "report content".getBytes();
            MultipartFile file = new StubMultipartFile(
                "file", "report.pdf", "application/pdf", content);

            MediaUploadResult result = MeshMedia.saveUploadResult(file, store);

            assertEquals("media://report.pdf", result.uri());
            assertEquals("report.pdf", result.name());
            assertEquals("application/pdf", result.mimeType());
            assertEquals(content.length, result.size());
            assertTrue(store.exists(result.uri()));
        }

        @Test
        @DisplayName("falls back to defaults when filename and contentType are null")
        void testSaveUploadResultNullDefaults() throws IOException {
            byte[] content = new byte[]{0x42};
            MultipartFile file = new StubMultipartFile("file", null, null, content);

            MediaUploadResult result = MeshMedia.saveUploadResult(file, store);

            assertEquals("upload", result.name());
            assertEquals("application/octet-stream", result.mimeType());
            assertEquals(1, result.size());
        }
    }
}
