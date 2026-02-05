package io.mcpmesh.core;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the MCP Mesh Core FFI layer.
 *
 * <p>These tests require the native library to be built. Set the environment
 * variable MESH_NATIVE_LIB_PATH to point to the directory containing the library,
 * or ensure it's available in the system library path.
 */
class MeshCoreTest {

    private static MeshCore core;

    @BeforeAll
    static void setup() {
        // Skip tests if native library is not available
        try {
            core = MeshCore.load();
        } catch (UnsatisfiedLinkError e) {
            System.err.println("Native library not available, skipping tests: " + e.getMessage());
            System.err.println("Set MESH_NATIVE_LIB_PATH to the directory containing libmcp_mesh_core.dylib");
            throw new AssumptionViolatedException("Native library not available", e);
        }
    }

    @Test
    void testVersion() {
        String version = core.mesh_version();
        assertNotNull(version, "Version should not be null");
        assertFalse(version.isEmpty(), "Version should not be empty");
        System.out.println("MCP Mesh Core version: " + version);
    }

    @Test
    void testLastErrorInitiallyNull() {
        // Initially there should be no error
        var ptr = core.mesh_last_error();
        assertNull(ptr, "Last error should be null initially");
    }

    @Test
    void testStartAgentWithNullSpec() {
        // Passing null should return null and set an error
        var handle = core.mesh_start_agent(null);
        assertNull(handle, "Handle should be null for null spec");

        // Check error message
        var errorPtr = core.mesh_last_error();
        assertNotNull(errorPtr, "Error should be set");
        String error = errorPtr.getString(0);
        assertTrue(error.contains("null"), "Error should mention null: " + error);
        core.mesh_free_string(errorPtr);
    }

    @Test
    void testStartAgentWithInvalidJson() {
        // Passing invalid JSON should return null and set an error
        var handle = core.mesh_start_agent("not valid json");
        assertNull(handle, "Handle should be null for invalid JSON");

        // Check error message
        var errorPtr = core.mesh_last_error();
        assertNotNull(errorPtr, "Error should be set");
        String error = errorPtr.getString(0);
        assertTrue(error.toLowerCase().contains("json") || error.toLowerCase().contains("parse"),
                "Error should mention JSON parsing: " + error);
        core.mesh_free_string(errorPtr);
    }

    @Test
    void testFreeHandleWithNull() {
        // Should not throw when freeing null handle
        assertDoesNotThrow(() -> core.mesh_free_handle(null));
    }

    @Test
    void testFreeStringWithNull() {
        // Should not throw when freeing null string
        assertDoesNotThrow(() -> core.mesh_free_string(null));
    }

    @Test
    void testNativeLoaderPlatformClassifier() {
        String classifier = NativeLoader.getPlatformClassifier();
        assertNotNull(classifier, "Platform classifier should not be null");
        assertFalse(classifier.isEmpty(), "Platform classifier should not be empty");
        System.out.println("Platform classifier: " + classifier);

        // Should be in format os-arch
        assertTrue(classifier.contains("-"), "Classifier should contain hyphen: " + classifier);
    }

    @Test
    void testNativeLoaderLibraryFileName() {
        String fileName = NativeLoader.getLibraryFileName();
        assertNotNull(fileName, "Library file name should not be null");
        assertTrue(fileName.contains("mcp_mesh_core"), "Library file name should contain mcp_mesh_core: " + fileName);
        System.out.println("Library file name: " + fileName);
    }

    // Helper class for JUnit 5 assumptions
    private static class AssumptionViolatedException extends RuntimeException {
        AssumptionViolatedException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
