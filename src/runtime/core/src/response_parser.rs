//! Response parsing utilities for LLM outputs.
//!
//! Extracts JSON from mixed LLM responses (narrative + code fences + raw JSON).
//! This logic was previously duplicated across Python, TypeScript, and Java SDKs.

use std::sync::OnceLock;

use regex::Regex;

fn code_block_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"```(?:json)?\s*([\s\S]*?)```").unwrap())
}

fn strip_fence_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?m)^```(?:json)?\s*|\s*```$").unwrap())
}

/// Extract JSON from LLM response text.
///
/// Strategies (in order):
/// 1. Find ````json...```` code blocks
/// 2. Progressive JSON object extraction (`{...}`)
/// 3. Progressive JSON array extraction (`[...]`)
///
/// Schema validation is NOT done here -- that stays in SDKs (Pydantic/Zod/victools).
pub fn extract_json(text: &str) -> Option<String> {
    // Strategy 1: code fence extraction
    if let Some(caps) = code_block_regex().captures(text) {
        let inner = caps.get(1).unwrap().as_str().trim();
        if !inner.is_empty() {
            return Some(inner.to_string());
        }
    }

    // Strategy 2: progressive object parse
    if let Some(start) = text.find('{') {
        if let Some(result) = try_progressive_parse(text, start, '{', '}') {
            return Some(result);
        }
    }

    // Strategy 3: progressive array parse
    if let Some(start) = text.find('[') {
        if let Some(result) = try_progressive_parse(text, start, '[', ']') {
            return Some(result);
        }
    }

    None
}

/// Strip markdown code fences from content.
///
/// Handles: ````json ... ````, ```` ... ````
pub fn strip_code_fences(text: &str) -> String {
    strip_fence_regex().replace_all(text, "").trim().to_string()
}

/// Attempt progressive depth-counting parse to find valid JSON.
///
/// Starting from `start_byte`, tracks brace/bracket depth and tries
/// `serde_json::from_str` at each position where depth returns to zero.
/// Returns the first valid JSON substring found.
fn try_progressive_parse(
    content: &str,
    start_byte: usize,
    open: char,
    close: char,
) -> Option<String> {
    let slice = &content[start_byte..];
    let mut depth = 0i32;
    let mut potential_ends = Vec::new();

    for (byte_offset, ch) in slice.char_indices() {
        if ch == open {
            depth += 1;
        } else if ch == close {
            depth -= 1;
            if depth == 0 {
                // byte_offset is relative to slice; convert to absolute
                potential_ends.push(start_byte + byte_offset);
            }
        }
    }

    // Try each potential end position (shortest first)
    for end in potential_ends {
        let candidate = &content[start_byte..=end];
        if serde_json::from_str::<serde_json::Value>(candidate).is_ok() {
            return Some(candidate.to_string());
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── extract_json ────────────────────────────────────────────

    #[test]
    fn plain_json_object() {
        let input = r#"{"key": "value", "num": 42}"#;
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["key"], "value");
        assert_eq!(v["num"], 42);
    }

    #[test]
    fn plain_json_array() {
        let input = r#"[1, 2, 3]"#;
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v, serde_json::json!([1, 2, 3]));
    }

    #[test]
    fn json_in_code_fence() {
        let input = "Here is the result:\n```json\n{\"a\": 1}\n```\nDone.";
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["a"], 1);
    }

    #[test]
    fn json_in_plain_code_fence() {
        let input = "Result:\n```\n{\"b\": 2}\n```";
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["b"], 2);
    }

    #[test]
    fn json_mixed_with_narrative() {
        let input = "The agent returned: {\"status\": \"ok\"} and then stopped.";
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["status"], "ok");
    }

    #[test]
    fn nested_braces_in_strings() {
        // The string value contains braces that should not confuse depth counting,
        // but since we validate with serde_json, invalid slices are skipped.
        let input = r#"{"msg": "use {x} and {y}", "ok": true}"#;
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["ok"], true);
        assert_eq!(v["msg"], "use {x} and {y}");
    }

    #[test]
    fn multiple_json_objects_returns_first_valid() {
        let input = r#"first: {"a": 1} second: {"b": 2}"#;
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["a"], 1);
    }

    #[test]
    fn no_json_returns_none() {
        assert!(extract_json("Hello, world! No JSON here.").is_none());
    }

    #[test]
    fn empty_string_returns_none() {
        assert!(extract_json("").is_none());
    }

    #[test]
    fn nested_objects() {
        let input = r#"{"outer": {"inner": [1, 2, 3]}, "flag": true}"#;
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["outer"]["inner"], serde_json::json!([1, 2, 3]));
        assert_eq!(v["flag"], true);
    }

    #[test]
    fn array_in_narrative() {
        let input = "The list is [1, 2, 3] as expected.";
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v, serde_json::json!([1, 2, 3]));
    }

    #[test]
    fn code_fence_preferred_over_raw_json() {
        // Code fence content takes priority even if there's raw JSON before it
        let input = "junk {\"ignore\": true}\n```json\n{\"pick\": \"me\"}\n```";
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["pick"], "me");
    }

    #[test]
    fn unicode_content() {
        let input = r#"{"greeting": "こんにちは", "emoji": "🎉"}"#;
        let result = extract_json(input).unwrap();
        let v: serde_json::Value = serde_json::from_str(&result).unwrap();
        assert_eq!(v["greeting"], "こんにちは");
        assert_eq!(v["emoji"], "🎉");
    }

    // ── strip_code_fences ───────────────────────────────────────

    #[test]
    fn strip_json_fence() {
        let input = "```json\n{\"a\": 1}\n```";
        assert_eq!(strip_code_fences(input), "{\"a\": 1}");
    }

    #[test]
    fn strip_plain_fence() {
        let input = "```\n{\"a\": 1}\n```";
        assert_eq!(strip_code_fences(input), "{\"a\": 1}");
    }

    #[test]
    fn strip_no_fences() {
        let input = "{\"a\": 1}";
        assert_eq!(strip_code_fences(input), "{\"a\": 1}");
    }

    #[test]
    fn strip_preserves_inner_content() {
        let input = "```json\nline one\nline two\n```";
        assert_eq!(strip_code_fences(input), "line one\nline two");
    }
}
