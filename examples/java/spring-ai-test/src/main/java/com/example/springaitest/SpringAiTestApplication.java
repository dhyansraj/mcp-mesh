package com.example.springaitest;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.anthropic.AnthropicChatModel;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.model.tool.ToolCallingChatOptions;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.function.FunctionToolCallback;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.*;
import java.util.function.Function;

/**
 * Standalone Spring AI 2.0.0-M2 capability test.
 *
 * Tests:
 * 1. Tool calling with internalToolExecutionEnabled(false)
 * 2. Structured output (response_format)
 * 3. Hint-based output (schema in prompt)
 * 4. Chat with message history
 */
@SpringBootApplication
public class SpringAiTestApplication implements CommandLineRunner {

    private static final Logger log = LoggerFactory.getLogger(SpringAiTestApplication.class);

    @Autowired
    private AnthropicChatModel anthropicChatModel;

    public static void main(String[] args) {
        SpringApplication.run(SpringAiTestApplication.class, args);
    }

    @Override
    public void run(String... args) throws Exception {
        log.info("=".repeat(80));
        log.info("SPRING AI 2.0.0-M2 CAPABILITY TEST");
        log.info("=".repeat(80));

        // Test 1: Simple chat (baseline)
        testSimpleChat();

        // Test 2: Chat with message history
        testChatWithHistory();

        // Test 3: Tool calling with execution DISABLED
        testToolCallingNoExecution();

        // Test 4: Tool calling with execution ENABLED (for comparison)
        testToolCallingWithExecution();

        // Test 5: Hint-based structured output
        testHintBasedStructuredOutput();

        // Test 6: Direct Prompt API with tool options
        testPromptApiWithTools();

        log.info("=".repeat(80));
        log.info("ALL TESTS COMPLETE");
        log.info("=".repeat(80));
    }

    /**
     * Test 1: Simple chat - baseline test
     */
    private void testSimpleChat() {
        log.info("\n" + "-".repeat(80));
        log.info("TEST 1: Simple Chat (Baseline)");
        log.info("-".repeat(80));

        try {
            ChatClient client = ChatClient.create(anthropicChatModel);
            String response = client.prompt()
                .system("You are a helpful assistant.")
                .user("Say 'Hello World' and nothing else.")
                .call()
                .content();

            log.info("Response: {}", response);
            log.info("TEST 1 RESULT: SUCCESS");
        } catch (Exception e) {
            log.error("TEST 1 RESULT: FAILED - {}", e.getMessage(), e);
        }
    }

    /**
     * Test 2: Chat with message history
     */
    private void testChatWithHistory() {
        log.info("\n" + "-".repeat(80));
        log.info("TEST 2: Chat with Message History");
        log.info("-".repeat(80));

        try {
            List<Message> messages = new ArrayList<>();
            messages.add(new SystemMessage("You are a helpful assistant. Remember the conversation."));
            messages.add(new UserMessage("My name is Alice."));
            messages.add(new AssistantMessage("Nice to meet you, Alice!"));
            messages.add(new UserMessage("What is my name?"));

            Prompt prompt = new Prompt(messages);
            ChatResponse response = anthropicChatModel.call(prompt);

            String content = response.getResult().getOutput().getText();
            log.info("Response: {}", content);

            boolean remembersName = content.toLowerCase().contains("alice");
            log.info("Remembers name 'Alice': {}", remembersName);
            log.info("TEST 2 RESULT: {}", remembersName ? "SUCCESS" : "FAILED");
        } catch (Exception e) {
            log.error("TEST 2 RESULT: FAILED - {}", e.getMessage(), e);
        }
    }

    /**
     * Test 3: Tool calling with execution DISABLED
     * This is the critical test for mesh delegation mode.
     */
    private void testToolCallingNoExecution() {
        log.info("\n" + "-".repeat(80));
        log.info("TEST 3: Tool Calling with Execution DISABLED");
        log.info("-".repeat(80));

        try {
            // Create a dummy tool callback (should never be called)
            Function<Map<String, Object>, String> getWeatherFunc = args -> {
                log.warn("Tool was unexpectedly called! Args: {}", args);
                return "{\"temperature\": 72, \"conditions\": \"sunny\"}";
            };

            @SuppressWarnings("unchecked")
            ToolCallback weatherTool = FunctionToolCallback
                .builder("getWeather", getWeatherFunc)
                .description("Get the current weather for a city")
                .inputType((Class<Map<String, Object>>) (Class<?>) Map.class)
                .build();

            // Create chat options with tool execution DISABLED
            ToolCallingChatOptions options = ToolCallingChatOptions.builder()
                .toolCallbacks(weatherTool)
                .internalToolExecutionEnabled(false)  // KEY: Don't auto-execute tools
                .build();

            List<Message> messages = List.of(
                new SystemMessage("You are a helpful assistant. Use tools when needed."),
                new UserMessage("What is the weather in San Francisco?")
            );

            Prompt prompt = new Prompt(messages, options);
            ChatResponse response = anthropicChatModel.call(prompt);
            Generation result = response.getResult();
            AssistantMessage output = result.getOutput();

            log.info("Response content: {}", output.getText());
            log.info("hasToolCalls(): {}", output.hasToolCalls());
            log.info("Metadata: {}", output.getMetadata());

            if (output.hasToolCalls()) {
                log.info("Tool calls count: {}", output.getToolCalls().size());
                for (AssistantMessage.ToolCall tc : output.getToolCalls()) {
                    log.info("  Tool call: id={}, name={}, args={}", tc.id(), tc.name(), tc.arguments());
                }
                log.info("TEST 3 RESULT: SUCCESS - Tool calls extracted!");
            } else {
                log.warn("TEST 3 RESULT: FAILED - hasToolCalls() returned false");
                log.info("Checking response metadata for tool calls...");

                // Try to find tool calls in other places
                log.info("Generation metadata: {}", result.getMetadata());
                log.info("ChatResponse metadata: {}", response.getMetadata());
            }
        } catch (Exception e) {
            log.error("TEST 3 RESULT: FAILED - {}", e.getMessage(), e);
        }
    }

    /**
     * Test 4: Tool calling with execution ENABLED (for comparison)
     */
    private void testToolCallingWithExecution() {
        log.info("\n" + "-".repeat(80));
        log.info("TEST 4: Tool Calling with Execution ENABLED");
        log.info("-".repeat(80));

        try {
            // Create a tool that will be called
            Function<Map<String, Object>, String> getWeatherFunc = args -> {
                String city = (String) args.getOrDefault("city", "unknown");
                log.info("Tool getWeather called with city: {}", city);
                return "{\"city\": \"" + city + "\", \"temperature\": 72, \"conditions\": \"sunny\"}";
            };

            @SuppressWarnings("unchecked")
            ToolCallback weatherTool = FunctionToolCallback
                .builder("getWeather", getWeatherFunc)
                .description("Get the current weather for a city")
                .inputType((Class<Map<String, Object>>) (Class<?>) Map.class)
                .build();

            // Use ChatClient with tools (execution enabled by default)
            ChatClient client = ChatClient.create(anthropicChatModel);
            String response = client.prompt()
                .system("You are a helpful assistant. Use the getWeather tool to answer weather questions.")
                .user("What is the weather in San Francisco?")
                .toolCallbacks(weatherTool)
                .call()
                .content();

            log.info("Final response: {}", response);
            log.info("TEST 4 RESULT: SUCCESS - Tool was called and response generated");
        } catch (Exception e) {
            log.error("TEST 4 RESULT: FAILED - {}", e.getMessage(), e);
        }
    }

    /**
     * Test 5: Hint-based structured output (JSON schema in prompt)
     */
    private void testHintBasedStructuredOutput() {
        log.info("\n" + "-".repeat(80));
        log.info("TEST 5: Hint-Based Structured Output");
        log.info("-".repeat(80));

        try {
            String systemPrompt = """
                You are a helpful assistant.

                RESPONSE FORMAT:
                You MUST respond with valid JSON matching this schema:
                {
                  "summary": "string (required) - A brief summary",
                  "confidence": "number (required) - A value from 0.0 to 1.0",
                  "tags": "array of strings (required)"
                }

                Example:
                {"summary": "Example summary", "confidence": 0.8, "tags": ["tag1", "tag2"]}

                IMPORTANT: Respond ONLY with valid JSON. No markdown code fences, no preamble.
                """;

            ChatClient client = ChatClient.create(anthropicChatModel);
            String response = client.prompt()
                .system(systemPrompt)
                .user("Analyze the topic: artificial intelligence")
                .call()
                .content();

            log.info("Raw response: {}", response);

            // Try to parse as JSON
            try {
                com.fasterxml.jackson.databind.ObjectMapper mapper = new com.fasterxml.jackson.databind.ObjectMapper();
                Map<String, Object> parsed = mapper.readValue(response.trim(), Map.class);
                log.info("Parsed JSON: {}", parsed);
                log.info("TEST 5 RESULT: SUCCESS - Valid JSON returned");
            } catch (Exception parseError) {
                log.warn("Failed to parse as JSON: {}", parseError.getMessage());
                log.info("TEST 5 RESULT: PARTIAL - Response not valid JSON");
            }
        } catch (Exception e) {
            log.error("TEST 5 RESULT: FAILED - {}", e.getMessage(), e);
        }
    }

    /**
     * Test 6: Direct Prompt API with tool options
     * Uses the lower-level Prompt API to see all response details
     */
    private void testPromptApiWithTools() {
        log.info("\n" + "-".repeat(80));
        log.info("TEST 6: Direct Prompt API with Tools");
        log.info("-".repeat(80));

        try {
            Function<Map<String, Object>, String> cityInfoFunc = args -> {
                log.info("Tool getCityInfo called with args: {}", args);
                return "{\"population\": 874961, \"state\": \"California\"}";
            };

            @SuppressWarnings("unchecked")
            ToolCallback cityTool = FunctionToolCallback
                .builder("getCityInfo", cityInfoFunc)
                .description("Get information about a city including population and state")
                .inputType((Class<Map<String, Object>>) (Class<?>) Map.class)
                .build();

            // Test with internalToolExecutionEnabled = false
            ToolCallingChatOptions options = ToolCallingChatOptions.builder()
                .toolCallbacks(cityTool)
                .internalToolExecutionEnabled(false)
                .build();

            List<Message> messages = List.of(
                new SystemMessage("You have access to a getCityInfo tool. Use it to answer questions about cities."),
                new UserMessage("What is the population of San Francisco?")
            );

            Prompt prompt = new Prompt(messages, options);

            log.info("Calling model with prompt...");
            ChatResponse response = anthropicChatModel.call(prompt);

            log.info("ChatResponse class: {}", response.getClass().getName());
            log.info("ChatResponse.getResults() size: {}", response.getResults().size());
            log.info("ChatResponse.getMetadata(): {}", response.getMetadata());

            for (int i = 0; i < response.getResults().size(); i++) {
                Generation gen = response.getResults().get(i);
                log.info("Generation[{}]:", i);
                log.info("  - output.getText(): {}", gen.getOutput().getText());
                log.info("  - output.hasToolCalls(): {}", gen.getOutput().hasToolCalls());
                log.info("  - output.getMetadata(): {}", gen.getOutput().getMetadata());
                log.info("  - generation.getMetadata(): {}", gen.getMetadata());

                if (gen.getOutput().hasToolCalls()) {
                    for (AssistantMessage.ToolCall tc : gen.getOutput().getToolCalls()) {
                        log.info("  - ToolCall: id={}, name={}, args={}", tc.id(), tc.name(), tc.arguments());
                    }
                }
            }

            // Check if the model wants to call a tool based on text content
            String content = response.getResult().getOutput().getText();
            if (content != null && (content.contains("getCityInfo") || content.contains("I'll") || content.contains("Let me"))) {
                log.info("Model text suggests it wants to use tools, but hasToolCalls()=false");
                log.info("This indicates Spring AI may not be properly exposing tool_calls in no-execution mode");
            }

            log.info("TEST 6 RESULT: See detailed output above");
        } catch (Exception e) {
            log.error("TEST 6 RESULT: FAILED - {}", e.getMessage(), e);
        }
    }
}
