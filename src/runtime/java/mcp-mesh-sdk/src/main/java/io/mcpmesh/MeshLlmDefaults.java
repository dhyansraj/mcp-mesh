package io.mcpmesh;

/**
 * Single source of truth for {@link MeshLlm} default values.
 *
 * <p>These compile-time constants are referenced both by the annotation
 * defaults on {@link MeshLlm} and by the starter-side fallbacks (used when no
 * annotation config is present). Keeping them here guarantees the two surfaces
 * never drift apart.
 *
 * <p>The sentinel constants ({@link #MAX_TOKENS_UNSET}, {@link #TEMPERATURE_UNSET})
 * encode "unset" for annotation primitives that cannot be {@code null}. When a
 * value is unset the SDK does NOT inject it into the wire {@code model_params};
 * the LLM provider's own default is used instead.
 */
public final class MeshLlmDefaults {

    /**
     * Default maximum iterations for the agentic loop. Matches the
     * Python/TypeScript SDK default of 10.
     */
    public static final int MAX_ITERATIONS = 10;

    /**
     * Sentinel for an unset {@code maxTokens}. When {@code maxTokens} equals
     * this value, no {@code max_tokens} is sent on the wire and the provider's
     * own default applies.
     */
    public static final int MAX_TOKENS_UNSET = -1;

    /**
     * Sentinel for an unset {@code temperature}. When {@code temperature} is
     * {@code NaN}, no {@code temperature} is sent on the wire and the provider's
     * own default applies.
     */
    public static final double TEMPERATURE_UNSET = Double.NaN;

    /**
     * Sentinel for an unset {@code outputMode}. When {@code outputMode} equals
     * this value, no {@code output_mode} is sent on the wire and the provider
     * auto-selects the structured-output mode per vendor/schema (today's
     * behavior — zero regression).
     */
    public static final String OUTPUT_MODE_UNSET = "";

    /**
     * {@code outputMode} requesting strict, schema-enforced structured output
     * (OpenAI response_format, Gemini responseSchema, Anthropic native
     * output_format / strict).
     */
    public static final String OUTPUT_MODE_STRICT = "strict";

    /**
     * {@code outputMode} requesting prompt-based JSON-hint structured output
     * (schema instructions injected into the system prompt).
     */
    public static final String OUTPUT_MODE_HINT = "hint";

    /**
     * {@code outputMode} requesting plain text output (no structured-output
     * enforcement).
     */
    public static final String OUTPUT_MODE_TEXT = "text";

    private MeshLlmDefaults() {
    }
}
