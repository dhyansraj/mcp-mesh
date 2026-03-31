package io.mcpmesh.core;

/**
 * Functional interface for a test-only override of
 * {@link MeshCoreBridge#formatSystemPrompt}.
 *
 * <p>When a non-null instance is registered via
 * {@link MeshCoreBridge#setFormatSystemPromptOverride}, it is called
 * <em>instead of</em> the native Rust library. This allows unit tests
 * to run without the native library present (e.g. in CI).
 */
@FunctionalInterface
public interface FormatSystemPromptFn {
    String apply(String provider, String basePrompt, boolean hasTools,
                 boolean hasMediaParams, String schemaJson,
                 String schemaName, String outputMode);
}
