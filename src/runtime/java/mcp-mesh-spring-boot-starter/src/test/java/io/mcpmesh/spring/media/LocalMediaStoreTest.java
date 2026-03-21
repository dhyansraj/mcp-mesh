package io.mcpmesh.spring.media;

import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

@DisplayName("LocalMediaStore")
class LocalMediaStoreTest {

    private Path tempDir;
    private LocalMediaStore store;

    @BeforeEach
    void setUp() throws IOException {
        tempDir = Files.createTempDirectory("mcp-mesh-media-test");
        store = new LocalMediaStore(tempDir.toString(), "media/");
    }

    @AfterEach
    void tearDown() throws IOException {
        // Clean up temp directory
        if (tempDir != null && Files.exists(tempDir)) {
            Files.walk(tempDir)
                .sorted(java.util.Comparator.reverseOrder())
                .forEach(path -> {
                    try { Files.deleteIfExists(path); } catch (IOException ignored) {}
                });
        }
    }

    @Nested
    @DisplayName("upload and fetch")
    class UploadFetchTests {

        @Test
        @DisplayName("round-trip preserves data and returns file URI")
        void roundTripPreservesData() {
            byte[] data = "hello world".getBytes();
            String uri = store.upload(data, "test.txt", "text/plain");

            assertNotNull(uri);
            assertTrue(uri.startsWith("file://"), "URI should use file:// scheme");
            assertTrue(uri.contains("media/test.txt"), "URI should contain prefix and filename");

            MediaFetchResult result = store.fetch(uri);
            assertNotNull(result);
            assertArrayEquals(data, result.data());
        }

        @Test
        @DisplayName("round-trip with binary data")
        void roundTripBinaryData() {
            byte[] data = new byte[]{0x00, 0x01, (byte) 0xFF, (byte) 0xFE, 0x42};
            String uri = store.upload(data, "binary.bin", "application/octet-stream");

            MediaFetchResult result = store.fetch(uri);
            assertArrayEquals(data, result.data());
        }

        @Test
        @DisplayName("upload with nested path creates directories")
        void uploadCreatesNestedDirectories() {
            byte[] data = "nested content".getBytes();
            String uri = store.upload(data, "sub/dir/deep.txt", "text/plain");

            assertTrue(uri.contains("media/sub/dir/deep.txt"));
            assertTrue(store.exists(uri));

            MediaFetchResult result = store.fetch(uri);
            assertArrayEquals(data, result.data());
        }
    }

    @Nested
    @DisplayName("exists")
    class ExistsTests {

        @Test
        @DisplayName("returns true after upload")
        void returnsTrueAfterUpload() {
            String uri = store.upload("data".getBytes(), "exists-test.txt", "text/plain");
            assertTrue(store.exists(uri));
        }

        @Test
        @DisplayName("returns false for non-existent file")
        void returnsFalseForNonExistent() {
            assertFalse(store.exists("file:///does/not/exist.txt"));
        }

        @Test
        @DisplayName("returns false before upload")
        void returnsFalseBeforeUpload() {
            String fakeUri = "file://" + tempDir.resolve("media/not-yet.txt");
            assertFalse(store.exists(fakeUri));
        }
    }

    @Nested
    @DisplayName("fetch errors")
    class FetchErrorTests {

        @Test
        @DisplayName("throws MediaStoreException for non-existent file")
        void throwsForNonExistent() {
            assertThrows(MediaStoreException.class,
                () -> store.fetch("file:///does/not/exist.txt"));
        }
    }

    @Nested
    @DisplayName("prefix handling")
    class PrefixTests {

        @Test
        @DisplayName("empty prefix stores directly under base path")
        void emptyPrefixStoresDirectly() {
            LocalMediaStore noPrefix = new LocalMediaStore(tempDir.toString(), "");
            String uri = noPrefix.upload("data".getBytes(), "direct.txt", "text/plain");
            assertTrue(uri.contains("direct.txt"));
            assertTrue(noPrefix.exists(uri));
        }

        @Test
        @DisplayName("null prefix treated as empty")
        void nullPrefixTreatedAsEmpty() {
            LocalMediaStore nullPrefix = new LocalMediaStore(tempDir.toString(), null);
            String uri = nullPrefix.upload("data".getBytes(), "null-prefix.txt", "text/plain");
            assertTrue(uri.contains("null-prefix.txt"));
            assertTrue(nullPrefix.exists(uri));
        }
    }
}
