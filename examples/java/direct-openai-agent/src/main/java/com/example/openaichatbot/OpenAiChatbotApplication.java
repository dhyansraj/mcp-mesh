package com.example.openaichatbot;

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
 * MCP Mesh agent demonstrating @MeshLlm with direct OpenAI calls.
 *
 * <p>This example shows:
 * <ul>
 *   <li>@MeshLlm with provider="openai" - Direct API calls via Spring AI</li>
 *   <li>No mesh delegation - API key required locally</li>
 *   <li>Simple chat interface - Text in, text out</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * export OPENAI_API_KEY=your-key-here
 * meshctl start --registry-only
 * cd examples/java/direct-openai-agent
 * mvn spring-boot:run
 * meshctl call chat '{"message": "Hello!"}'
 * </pre>
 */
@MeshAgent(
    name = "openai-chatbot",
    version = "1.0.0",
    description = "Chatbot with direct OpenAI access",
    port = 9004
)
@SpringBootApplication
public class OpenAiChatbotApplication {

    private static final Logger log = LoggerFactory.getLogger(OpenAiChatbotApplication.class);

    public static void main(String[] args) {
        log.info("Starting OpenAI Chatbot Agent...");
        SpringApplication.run(OpenAiChatbotApplication.class, args);
    }

    @MeshLlm(
        provider = "openai",
        maxIterations = 1,
        systemPrompt = "You are a helpful, friendly assistant. Keep responses concise.",
        maxTokens = 1024,
        temperature = 0.7
    )
    @MeshTool(
        capability = "chat",
        description = "Interactive chat with OpenAI",
        tags = {"chat", "llm", "java", "direct", "openai"}
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
                source = "direct:openai";
            } catch (Exception e) {
                log.error("LLM call failed: {}", e.getMessage());
                response = "I'm sorry, I encountered an error processing your message.";
                source = "error";
            }
        } else {
            log.warn("LLM not available");
            response = "The chat service is currently unavailable. Please check that OPENAI_API_KEY is set.";
            source = "fallback";
        }

        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        return new ChatResponse(message, response, timestamp, source);
    }

    public record ChatResponse(
        String input,
        String response,
        String timestamp,
        String source
    ) {}
}
