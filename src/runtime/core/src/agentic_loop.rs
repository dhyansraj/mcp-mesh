//! LLM agentic loop state machine.
//!
//! Manages the message history, iteration counting, token accumulation,
//! and tool call detection for the LLM agentic loop. SDKs control the
//! event loop and call these functions between LLM invocations.
//!
//! # Architecture
//!
//! ```text
//! SDK                                    Rust
//!  |                                       |
//!  |  create_loop(config) --------------> state + "call_llm" action
//!  |                                       |
//!  |  SDK calls LLM with state.messages    |
//!  |                                       |
//!  |  process_response(state, resp) -----> "execute_tools" + tool_calls
//!  |                                    OR "done" + content
//!  |                                    OR "max_iterations"
//!  |  SDK executes tools                   |
//!  |                                       |
//!  |  add_tool_results(state, results) --> "call_llm" + updated state
//!  |                                       |
//!  |  SDK calls LLM again...              |
//!  |  ...repeats until "done"              |
//! ```

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Serialize, Deserialize)]
struct LoopState {
    messages: Vec<Value>,
    iteration: u32,
    max_iterations: u32,
    total_input_tokens: u64,
    total_output_tokens: u64,
}

/// Create initial loop state and return the first action.
///
/// Input config must contain `messages` (array) and optionally `max_iterations` (default 10).
///
/// Returns a JSON string with `{"action": "call_llm", "messages": [...], "state": "..."}`.
pub fn create_loop(config_json: &str) -> Result<String, String> {
    let config: Value = serde_json::from_str(config_json)
        .map_err(|e| format!("Invalid config JSON: {}", e))?;

    let messages = config.get("messages")
        .and_then(|m| m.as_array())
        .ok_or("config.messages must be an array")?
        .clone();

    let max_iterations = config.get("max_iterations")
        .and_then(|m| m.as_u64())
        .unwrap_or(10) as u32;

    if max_iterations == 0 {
        return Err("max_iterations must be greater than 0".to_string());
    }

    let state = LoopState {
        messages,
        iteration: 0,
        max_iterations,
        total_input_tokens: 0,
        total_output_tokens: 0,
    };

    let state_json = serde_json::to_string(&state)
        .map_err(|e| format!("Failed to serialize state: {}", e))?;

    let action = serde_json::json!({
        "action": "call_llm",
        "messages": state.messages,
        "state": state_json,
    });

    serde_json::to_string(&action)
        .map_err(|e| format!("Failed to serialize action: {}", e))
}

/// Process an LLM response and decide the next action.
///
/// Examines the response for tool calls. If present, returns `execute_tools`;
/// if absent, returns `done`. Checks iteration limits before allowing further
/// tool execution.
pub fn process_response(state_json: &str, llm_response_json: &str) -> Result<String, String> {
    let mut state: LoopState = serde_json::from_str(state_json)
        .map_err(|e| format!("Invalid state JSON: {}", e))?;

    let response: Value = serde_json::from_str(llm_response_json)
        .map_err(|e| format!("Invalid response JSON: {}", e))?;

    state.iteration += 1;

    if let Some(usage) = response.get("usage") {
        state.total_input_tokens += usage.get("prompt_tokens")
            .and_then(|t| t.as_u64()).unwrap_or(0);
        state.total_output_tokens += usage.get("completion_tokens")
            .and_then(|t| t.as_u64()).unwrap_or(0);
    }

    let content = response.get("content")
        .and_then(|c| c.as_str())
        .unwrap_or("");

    let tool_calls = response.get("tool_calls")
        .and_then(|tc| tc.as_array())
        .filter(|tc| !tc.is_empty());

    if let Some(calls) = tool_calls {
        if state.iteration >= state.max_iterations {
            let state_str = serde_json::to_string(&state)
                .map_err(|e| format!("Failed to serialize state: {}", e))?;
            let action = serde_json::json!({
                "action": "max_iterations",
                "iteration": state.iteration,
                "max_iterations": state.max_iterations,
                "state": state_str,
            });
            return serde_json::to_string(&action)
                .map_err(|e| format!("Failed to serialize action: {}", e));
        }

        let mut assistant_msg = serde_json::json!({
            "role": "assistant",
            "tool_calls": calls,
        });
        if !content.is_empty() {
            assistant_msg["content"] = Value::String(content.to_string());
        } else {
            assistant_msg["content"] = Value::Null;
        }

        state.messages.push(assistant_msg);

        let state_str = serde_json::to_string(&state)
            .map_err(|e| format!("Failed to serialize state: {}", e))?;
        let action = serde_json::json!({
            "action": "execute_tools",
            "tool_calls": calls,
            "state": state_str,
        });
        return serde_json::to_string(&action)
            .map_err(|e| format!("Failed to serialize action: {}", e));
    }

    // No tool calls -- final response
    let state_str = serde_json::to_string(&state)
        .map_err(|e| format!("Failed to serialize state: {}", e))?;
    let action = serde_json::json!({
        "action": "done",
        "content": content,
        "meta": {
            "iteration": state.iteration,
            "total_input_tokens": state.total_input_tokens,
            "total_output_tokens": state.total_output_tokens,
        },
        "state": state_str,
    });
    serde_json::to_string(&action)
        .map_err(|e| format!("Failed to serialize action: {}", e))
}

/// Add tool execution results to the message history and return action to call LLM again.
///
/// Each result becomes a `{"role": "tool", "tool_call_id": "...", "content": "..."}` message.
pub fn add_tool_results(state_json: &str, tool_results_json: &str) -> Result<String, String> {
    let mut state: LoopState = serde_json::from_str(state_json)
        .map_err(|e| format!("Invalid state JSON: {}", e))?;

    let results: Vec<Value> = serde_json::from_str(tool_results_json)
        .map_err(|e| format!("Invalid tool results JSON: {}", e))?;

    if state.iteration >= state.max_iterations {
        let state_str = serde_json::to_string(&state)
            .map_err(|e| format!("Failed to serialize state: {}", e))?;
        let action = serde_json::json!({
            "action": "max_iterations",
            "iteration": state.iteration,
            "max_iterations": state.max_iterations,
            "state": state_str,
        });
        return serde_json::to_string(&action)
            .map_err(|e| format!("Failed to serialize action: {}", e));
    }

    for result in &results {
        let tool_msg = serde_json::json!({
            "role": "tool",
            "tool_call_id": result.get("tool_call_id").and_then(|id| id.as_str()).unwrap_or(""),
            "content": result.get("content").and_then(|c| c.as_str()).unwrap_or(""),
        });
        state.messages.push(tool_msg);
    }

    let state_str = serde_json::to_string(&state)
        .map_err(|e| format!("Failed to serialize state: {}", e))?;
    let action = serde_json::json!({
        "action": "call_llm",
        "messages": state.messages,
        "state": state_str,
    });
    serde_json::to_string(&action)
        .map_err(|e| format!("Failed to serialize action: {}", e))
}

/// Return a read-only view of the current loop state (for debugging/logging).
pub fn get_loop_state(state_json: &str) -> Result<String, String> {
    let state: LoopState = serde_json::from_str(state_json)
        .map_err(|e| format!("Invalid state JSON: {}", e))?;

    let info = serde_json::json!({
        "iteration": state.iteration,
        "max_iterations": state.max_iterations,
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "message_count": state.messages.len(),
    });
    serde_json::to_string(&info)
        .map_err(|e| format!("Failed to serialize state info: {}", e))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // =========================================================================
    // create_loop tests
    // =========================================================================

    #[test]
    fn test_create_loop_valid_config() {
        let config = json!({
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello"}
            ],
            "max_iterations": 5
        });

        let result = create_loop(&config.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "call_llm");
        assert_eq!(action["messages"].as_array().unwrap().len(), 2);
        assert_eq!(action["messages"][0]["role"], "system");
        assert_eq!(action["messages"][1]["role"], "user");

        // State should be a valid JSON string
        let state: LoopState = serde_json::from_str(action["state"].as_str().unwrap()).unwrap();
        assert_eq!(state.iteration, 0);
        assert_eq!(state.max_iterations, 5);
        assert_eq!(state.total_input_tokens, 0);
        assert_eq!(state.total_output_tokens, 0);
        assert_eq!(state.messages.len(), 2);
    }

    #[test]
    fn test_create_loop_missing_messages() {
        let config = json!({"max_iterations": 5});
        let result = create_loop(&config.to_string());
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("messages must be an array"));
    }

    #[test]
    fn test_create_loop_default_max_iterations() {
        let config = json!({
            "messages": [{"role": "user", "content": "Hi"}]
        });

        let result = create_loop(&config.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();
        let state: LoopState = serde_json::from_str(action["state"].as_str().unwrap()).unwrap();
        assert_eq!(state.max_iterations, 10);
    }

    #[test]
    fn test_create_loop_custom_max_iterations() {
        let config = json!({
            "messages": [{"role": "user", "content": "Hi"}],
            "max_iterations": 20
        });

        let result = create_loop(&config.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();
        let state: LoopState = serde_json::from_str(action["state"].as_str().unwrap()).unwrap();
        assert_eq!(state.max_iterations, 20);
    }

    #[test]
    fn test_create_loop_zero_max_iterations() {
        let config = json!({
            "messages": [{"role": "user", "content": "Hi"}],
            "max_iterations": 0
        });
        let result = create_loop(&config.to_string());
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("max_iterations must be greater than 0"));
    }

    #[test]
    fn test_create_loop_invalid_json() {
        let result = create_loop("not valid json");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid config JSON"));
    }

    // =========================================================================
    // process_response -- tool calls
    // =========================================================================

    #[test]
    fn test_process_response_with_tool_calls() {
        let config = json!({
            "messages": [{"role": "user", "content": "What is the weather?"}],
            "max_iterations": 10
        });
        let create_result = create_loop(&config.to_string()).unwrap();
        let create_action: Value = serde_json::from_str(&create_result).unwrap();
        let state_str = create_action["state"].as_str().unwrap();

        let llm_response = json!({
            "content": null,
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": "{\"location\": \"NYC\"}"
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 25
            }
        });

        let result = process_response(state_str, &llm_response.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "execute_tools");
        let tool_calls = action["tool_calls"].as_array().unwrap();
        assert_eq!(tool_calls.len(), 1);
        assert_eq!(tool_calls[0]["function"]["name"], "get_weather");

        // Verify state updated
        let state: LoopState = serde_json::from_str(action["state"].as_str().unwrap()).unwrap();
        assert_eq!(state.iteration, 1);
        assert_eq!(state.total_input_tokens, 100);
        assert_eq!(state.total_output_tokens, 25);
        // Assistant message with tool_calls should be added
        assert_eq!(state.messages.len(), 2); // original user + assistant
        assert_eq!(state.messages[1]["role"], "assistant");
        assert!(state.messages[1]["tool_calls"].is_array());
    }

    #[test]
    fn test_process_response_tool_calls_with_content() {
        let state = LoopState {
            messages: vec![json!({"role": "user", "content": "Calc 2+2"})],
            iteration: 0,
            max_iterations: 10,
            total_input_tokens: 0,
            total_output_tokens: 0,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let llm_response = json!({
            "content": "Let me calculate that for you.",
            "tool_calls": [
                {
                    "id": "call_xyz",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": "{\"expr\": \"2+2\"}"}
                }
            ]
        });

        let result = process_response(&state_str, &llm_response.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "execute_tools");

        let new_state: LoopState = serde_json::from_str(action["state"].as_str().unwrap()).unwrap();
        let assistant_msg = &new_state.messages[1];
        assert_eq!(assistant_msg["content"], "Let me calculate that for you.");
        assert!(assistant_msg["tool_calls"].is_array());
    }

    #[test]
    fn test_process_response_token_accumulation() {
        let state = LoopState {
            messages: vec![json!({"role": "user", "content": "Hi"})],
            iteration: 2,
            max_iterations: 10,
            total_input_tokens: 200,
            total_output_tokens: 50,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let llm_response = json!({
            "content": "Done!",
            "usage": {"prompt_tokens": 300, "completion_tokens": 75}
        });

        let result = process_response(&state_str, &llm_response.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "done");
        let meta = &action["meta"];
        assert_eq!(meta["total_input_tokens"], 500);
        assert_eq!(meta["total_output_tokens"], 125);
        assert_eq!(meta["iteration"], 3);
    }

    // =========================================================================
    // process_response -- final response
    // =========================================================================

    #[test]
    fn test_process_response_done_no_tool_calls() {
        let state = LoopState {
            messages: vec![json!({"role": "user", "content": "Hello"})],
            iteration: 0,
            max_iterations: 10,
            total_input_tokens: 0,
            total_output_tokens: 0,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let llm_response = json!({
            "content": "Hi there! How can I help?",
            "usage": {"prompt_tokens": 10, "completion_tokens": 8}
        });

        let result = process_response(&state_str, &llm_response.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "done");
        assert_eq!(action["content"], "Hi there! How can I help?");
        assert_eq!(action["meta"]["iteration"], 1);
        assert_eq!(action["meta"]["total_input_tokens"], 10);
        assert_eq!(action["meta"]["total_output_tokens"], 8);
    }

    #[test]
    fn test_process_response_empty_tool_calls_treated_as_done() {
        let state = LoopState {
            messages: vec![json!({"role": "user", "content": "Hello"})],
            iteration: 0,
            max_iterations: 10,
            total_input_tokens: 0,
            total_output_tokens: 0,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let llm_response = json!({
            "content": "Final answer",
            "tool_calls": []
        });

        let result = process_response(&state_str, &llm_response.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "done");
        assert_eq!(action["content"], "Final answer");
    }

    #[test]
    fn test_process_response_no_usage_field() {
        let state = LoopState {
            messages: vec![json!({"role": "user", "content": "Hi"})],
            iteration: 0,
            max_iterations: 10,
            total_input_tokens: 0,
            total_output_tokens: 0,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let llm_response = json!({"content": "Hello!"});

        let result = process_response(&state_str, &llm_response.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "done");
        assert_eq!(action["meta"]["total_input_tokens"], 0);
        assert_eq!(action["meta"]["total_output_tokens"], 0);
    }

    // =========================================================================
    // process_response -- max iterations
    // =========================================================================

    #[test]
    fn test_process_response_max_iterations() {
        let state = LoopState {
            messages: vec![json!({"role": "user", "content": "Loop"})],
            iteration: 4,
            max_iterations: 5,
            total_input_tokens: 0,
            total_output_tokens: 0,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let llm_response = json!({
            "content": null,
            "tool_calls": [
                {"id": "call_999", "type": "function", "function": {"name": "again", "arguments": "{}"}}
            ]
        });

        let result = process_response(&state_str, &llm_response.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "max_iterations");
        assert_eq!(action["iteration"], 5);
        assert_eq!(action["max_iterations"], 5);

        // State should still be valid
        let new_state: LoopState = serde_json::from_str(action["state"].as_str().unwrap()).unwrap();
        assert_eq!(new_state.iteration, 5);
    }

    #[test]
    fn test_process_response_max_iterations_preserves_state() {
        let state = LoopState {
            messages: vec![
                json!({"role": "user", "content": "Go"}),
                json!({"role": "assistant", "content": null, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}}]}),
                json!({"role": "tool", "tool_call_id": "c1", "content": "ok"}),
            ],
            iteration: 9,
            max_iterations: 10,
            total_input_tokens: 500,
            total_output_tokens: 200,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let llm_response = json!({
            "content": null,
            "tool_calls": [{"id": "call_x", "type": "function", "function": {"name": "b", "arguments": "{}"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10}
        });

        let result = process_response(&state_str, &llm_response.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "max_iterations");
        let new_state: LoopState = serde_json::from_str(action["state"].as_str().unwrap()).unwrap();
        assert_eq!(new_state.total_input_tokens, 550);
        assert_eq!(new_state.total_output_tokens, 210);
        assert_eq!(new_state.messages.len(), 3); // assistant msg NOT added on max_iterations
    }

    // =========================================================================
    // add_tool_results
    // =========================================================================

    #[test]
    fn test_add_tool_results_single() {
        let state = LoopState {
            messages: vec![
                json!({"role": "user", "content": "Calc"}),
                json!({"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "calc", "arguments": "{}"}}]}),
            ],
            iteration: 1,
            max_iterations: 10,
            total_input_tokens: 100,
            total_output_tokens: 50,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let results = json!([
            {"tool_call_id": "call_1", "content": "{\"result\": 42}"}
        ]);

        let result = add_tool_results(&state_str, &results.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "call_llm");
        let messages = action["messages"].as_array().unwrap();
        assert_eq!(messages.len(), 3); // user + assistant + tool
        assert_eq!(messages[2]["role"], "tool");
        assert_eq!(messages[2]["tool_call_id"], "call_1");
        assert_eq!(messages[2]["content"], "{\"result\": 42}");
    }

    #[test]
    fn test_add_tool_results_multiple() {
        let state = LoopState {
            messages: vec![
                json!({"role": "user", "content": "Do stuff"}),
                json!({"role": "assistant", "content": null, "tool_calls": [
                    {"id": "call_a", "type": "function", "function": {"name": "foo", "arguments": "{}"}},
                    {"id": "call_b", "type": "function", "function": {"name": "bar", "arguments": "{}"}}
                ]}),
            ],
            iteration: 1,
            max_iterations: 10,
            total_input_tokens: 0,
            total_output_tokens: 0,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let results = json!([
            {"tool_call_id": "call_a", "content": "result_a"},
            {"tool_call_id": "call_b", "content": "result_b"}
        ]);

        let result = add_tool_results(&state_str, &results.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "call_llm");
        let messages = action["messages"].as_array().unwrap();
        assert_eq!(messages.len(), 4); // user + assistant + 2 tool
        assert_eq!(messages[2]["tool_call_id"], "call_a");
        assert_eq!(messages[3]["tool_call_id"], "call_b");
    }

    #[test]
    fn test_add_tool_results_max_iterations_check() {
        let state = LoopState {
            messages: vec![json!({"role": "user", "content": "Loop"})],
            iteration: 5,
            max_iterations: 5,
            total_input_tokens: 0,
            total_output_tokens: 0,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let results = json!([{"tool_call_id": "call_1", "content": "ok"}]);

        let result = add_tool_results(&state_str, &results.to_string()).unwrap();
        let action: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(action["action"], "max_iterations");
        assert_eq!(action["iteration"], 5);
        assert_eq!(action["max_iterations"], 5);
    }

    // =========================================================================
    // Full loop simulation
    // =========================================================================

    #[test]
    fn test_full_loop_create_tool_call_result_done() {
        // Step 1: Create loop
        let config = json!({
            "messages": [
                {"role": "system", "content": "You are a calculator."},
                {"role": "user", "content": "What is 2 + 2?"}
            ],
            "max_iterations": 10
        });

        let create_result = create_loop(&config.to_string()).unwrap();
        let create_action: Value = serde_json::from_str(&create_result).unwrap();
        assert_eq!(create_action["action"], "call_llm");
        let state1 = create_action["state"].as_str().unwrap();

        // Step 2: LLM responds with tool call
        let llm_response1 = json!({
            "content": null,
            "tool_calls": [
                {
                    "id": "call_calc",
                    "type": "function",
                    "function": {"name": "add", "arguments": "{\"a\": 2, \"b\": 2}"}
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20}
        });

        let process_result1 = process_response(state1, &llm_response1.to_string()).unwrap();
        let process_action1: Value = serde_json::from_str(&process_result1).unwrap();
        assert_eq!(process_action1["action"], "execute_tools");
        assert_eq!(process_action1["tool_calls"].as_array().unwrap().len(), 1);
        let state2 = process_action1["state"].as_str().unwrap();

        // Step 3: SDK executes tool, adds results
        let tool_results = json!([
            {"tool_call_id": "call_calc", "content": "4"}
        ]);

        let add_result = add_tool_results(state2, &tool_results.to_string()).unwrap();
        let add_action: Value = serde_json::from_str(&add_result).unwrap();
        assert_eq!(add_action["action"], "call_llm");
        let messages = add_action["messages"].as_array().unwrap();
        // system + user + assistant(with tool_calls) + tool result = 4
        assert_eq!(messages.len(), 4);
        let state3 = add_action["state"].as_str().unwrap();

        // Step 4: LLM responds with final answer (no tool calls)
        let llm_response2 = json!({
            "content": "2 + 2 = 4",
            "usage": {"prompt_tokens": 80, "completion_tokens": 10}
        });

        let process_result2 = process_response(state3, &llm_response2.to_string()).unwrap();
        let process_action2: Value = serde_json::from_str(&process_result2).unwrap();
        assert_eq!(process_action2["action"], "done");
        assert_eq!(process_action2["content"], "2 + 2 = 4");
        assert_eq!(process_action2["meta"]["iteration"], 2);
        assert_eq!(process_action2["meta"]["total_input_tokens"], 130); // 50 + 80
        assert_eq!(process_action2["meta"]["total_output_tokens"], 30); // 20 + 10
    }

    #[test]
    fn test_full_loop_multi_iteration() {
        let config = json!({
            "messages": [{"role": "user", "content": "Research and summarize"}],
            "max_iterations": 10
        });

        let create_result = create_loop(&config.to_string()).unwrap();
        let mut action: Value = serde_json::from_str(&create_result).unwrap();
        assert_eq!(action["action"], "call_llm");

        // Iteration 1: tool call
        let resp1 = json!({
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{\"q\": \"rust\"}"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}
        });
        action = serde_json::from_str(
            &process_response(action["state"].as_str().unwrap(), &resp1.to_string()).unwrap()
        ).unwrap();
        assert_eq!(action["action"], "execute_tools");

        // Tool result 1
        let results1 = json!([{"tool_call_id": "c1", "content": "Rust is a language"}]);
        action = serde_json::from_str(
            &add_tool_results(action["state"].as_str().unwrap(), &results1.to_string()).unwrap()
        ).unwrap();
        assert_eq!(action["action"], "call_llm");

        // Iteration 2: another tool call
        let resp2 = json!({
            "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "summarize", "arguments": "{}"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10}
        });
        action = serde_json::from_str(
            &process_response(action["state"].as_str().unwrap(), &resp2.to_string()).unwrap()
        ).unwrap();
        assert_eq!(action["action"], "execute_tools");

        // Tool result 2
        let results2 = json!([{"tool_call_id": "c2", "content": "Summary: Rust is fast"}]);
        action = serde_json::from_str(
            &add_tool_results(action["state"].as_str().unwrap(), &results2.to_string()).unwrap()
        ).unwrap();
        assert_eq!(action["action"], "call_llm");

        // Iteration 3: final answer
        let resp3 = json!({
            "content": "Here is the summary: Rust is a fast systems language.",
            "usage": {"prompt_tokens": 30, "completion_tokens": 15}
        });
        action = serde_json::from_str(
            &process_response(action["state"].as_str().unwrap(), &resp3.to_string()).unwrap()
        ).unwrap();
        assert_eq!(action["action"], "done");
        assert_eq!(action["meta"]["iteration"], 3);
        assert_eq!(action["meta"]["total_input_tokens"], 60);
        assert_eq!(action["meta"]["total_output_tokens"], 30);

        // Verify messages grew correctly
        let final_state: LoopState = serde_json::from_str(action["state"].as_str().unwrap()).unwrap();
        // user + assistant1 + tool1 + assistant2 + tool2 = 5
        assert_eq!(final_state.messages.len(), 5);
    }

    // =========================================================================
    // get_loop_state
    // =========================================================================

    #[test]
    fn test_get_loop_state() {
        let state = LoopState {
            messages: vec![
                json!({"role": "system", "content": "sys"}),
                json!({"role": "user", "content": "hello"}),
                json!({"role": "assistant", "content": "hi"}),
            ],
            iteration: 3,
            max_iterations: 10,
            total_input_tokens: 450,
            total_output_tokens: 150,
        };
        let state_str = serde_json::to_string(&state).unwrap();

        let result = get_loop_state(&state_str).unwrap();
        let info: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(info["iteration"], 3);
        assert_eq!(info["max_iterations"], 10);
        assert_eq!(info["total_input_tokens"], 450);
        assert_eq!(info["total_output_tokens"], 150);
        assert_eq!(info["message_count"], 3);
    }

    #[test]
    fn test_get_loop_state_invalid_json() {
        let result = get_loop_state("bad json");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid state JSON"));
    }
}
