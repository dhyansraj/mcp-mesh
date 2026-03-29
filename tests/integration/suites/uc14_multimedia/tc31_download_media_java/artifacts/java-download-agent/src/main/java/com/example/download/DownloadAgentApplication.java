package com.example.download;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.spring.media.MediaStore;
import io.mcpmesh.spring.media.MeshMedia;
import io.mcpmesh.spring.media.MediaFetchResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Test agent for downloadMedia API.
 *
 * <p>Uploads test data via {@link MediaStore#upload}, downloads it back via
 * {@link MeshMedia#downloadMedia}, and returns the comparison result.
 */
@MeshAgent(
    name = "java-download-agent",
    version = "1.0.0",
    description = "Agent for testing downloadMedia API",
    port = 9050
)
@SpringBootApplication
public class DownloadAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(DownloadAgentApplication.class);

    private static final byte[] TEST_CONTENT = "Hello Media Download Test - Java".getBytes(StandardCharsets.UTF_8);
    private static final String TEST_FILENAME = "test-download.txt";
    private static final String TEST_MIME = "text/plain";

    @Autowired
    private MediaStore mediaStore;

    public static void main(String[] args) {
        log.info("Starting Download Test Agent...");
        SpringApplication.run(DownloadAgentApplication.class, args);
    }

    @MeshTool(
        capability = "test_download_media",
        description = "Upload then download media and verify"
    )
    public Map<String, Object> testDownloadMedia() {
        // Upload
        String uri = mediaStore.upload(TEST_CONTENT, TEST_FILENAME, TEST_MIME);
        log.info("Uploaded test media: {}", uri);

        // Download
        MediaFetchResult result = MeshMedia.downloadMedia(uri, mediaStore);
        byte[] data = result.data();
        String mimeType = result.mimeType();
        log.info("Downloaded: {} bytes, mime={}", data.length, mimeType);

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("uri", uri);
        response.put("uploaded_size", TEST_CONTENT.length);
        response.put("downloaded_size", data.length);
        response.put("content_match", Arrays.equals(data, TEST_CONTENT));
        response.put("mime_type", mimeType);
        response.put("downloaded_text", new String(data, StandardCharsets.UTF_8));
        return response;
    }
}
