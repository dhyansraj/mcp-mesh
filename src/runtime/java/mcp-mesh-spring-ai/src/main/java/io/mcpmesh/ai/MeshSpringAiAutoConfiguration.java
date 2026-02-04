package io.mcpmesh.ai;

import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.ai.chat.model.ChatModel;

/**
 * Auto-configuration for MCP Mesh Spring AI support.
 *
 * <p>This configuration is automatically applied when:
 * <ul>
 *   <li>Spring AI ChatModel is on the classpath</li>
 *   <li>MCP Mesh SDK is on the classpath</li>
 * </ul>
 *
 * <p>Provides:
 * <ul>
 *   <li>{@link MeshLlmProviderProcessor} - Processes @MeshLlmProvider annotations</li>
 *   <li>{@link SpringAiLlmProvider} - Spring AI integration for LLM calls</li>
 * </ul>
 */
@AutoConfiguration
@ConditionalOnClass({ChatModel.class})
public class MeshSpringAiAutoConfiguration {

    /**
     * Create the LLM provider processor.
     *
     * <p>This processor detects @MeshLlmProvider annotations and registers
     * LLM capabilities with the mesh.
     */
    @Bean
    @ConditionalOnMissingBean
    public MeshLlmProviderProcessor meshLlmProviderProcessor() {
        return new MeshLlmProviderProcessor();
    }

    /**
     * Create the Spring AI LLM provider.
     *
     * <p>This provider wraps Spring AI ChatClient for LLM calls.
     */
    @Bean
    @ConditionalOnMissingBean
    public SpringAiLlmProvider springAiLlmProvider() {
        return new SpringAiLlmProvider();
    }
}
