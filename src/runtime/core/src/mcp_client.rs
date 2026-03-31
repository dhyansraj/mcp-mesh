//! MCP JSON-RPC client for inter-agent communication.
//!
//! Provides protocol-level utilities and an HTTP client for calling remote
//! MCP agents. Previously duplicated across Python, TypeScript, and Java SDKs.

use serde_json::Value;
use std::collections::HashMap;
use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

static HTTP_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();

fn get_http_client() -> &'static reqwest::Client {
    HTTP_CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .pool_max_idle_per_host(20)
            .pool_idle_timeout(Duration::from_secs(90))
            .connect_timeout(Duration::from_secs(30))
            .build()
            .expect("Failed to build HTTP client")
    })
}

/// Build a JSON-RPC 2.0 request envelope.
///
/// # Arguments
/// * `method` - JSON-RPC method name (e.g., "tools/call")
/// * `params_json` - JSON string to parse and embed as the params object
/// * `request_id` - Unique request identifier
///
/// # Returns
/// The full JSON-RPC request as a string.
pub fn build_jsonrpc_request(method: &str, params_json: &str, request_id: &str) -> Result<String, String> {
    let params: Value = serde_json::from_str(params_json)
        .map_err(|e| format!("Invalid params JSON: {}", e))?;

    let request = serde_json::json!({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    });

    serde_json::to_string(&request)
        .map_err(|e| format!("Failed to serialize request: {}", e))
}

/// Generate a unique request ID.
///
/// Format: `req_{unix_millis}_{random_hex_6chars}`
pub fn generate_request_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();

    let uuid = uuid::Uuid::new_v4();
    let hex = format!("{:x}", uuid);
    let random_part = &hex[..6.min(hex.len())];

    format!("req_{}_{}", millis, random_part)
}

/// Parse SSE (Server-Sent Events) or plain JSON response and extract JSON data.
///
/// Logic (matches all three SDKs):
/// 1. Check if it's SSE format (event: at line start, data: after newline)
/// 2. If NOT SSE: try parsing as plain JSON, return as-is if valid
/// 3. If SSE: scan lines for `data:` prefix, try JSON parse on each, return first valid
/// 4. If no valid JSON found: return error
pub fn parse_sse_response(response_text: &str) -> Result<String, String> {
    // Match Python SSEParser behavior: check SSE markers at line beginnings only
    // to avoid false positives from JSON values containing these strings
    let is_sse = response_text.starts_with("event:")
        || response_text.starts_with("data:")
        || response_text.contains("\nevent:")
        || response_text.contains("\ndata:");

    if !is_sse {
        // Try parsing as plain JSON
        let _: Value = serde_json::from_str(response_text)
            .map_err(|e| format!("Invalid JSON response: {}", e))?;
        return Ok(response_text.to_string());
    }

    // SSE format: scan lines for data: prefix
    for line in response_text.lines() {
        let data = if let Some(stripped) = line.strip_prefix("data: ") {
            stripped
        } else if let Some(stripped) = line.strip_prefix("data:") {
            stripped
        } else {
            continue;
        };

        let trimmed = data.trim();
        if trimmed.is_empty() {
            continue;
        }

        if serde_json::from_str::<Value>(trimmed).is_ok() {
            return Ok(trimmed.to_string());
        }
    }

    Err("No valid JSON found in SSE response".to_string())
}

/// Extract text content from an MCP `CallToolResult` JSON response.
///
/// The MCP protocol returns results in various formats. This function
/// normalizes them to a string:
///
/// 1. If it's a string: return directly
/// 2. If object with `content` array of all-text items: join text values
/// 3. If object with mixed content (resource_link, image, etc.): return full JSON
/// 4. If object with `content` as string: return that string
/// 5. Otherwise: JSON stringify
pub fn extract_content(result_json: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(result_json)
        .map_err(|e| format!("Invalid JSON: {}", e))?;

    match &value {
        Value::String(s) => Ok(s.clone()),
        Value::Object(obj) => {
            if let Some(content) = obj.get("content") {
                match content {
                    Value::Array(items) => {
                        let all_text = items.iter().all(|item| {
                            match item {
                                Value::String(_) => true,
                                Value::Object(m) => m.get("type")
                                    .and_then(|t| t.as_str()) == Some("text"),
                                _ => false,
                            }
                        });

                        if all_text {
                            let parts: Vec<&str> = items.iter().filter_map(|item| {
                                match item {
                                    Value::String(s) => Some(s.as_str()),
                                    Value::Object(m) => m.get("text")
                                        .and_then(|t| t.as_str()),
                                    _ => None,
                                }
                            }).collect();
                            Ok(parts.join(""))
                        } else {
                            // Mixed content - return full JSON
                            Ok(result_json.to_string())
                        }
                    }
                    Value::String(s) => Ok(s.clone()),
                    _ => Ok(serde_json::to_string(&value).unwrap_or_default()),
                }
            } else {
                Ok(serde_json::to_string(&value).unwrap_or_default())
            }
        }
        _ => Ok(serde_json::to_string(&value).unwrap_or_default()),
    }
}

/// Call a remote MCP tool via HTTP POST with retry logic.
///
/// Sends a JSON-RPC 2.0 `tools/call` request to the given endpoint,
/// handling SSE responses, JSON-RPC errors, and network retries with
/// exponential backoff.
pub async fn call_tool(
    endpoint: &str,
    tool_name: &str,
    args_json: Option<&str>,
    headers_json: Option<&str>,
    timeout_ms: u64,
    max_retries: u32,
) -> Result<String, String> {
    let url = if endpoint.ends_with("/mcp") {
        endpoint.to_string()
    } else {
        format!("{}/mcp", endpoint.trim_end_matches('/'))
    };

    // Build args
    let args: Value = match args_json {
        Some(s) => serde_json::from_str(s).map_err(|e| format!("Invalid args JSON: {}", e))?,
        None => serde_json::json!({}),
    };

    // Build params
    let params = serde_json::json!({
        "name": tool_name,
        "arguments": args,
    });

    let request_id = generate_request_id();
    let payload = serde_json::json!({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": params,
    });

    // Parse extra headers
    let extra_headers: HashMap<String, String> = match headers_json {
        Some(s) if !s.is_empty() => serde_json::from_str(s).unwrap_or_default(),
        _ => HashMap::new(),
    };

    let client = get_http_client();

    let mut last_error = String::new();

    for attempt in 0..=max_retries {
        let mut request = client
            .post(&url)
            .timeout(Duration::from_millis(timeout_ms))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream");

        for (key, value) in &extra_headers {
            request = request.header(key.as_str(), value.as_str());
        }

        match request.body(payload.to_string()).send().await {
            Ok(response) => {
                let status = response.status();
                if !status.is_success() {
                    last_error = format!(
                        "MCP call failed: {} {}",
                        status.as_u16(),
                        status.canonical_reason().unwrap_or("")
                    );
                    if attempt < max_retries {
                        tokio::time::sleep(Duration::from_millis(100 * (attempt as u64 + 1))).await;
                        continue;
                    }
                    return Err(last_error);
                }

                let response_text = response.text().await
                    .map_err(|e| format!("Failed to read response: {}", e))?;

                // Parse response (SSE or JSON)
                let parsed = parse_sse_response(&response_text)?;

                // Check for JSON-RPC error
                let json_value: Value = serde_json::from_str(&parsed)
                    .map_err(|e| format!("Invalid JSON-RPC response: {}", e))?;

                if let Some(error) = json_value.get("error") {
                    let msg = error.get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("Unknown error");
                    return Err(format!("MCP error: {}", msg));
                }

                // Extract result
                if let Some(result) = json_value.get("result") {
                    let result_str = serde_json::to_string(result)
                        .map_err(|e| format!("Failed to serialize result: {}", e))?;
                    return extract_content(&result_str);
                }

                return Ok(parsed);
            }
            Err(e) => {
                if e.is_timeout() {
                    return Err(format!("MCP call timed out after {}ms", timeout_ms));
                }
                last_error = format!("Network error: {}", e);
                if attempt < max_retries {
                    tokio::time::sleep(Duration::from_millis(100 * (attempt as u64 + 1))).await;
                    continue;
                }
            }
        }
    }

    Err(last_error)
}

#[cfg(test)]
mod tests {
    use super::*;

    // =========================================================================
    // build_jsonrpc_request
    // =========================================================================

    #[test]
    fn test_build_jsonrpc_request_valid() {
        let result = build_jsonrpc_request("tools/call", r#"{"name":"greet"}"#, "req_123").unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(parsed["jsonrpc"], "2.0");
        assert_eq!(parsed["id"], "req_123");
        assert_eq!(parsed["method"], "tools/call");
        assert_eq!(parsed["params"]["name"], "greet");
    }

    #[test]
    fn test_build_jsonrpc_request_empty_params() {
        let result = build_jsonrpc_request("tools/list", "{}", "id_1").unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(parsed["method"], "tools/list");
        assert!(parsed["params"].is_object());
        assert_eq!(parsed["params"].as_object().unwrap().len(), 0);
    }

    #[test]
    fn test_build_jsonrpc_request_complex_params() {
        let params = r#"{"name":"calc","arguments":{"a":1,"b":2,"op":"add"}}"#;
        let result = build_jsonrpc_request("tools/call", params, "req_456").unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(parsed["params"]["arguments"]["a"], 1);
        assert_eq!(parsed["params"]["arguments"]["op"], "add");
    }

    #[test]
    fn test_build_jsonrpc_request_invalid_params() {
        let result = build_jsonrpc_request("tools/call", "not json", "id_1");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid params JSON"));
    }

    // =========================================================================
    // generate_request_id
    // =========================================================================

    #[test]
    fn test_generate_request_id_format() {
        let id = generate_request_id();
        assert!(id.starts_with("req_"));
        let parts: Vec<&str> = id.splitn(3, '_').collect();
        assert_eq!(parts.len(), 3);
        // Second part should be numeric (millis)
        assert!(parts[1].parse::<u128>().is_ok());
        // Third part should be 6 hex chars
        assert_eq!(parts[2].len(), 6);
        assert!(parts[2].chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn test_generate_request_id_unique() {
        let id1 = generate_request_id();
        let id2 = generate_request_id();
        assert_ne!(id1, id2);
    }

    // =========================================================================
    // parse_sse_response
    // =========================================================================

    #[test]
    fn test_parse_sse_plain_json() {
        let json = r#"{"jsonrpc":"2.0","id":"1","result":{"content":[{"type":"text","text":"hi"}]}}"#;
        let result = parse_sse_response(json).unwrap();
        assert_eq!(result, json);
    }

    #[test]
    fn test_parse_sse_format() {
        let sse = "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":\"1\",\"result\":{}}\n\n";
        let result = parse_sse_response(sse).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(parsed["jsonrpc"], "2.0");
    }

    #[test]
    fn test_parse_sse_multiple_data_lines() {
        let sse = "event: message\ndata: not json\ndata: {\"ok\":true}\n\n";
        let result = parse_sse_response(sse).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(parsed["ok"], true);
    }

    #[test]
    fn test_parse_sse_no_space_after_data() {
        let sse = "data:{\"result\":42}\n\n";
        let result = parse_sse_response(sse).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(parsed["result"], 42);
    }

    #[test]
    fn test_parse_sse_invalid_json() {
        let result = parse_sse_response("this is not json at all");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid JSON"));
    }

    #[test]
    fn test_parse_sse_no_valid_json_in_data_lines() {
        let sse = "event: message\ndata: not json\ndata: still not json\n\n";
        let result = parse_sse_response(sse);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("No valid JSON"));
    }

    // =========================================================================
    // extract_content
    // =========================================================================

    #[test]
    fn test_extract_content_string_value() {
        let result = extract_content(r#""hello world""#).unwrap();
        assert_eq!(result, "hello world");
    }

    #[test]
    fn test_extract_content_text_array() {
        let json = r#"{"content":[{"type":"text","text":"Hello "},{"type":"text","text":"world"}]}"#;
        let result = extract_content(json).unwrap();
        assert_eq!(result, "Hello world");
    }

    #[test]
    fn test_extract_content_string_content() {
        let json = r#"{"content":"direct string"}"#;
        let result = extract_content(json).unwrap();
        assert_eq!(result, "direct string");
    }

    #[test]
    fn test_extract_content_mixed_content() {
        let json = r#"{"content":[{"type":"text","text":"hi"},{"type":"resource_link","uri":"file:///x"}]}"#;
        let result = extract_content(json).unwrap();
        // Mixed content returns full JSON as-is
        assert_eq!(result, json);
    }

    #[test]
    fn test_extract_content_no_content_field() {
        let json = r#"{"status":"ok","count":42}"#;
        let result = extract_content(json).unwrap();
        // Should be JSON stringified
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(parsed["status"], "ok");
        assert_eq!(parsed["count"], 42);
    }

    #[test]
    fn test_extract_content_bare_number() {
        let result = extract_content("42").unwrap();
        assert_eq!(result, "42");
    }

    #[test]
    fn test_extract_content_plain_strings_in_array() {
        let json = r#"{"content":["hello","world"]}"#;
        let result = extract_content(json).unwrap();
        assert_eq!(result, "helloworld");
    }

    #[test]
    fn test_extract_content_invalid_json() {
        let result = extract_content("not json");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid JSON"));
    }

    #[test]
    fn test_extract_content_single_text_item() {
        let json = r#"{"content":[{"type":"text","text":"only one"}]}"#;
        let result = extract_content(json).unwrap();
        assert_eq!(result, "only one");
    }

    #[test]
    fn test_extract_content_empty_array() {
        let json = r#"{"content":[]}"#;
        let result = extract_content(json).unwrap();
        assert_eq!(result, "");
    }

    // =========================================================================
    // get_http_client (connection pool singleton)
    // =========================================================================

    #[test]
    fn test_get_http_client_returns_same_instance() {
        let a = get_http_client() as *const reqwest::Client;
        let b = get_http_client() as *const reqwest::Client;
        assert_eq!(a, b, "get_http_client() must return the same static instance");
    }
}
