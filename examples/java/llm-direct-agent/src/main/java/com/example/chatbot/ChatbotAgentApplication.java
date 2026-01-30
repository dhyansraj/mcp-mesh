package com.example.chatbot;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * MCP Mesh agent demonstrating @MeshLlm with direct Spring AI calls.
 *
 * <p>This example shows:
 * <ul>
 *   <li>@MeshLlm with provider="claude" - Direct API calls via Spring AI</li>
 *   <li>No mesh delegation - API key required locally</li>
 *   <li>Simple chat interface - Text in, text out</li>
 *   <li>Temperature and token configuration</li>
 * </ul>
 *
 * <h2>Difference from llm-mesh-agent</h2>
 * <pre>
 * llm-mesh-agent:    User -> Agent -> Mesh -> LLM Provider Agent -> Claude API
 * llm-direct-agent:  User -> Agent -> Spring AI -> Claude API (direct)
 * </pre>
 *
 * <h2>When to Use Direct vs Mesh</h2>
 * <ul>
 *   <li>Direct: Single agent, simpler setup, API key managed locally</li>
 *   <li>Mesh: Multiple agents share LLM, centralized API key management</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Set API key
 * export ANTHROPIC_API_KEY=your-key-here
 *
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this agent
 * cd examples/java/llm-direct-agent
 * mvn spring-boot:run
 *
 * # Test with meshctl
 * meshctl call chat '{"message": "Hello, how are you?"}'
 * </pre>
 */
@MeshAgent(
    name = "chatbot",
    version = "1.0.0",
    description = "Chatbot with direct LLM access",
    port = 9003
)
@SpringBootApplication
public class ChatbotAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(ChatbotAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Chatbot Agent...");
        SpringApplication.run(ChatbotAgentApplication.class, args);
    }

    /**
     * Chat using direct Spring AI Claude client.
     *
     * <p>The {@code llm} parameter uses Spring AI's Anthropic client directly,
     * not mesh delegation. This requires ANTHROPIC_API_KEY environment variable.
     *
     * @param message User message
     * @param llm     Injected LLM agent (direct Spring AI)
     * @return Chat response
     */
    @MeshLlm(
        provider = "claude",  // Direct: uses Spring AI Anthropic client
        maxIterations = 1,    // Simple chat, no tool calls
        systemPrompt = "You are a helpful, friendly assistant. Keep responses concise.",
        maxTokens = 1024,
        temperature = 0.7
    )
    @MeshTool(
        capability = "chat",
        description = "Interactive chat with Claude",
        tags = {"chat", "llm", "java", "direct"}
    )
    public ChatResponse chat(
        @Param(value = "message", description = "User message") String message,
        MeshLlmAgent llm
    ) {
        log.info("Chat message: {}", message);

        String response;
        String source;

        if (llm != null && llm.isAvailable()) {
            try {
                response = llm.generate(message);
                source = "direct:claude";
            } catch (Exception e) {
                log.error("LLM call failed: {}", e.getMessage());
                response = "I'm sorry, I encountered an error processing your message.";
                source = "error";
            }
        } else {
            log.warn("LLM not available");
            response = "The chat service is currently unavailable. Please check that ANTHROPIC_API_KEY is set.";
            source = "fallback";
        }

        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        return new ChatResponse(message, response, timestamp, source);
    }

    /**
     * Creative writing assistant with higher temperature.
     *
     * @param prompt Creative writing prompt
     * @param llm    Injected LLM agent
     * @return Generated creative text
     */
    @MeshLlm(
        provider = "claude",
        maxIterations = 1,
        systemPrompt = "You are a creative writing assistant. Be imaginative and expressive.",
        maxTokens = 2048,
        temperature = 0.9  // Higher temperature for creativity
    )
    @MeshTool(
        capability = "creative_write",
        description = "Creative writing with Claude",
        tags = {"writing", "creative", "llm", "java"}
    )
    public CreativeResponse creativeWrite(
        @Param(value = "prompt", description = "Creative writing prompt") String prompt,
        MeshLlmAgent llm
    ) {
        log.info("Creative writing prompt: {}", prompt);

        String content;
        String source;

        if (llm != null && llm.isAvailable()) {
            try {
                content = llm.generate(prompt);
                source = "direct:claude";
            } catch (Exception e) {
                log.error("LLM call failed: {}", e.getMessage());
                content = "Unable to generate creative content at this time.";
                source = "error";
            }
        } else {
            content = "Creative writing service unavailable.";
            source = "fallback";
        }

        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        return new CreativeResponse(prompt, content, timestamp, source);
    }

    /**
     * Code explanation assistant with lower temperature for accuracy.
     *
     * @param code Code snippet to explain
     * @param llm  Injected LLM agent
     * @return Code explanation
     */
    @MeshLlm(
        provider = "claude",
        maxIterations = 1,
        systemPrompt = "You are a code explanation assistant. Explain code clearly and accurately.",
        maxTokens = 2048,
        temperature = 0.3  // Lower temperature for accuracy
    )
    @MeshTool(
        capability = "explain_code",
        description = "Explain code with Claude",
        tags = {"code", "explanation", "llm", "java"}
    )
    public CodeExplanation explainCode(
        @Param(value = "code", description = "Code snippet to explain") String code,
        @Param(value = "language", description = "Programming language") String language,
        MeshLlmAgent llm
    ) {
        log.info("Explaining {} code", language);

        String explanation;
        String source;

        if (llm != null && llm.isAvailable()) {
            try {
                String prompt = String.format(
                    "Explain this %s code:\n\n```%s\n%s\n```",
                    language, language, code
                );
                explanation = llm.generate(prompt);
                source = "direct:claude";
            } catch (Exception e) {
                log.error("LLM call failed: {}", e.getMessage());
                explanation = "Unable to explain code at this time.";
                source = "error";
            }
        } else {
            explanation = "Code explanation service unavailable.";
            source = "fallback";
        }

        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        return new CodeExplanation(code, language, explanation, timestamp, source);
    }

    /**
     * Chat response record.
     */
    public record ChatResponse(
        String input,
        String response,
        String timestamp,
        String source
    ) {}

    /**
     * Creative writing response record.
     */
    public record CreativeResponse(
        String prompt,
        String content,
        String timestamp,
        String source
    ) {}

    /**
     * Code explanation record.
     */
    public record CodeExplanation(
        String code,
        String language,
        String explanation,
        String timestamp,
        String source
    ) {}
}
