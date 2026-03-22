package io.mcpmesh.spring;

import io.mcpmesh.MediaParam;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.junit.jupiter.api.*;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("@MediaParam schema generation")
class MediaParamTest {

    private MeshToolRegistry registry;

    @BeforeEach
    void setUp() {
        registry = new MeshToolRegistry();
    }

    // ── Test fixtures ──────────────────────────────────────────────────

    @SuppressWarnings("unused")
    static class SampleAgent {

        @MeshTool(capability = "analyze", description = "Analyze an image")
        public String analyze(
            @Param(value = "question", description = "The question to answer") String question,
            @MediaParam("image/*") @Param("image") String imageUri
        ) {
            return "result";
        }

        @MeshTool(capability = "process_any", description = "Process any media")
        public String processAny(
            @MediaParam @Param("media") String mediaUri
        ) {
            return "result";
        }

        @MeshTool(capability = "process_pdf", description = "Process a PDF")
        public String processPdf(
            @MediaParam("application/pdf") @Param(value = "doc", description = "PDF document") String docUri
        ) {
            return "result";
        }

        @MeshTool(capability = "plain_tool", description = "No media params")
        public String plainTool(
            @Param("name") String name
        ) {
            return "hello";
        }
    }

    // ── Tests ──────────────────────────────────────────────────────────

    @Nested
    @DisplayName("x-media-type in schema")
    class XMediaTypeTests {

        @Test
        @DisplayName("@MediaParam adds x-media-type to property schema")
        @SuppressWarnings("unchecked")
        void mediaParamAddsXMediaType() throws Exception {
            registerTool("analyze");

            Map<String, Object> schema = registry.getTool("analyze").inputSchema();
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            Map<String, Object> imageProp = (Map<String, Object>) properties.get("image");

            assertEquals("image/*", imageProp.get("x-media-type"));
        }

        @Test
        @DisplayName("default MIME type is */* when no value specified")
        @SuppressWarnings("unchecked")
        void defaultMimeType() throws Exception {
            registerTool("process_any");

            Map<String, Object> schema = registry.getTool("process_any").inputSchema();
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            Map<String, Object> mediaProp = (Map<String, Object>) properties.get("media");

            assertEquals("*/*", mediaProp.get("x-media-type"));
        }

        @Test
        @DisplayName("specific MIME type preserved")
        @SuppressWarnings("unchecked")
        void specificMimeType() throws Exception {
            registerTool("process_pdf");

            Map<String, Object> schema = registry.getTool("process_pdf").inputSchema();
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            Map<String, Object> docProp = (Map<String, Object>) properties.get("doc");

            assertEquals("application/pdf", docProp.get("x-media-type"));
        }

        @Test
        @DisplayName("parameter without @MediaParam has no x-media-type")
        @SuppressWarnings("unchecked")
        void noMediaParamNoXMediaType() throws Exception {
            registerTool("analyze");

            Map<String, Object> schema = registry.getTool("analyze").inputSchema();
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            Map<String, Object> questionProp = (Map<String, Object>) properties.get("question");

            assertNull(questionProp.get("x-media-type"));
        }

        @Test
        @DisplayName("tool with no @MediaParam at all has no x-media-type anywhere")
        @SuppressWarnings("unchecked")
        void plainToolNoXMediaType() throws Exception {
            registerTool("plain_tool");

            Map<String, Object> schema = registry.getTool("plain_tool").inputSchema();
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            Map<String, Object> nameProp = (Map<String, Object>) properties.get("name");

            assertNull(nameProp.get("x-media-type"));
        }
    }

    @Nested
    @DisplayName("description augmentation")
    class DescriptionTests {

        @Test
        @DisplayName("@MediaParam appends media note to description")
        @SuppressWarnings("unchecked")
        void mediaParamAppendsDescriptionNote() throws Exception {
            registerTool("analyze");

            Map<String, Object> schema = registry.getTool("analyze").inputSchema();
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            Map<String, Object> imageProp = (Map<String, Object>) properties.get("image");

            String desc = (String) imageProp.get("description");
            assertNotNull(desc);
            assertTrue(desc.contains("(accepts media URI: image/*)"), "Expected media note in: " + desc);
        }

        @Test
        @DisplayName("existing description is preserved alongside media note")
        @SuppressWarnings("unchecked")
        void existingDescriptionPreserved() throws Exception {
            registerTool("process_pdf");

            Map<String, Object> schema = registry.getTool("process_pdf").inputSchema();
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            Map<String, Object> docProp = (Map<String, Object>) properties.get("doc");

            String desc = (String) docProp.get("description");
            assertNotNull(desc);
            assertTrue(desc.contains("PDF document"), "Original description missing: " + desc);
            assertTrue(desc.contains("(accepts media URI: application/pdf)"), "Media note missing: " + desc);
        }

        @Test
        @DisplayName("@MediaParam without existing description creates media-only description")
        @SuppressWarnings("unchecked")
        void mediaParamWithoutExistingDescription() throws Exception {
            registerTool("analyze");

            Map<String, Object> schema = registry.getTool("analyze").inputSchema();
            Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
            Map<String, Object> imageProp = (Map<String, Object>) properties.get("image");

            String desc = (String) imageProp.get("description");
            assertEquals("(accepts media URI: image/*)", desc);
        }
    }

    @Nested
    @DisplayName("required field behavior")
    class RequiredFieldTests {

        @Test
        @DisplayName("@MediaParam does not affect required list")
        @SuppressWarnings("unchecked")
        void mediaParamDoesNotAffectRequired() throws Exception {
            registerTool("analyze");

            Map<String, Object> schema = registry.getTool("analyze").inputSchema();
            List<String> required = (List<String>) schema.get("required");

            assertNotNull(required);
            assertTrue(required.contains("question"));
            assertTrue(required.contains("image"));
        }
    }

    // ── Helpers ────────────────────────────────────────────────────────

    private void registerTool(String capability) throws Exception {
        for (var method : SampleAgent.class.getDeclaredMethods()) {
            MeshTool ann = method.getAnnotation(MeshTool.class);
            if (ann != null && ann.capability().equals(capability)) {
                registry.registerTool(new SampleAgent(), method, ann);
                return;
            }
        }
        fail("No @MeshTool method found with capability: " + capability);
    }
}
