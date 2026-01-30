package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Creates a zero-code LLM provider wrapping Spring AI.
 *
 * <p>Apply this annotation to a Spring Boot application class to create
 * an agent that provides LLM capabilities to other agents in the mesh.
 *
 * <h2>Example</h2>
 * <pre>{@code
 * @MeshAgent(name = "claude-provider", port = 9110)
 * @MeshLlmProvider(
 *     model = "anthropic/claude-sonnet-4-5",
 *     capability = "llm",
 *     tags = {"llm", "claude", "anthropic", "provider"}
 * )
 * @SpringBootApplication
 * public class ClaudeProviderAgent {
 *     public static void main(String[] args) {
 *         SpringApplication.run(ClaudeProviderAgent.class, args);
 *     }
 *     // No implementation needed - @MeshLlmProvider handles everything
 * }
 * }</pre>
 *
 * <h2>Supported Models</h2>
 * <p>Model strings follow Spring AI conventions:
 * <ul>
 *   <li>{@code anthropic/claude-sonnet-4-5} - Claude models</li>
 *   <li>{@code openai/gpt-4} - OpenAI models</li>
 *   <li>{@code ollama/llama2} - Ollama local models</li>
 * </ul>
 *
 * <h2>Environment Variables</h2>
 * <p>API keys are read from environment:
 * <ul>
 *   <li>{@code ANTHROPIC_API_KEY} - For Anthropic/Claude models</li>
 *   <li>{@code OPENAI_API_KEY} - For OpenAI models</li>
 * </ul>
 *
 * @see MeshLlm#providerSelector()
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
public @interface MeshLlmProvider {

    /**
     * Spring AI model string.
     *
     * <p>Format: {@code provider/model-name}
     */
    String model();

    /**
     * Capability name for mesh discovery.
     *
     * <p>Other agents reference this via {@code @Selector(capability = "llm")}.
     */
    String capability() default "llm";

    /**
     * Tags for filtering.
     *
     * <p>Other agents can prefer specific providers via tags.
     */
    String[] tags() default {"llm", "provider"};

    /**
     * Capability version (semver format).
     */
    String version() default "1.0.0";
}
