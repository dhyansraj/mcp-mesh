//! Trace context utilities for distributed tracing.
//!
//! Handles trace context injection, extraction, and header propagation
//! for inter-agent communication. Previously duplicated across all SDKs.

use serde_json::Value;
use uuid::Uuid;

/// Generate OpenTelemetry-compliant trace ID (32-char hex, 128-bit).
pub fn generate_trace_id() -> String {
    Uuid::new_v4().to_string().replace('-', "")
}

/// Generate OpenTelemetry-compliant span ID (16-char hex, 64-bit).
pub fn generate_span_id() -> String {
    Uuid::new_v4().to_string().replace('-', "")[..16].to_string()
}

/// Inject trace context into JSON-RPC arguments.
pub fn inject_trace_context(
    args_json: &str,
    trace_id: &str,
    span_id: &str,
    propagated_headers_json: Option<&str>,
) -> Result<String, String> {
    let mut args: Value =
        serde_json::from_str(args_json).map_err(|e| format!("Failed to parse args_json: {}", e))?;

    let obj = args
        .as_object_mut()
        .ok_or_else(|| "args_json must be a JSON object".to_string())?;

    obj.insert("_trace_id".to_string(), Value::String(trace_id.to_string()));
    obj.insert(
        "_parent_span".to_string(),
        Value::String(span_id.to_string()),
    );

    if let Some(headers_str) = propagated_headers_json {
        if !headers_str.is_empty() {
            let headers: Value = serde_json::from_str(headers_str)
                .map_err(|e| format!("Failed to parse propagated_headers_json: {}", e))?;
            obj.insert("_mesh_headers".to_string(), headers);
        }
    }

    serde_json::to_string(&args).map_err(|e| format!("Failed to serialize result: {}", e))
}

/// Extract trace context from HTTP headers with body fallback.
pub fn extract_trace_context(headers_json: &str, body_json: Option<&str>) -> String {
    let mut trace_id = Value::Null;
    let mut parent_span = Value::Null;

    // Strategy 1: HTTP headers (case-insensitive)
    if let Ok(headers) = serde_json::from_str::<Value>(headers_json) {
        if let Some(obj) = headers.as_object() {
            for (key, value) in obj {
                let lower = key.to_lowercase();
                if lower == "x-trace-id" {
                    trace_id = value.clone();
                } else if lower == "x-parent-span" {
                    parent_span = value.clone();
                }
            }
        }
    }

    // Strategy 2: Fallback to body if trace_id or parent_span still missing
    if trace_id.is_null() || parent_span.is_null() {
        if let Some(body_str) = body_json {
            if let Ok(body) = serde_json::from_str::<Value>(body_str) {
                if body.get("method").and_then(|m| m.as_str()) == Some("tools/call") {
                    if let Some(args) = body
                        .get("params")
                        .and_then(|p| p.get("arguments"))
                    {
                        if trace_id.is_null() {
                            if let Some(tid) = args.get("_trace_id") {
                                trace_id = tid.clone();
                            }
                        }
                        if parent_span.is_null() {
                            if let Some(ps) = args.get("_parent_span") {
                                parent_span = ps.clone();
                            }
                        }
                    }
                }
            }
        }
    }

    serde_json::json!({
        "trace_id": trace_id,
        "parent_span": parent_span,
    })
    .to_string()
}

/// Filter headers by propagation allowlist with prefix matching.
pub fn filter_propagation_headers(
    headers_json: &str,
    allowlist_csv: &str,
) -> Result<String, String> {
    let allowlist = parse_allowlist(allowlist_csv);
    let headers: Value = serde_json::from_str(headers_json)
        .map_err(|e| format!("Failed to parse headers_json: {}", e))?;

    let obj = headers
        .as_object()
        .ok_or_else(|| "headers_json must be a JSON object".to_string())?;

    let mut result = serde_json::Map::new();
    for (key, value) in obj {
        let lower_key = key.to_lowercase();
        if allowlist.iter().any(|prefix| lower_key.starts_with(prefix)) {
            result.insert(lower_key, value.clone());
        }
    }

    serde_json::to_string(&Value::Object(result))
        .map_err(|e| format!("Failed to serialize result: {}", e))
}

/// Check if a header matches the propagation allowlist.
pub fn matches_propagate_header(header_name: &str, allowlist_csv: &str) -> bool {
    let allowlist = parse_allowlist(allowlist_csv);
    let lower = header_name.to_lowercase();
    allowlist.iter().any(|prefix| lower.starts_with(prefix))
}

fn parse_allowlist(csv: &str) -> Vec<String> {
    csv.split(',')
        .map(|s| s.trim().to_lowercase())
        .filter(|s| !s.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    // =========================================================================
    // generate_trace_id
    // =========================================================================

    #[test]
    fn test_generate_trace_id_length() {
        let id = generate_trace_id();
        assert_eq!(id.len(), 32);
    }

    #[test]
    fn test_generate_trace_id_hex_chars() {
        let id = generate_trace_id();
        assert!(id.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn test_generate_trace_id_no_dashes() {
        let id = generate_trace_id();
        assert!(!id.contains('-'));
    }

    // =========================================================================
    // generate_span_id
    // =========================================================================

    #[test]
    fn test_generate_span_id_length() {
        let id = generate_span_id();
        assert_eq!(id.len(), 16);
    }

    #[test]
    fn test_generate_span_id_hex_chars() {
        let id = generate_span_id();
        assert!(id.chars().all(|c| c.is_ascii_hexdigit()));
    }

    // =========================================================================
    // inject_trace_context
    // =========================================================================

    #[test]
    fn test_inject_basic() {
        let result = inject_trace_context(
            r#"{"query": "hello"}"#,
            "abc123",
            "def456",
            None,
        )
        .unwrap();
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["query"], "hello");
        assert_eq!(v["_trace_id"], "abc123");
        assert_eq!(v["_parent_span"], "def456");
        assert!(v.get("_mesh_headers").is_none());
    }

    #[test]
    fn test_inject_with_propagated_headers() {
        let result = inject_trace_context(
            r#"{"query": "hello"}"#,
            "abc123",
            "def456",
            Some(r#"{"x-audit-id": "123"}"#),
        )
        .unwrap();
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["_mesh_headers"]["x-audit-id"], "123");
    }

    #[test]
    fn test_inject_empty_args() {
        let result = inject_trace_context("{}", "tid", "sid", None).unwrap();
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["_trace_id"], "tid");
        assert_eq!(v["_parent_span"], "sid");
    }

    #[test]
    fn test_inject_no_propagated_headers() {
        let result = inject_trace_context(r#"{"a":1}"#, "t", "s", Some("")).unwrap();
        let v: Value = serde_json::from_str(&result).unwrap();
        assert!(v.get("_mesh_headers").is_none());
    }

    // =========================================================================
    // extract_trace_context
    // =========================================================================

    #[test]
    fn test_extract_from_headers_case_insensitive() {
        let result = extract_trace_context(
            r#"{"X-Trace-ID": "t1", "x-parent-span": "s1"}"#,
            None,
        );
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["trace_id"], "t1");
        assert_eq!(v["parent_span"], "s1");
    }

    #[test]
    fn test_extract_from_body_fallback() {
        let body = r#"{"method":"tools/call","params":{"arguments":{"_trace_id":"bt","_parent_span":"bs"}}}"#;
        let result = extract_trace_context("{}", Some(body));
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["trace_id"], "bt");
        assert_eq!(v["parent_span"], "bs");
    }

    #[test]
    fn test_extract_no_trace_found() {
        let result = extract_trace_context(r#"{"Content-Type": "json"}"#, None);
        let v: Value = serde_json::from_str(&result).unwrap();
        assert!(v["trace_id"].is_null());
        assert!(v["parent_span"].is_null());
    }

    #[test]
    fn test_extract_only_trace_id_no_parent_span() {
        let result = extract_trace_context(r#"{"X-Trace-Id": "t1"}"#, None);
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["trace_id"], "t1");
        assert!(v["parent_span"].is_null());
    }

    #[test]
    fn test_extract_trace_id_from_header_parent_span_from_body() {
        let body = r#"{"method":"tools/call","params":{"arguments":{"_trace_id":"bt","_parent_span":"bs"}}}"#;
        let result = extract_trace_context(r#"{"X-Trace-Id": "ht"}"#, Some(body));
        let v: Value = serde_json::from_str(&result).unwrap();
        // trace_id from headers takes precedence
        assert_eq!(v["trace_id"], "ht");
        // parent_span falls back to body since headers had none
        assert_eq!(v["parent_span"], "bs");
    }

    // =========================================================================
    // filter_propagation_headers
    // =========================================================================

    #[test]
    fn test_filter_prefix_matching() {
        let result = filter_propagation_headers(
            r#"{"X-Audit-Id": "123", "X-Request-Id": "456", "Content-Type": "json"}"#,
            "x-audit, x-request",
        )
        .unwrap();
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["x-audit-id"], "123");
        assert_eq!(v["x-request-id"], "456");
        assert!(v.get("content-type").is_none());
    }

    #[test]
    fn test_filter_no_matches() {
        let result = filter_propagation_headers(
            r#"{"Content-Type": "json"}"#,
            "x-audit",
        )
        .unwrap();
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v.as_object().unwrap().len(), 0);
    }

    #[test]
    fn test_filter_empty_allowlist() {
        let result = filter_propagation_headers(
            r#"{"X-Audit-Id": "123"}"#,
            "",
        )
        .unwrap();
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v.as_object().unwrap().len(), 0);
    }

    #[test]
    fn test_filter_multiple_prefixes() {
        let result = filter_propagation_headers(
            r#"{"X-A-One": "1", "X-B-Two": "2", "X-C-Three": "3"}"#,
            "x-a, x-c",
        )
        .unwrap();
        let v: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["x-a-one"], "1");
        assert!(v.get("x-b-two").is_none());
        assert_eq!(v["x-c-three"], "3");
    }

    // =========================================================================
    // matches_propagate_header
    // =========================================================================

    #[test]
    fn test_matches_exact() {
        assert!(matches_propagate_header("x-audit", "x-audit"));
    }

    #[test]
    fn test_matches_prefix() {
        assert!(matches_propagate_header("X-Audit-Id", "x-audit"));
    }

    #[test]
    fn test_matches_no_match() {
        assert!(!matches_propagate_header("Content-Type", "x-audit"));
    }

    #[test]
    fn test_matches_empty_allowlist() {
        assert!(!matches_propagate_header("X-Audit-Id", ""));
    }
}
