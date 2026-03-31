//! Provider request formatting for vendor-specific LLM logic.
//!
//! Consolidates vendor-specific behavior from all three SDKs using a
//! data-driven `VendorConfig` approach. Four vendors are supported:
//! `anthropic` (Claude), `openai`, `gemini`, `generic`.

use serde_json::Value;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASE_TOOL_INSTRUCTIONS: &str = "\n\nIMPORTANT TOOL CALLING RULES:\n- You have access to tools that you can call to gather information\n- Make ONE tool call at a time\n- After receiving tool results, you can make additional calls if needed\n- Once you have all needed information, provide your final response\n";

const CLAUDE_ANTI_XML_INSTRUCTION: &str = "- NEVER use XML-style syntax like <invoke name=\"tool_name\"/>\n";

const MEDIA_PARAM_INSTRUCTIONS: &str = "\n\nMEDIA PARAMETERS: Some tools accept media URIs (file://, s3://) in parameters marked with x-media-type. If you received images or media in this conversation, pass the media URI to the appropriate tool parameter.";

const DECISION_GUIDE: &str = "\nDECISION GUIDE:\n- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.\n- If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.\n- After calling a tool and receiving results, STOP calling tools and return your final JSON response.\n";

const GENERIC_TOOL_INSTRUCTIONS: &str = "\n\nTOOL CALLING RULES:\n- You can call tools to gather information\n- Make one tool call at a time\n- Wait for tool results before making additional calls\n- Use standard JSON function calling format\n- Provide your final response after gathering needed information\n";

// ---------------------------------------------------------------------------
// VendorConfig
// ---------------------------------------------------------------------------

struct VendorConfig {
    /// Vendor name
    name: &'static str,
    /// Whether vendor supports native response_format for structured output
    supports_response_format: bool,
    /// Whether to use response_format when tools are present
    /// (Gemini has a bug where response_format + tools causes infinite loops)
    response_format_with_tools: bool,
    /// Default output mode for schema types: "strict" or "hint"
    default_schema_mode: &'static str,
    /// Whether to add anti-XML instructions (Claude-specific)
    anti_xml_instruction: bool,
    /// Whether to use custom tool instructions (generic) or BASE_TOOL_INSTRUCTIONS
    use_generic_tool_instructions: bool,
    /// Hint style: "detailed" (Claude-style), "example" (Gemini-style), "full_schema" (generic)
    hint_style: &'static str,
}

fn get_vendor_config(provider: &str) -> VendorConfig {
    match provider.to_lowercase().as_str() {
        "anthropic" | "claude" => VendorConfig {
            name: "anthropic",
            supports_response_format: false,
            response_format_with_tools: false,
            default_schema_mode: "hint",
            anti_xml_instruction: true,
            use_generic_tool_instructions: false,
            hint_style: "detailed",
        },
        "openai" | "gpt" => VendorConfig {
            name: "openai",
            supports_response_format: true,
            response_format_with_tools: true,
            default_schema_mode: "strict",
            anti_xml_instruction: false,
            use_generic_tool_instructions: false,
            hint_style: "example",
        },
        "gemini" | "google" => VendorConfig {
            name: "gemini",
            supports_response_format: true,
            response_format_with_tools: false,
            default_schema_mode: "strict",
            anti_xml_instruction: false,
            use_generic_tool_instructions: false,
            hint_style: "example",
        },
        _ => VendorConfig {
            name: "generic",
            supports_response_format: false,
            response_format_with_tools: false,
            default_schema_mode: "hint",
            anti_xml_instruction: false,
            use_generic_tool_instructions: true,
            hint_style: "full_schema",
        },
    }
}

// ---------------------------------------------------------------------------
// Public functions
// ---------------------------------------------------------------------------

/// Determine the output mode for a provider given the context.
///
/// Returns `"text"`, `"hint"`, or `"strict"`.
pub fn determine_output_mode(
    provider: &str,
    is_string_type: bool,
    has_tools: bool,
    override_mode: Option<&str>,
) -> String {
    if let Some(mode) = override_mode {
        return mode.to_string();
    }

    if is_string_type {
        return "text".to_string();
    }

    let config = get_vendor_config(provider);

    if config.supports_response_format {
        if has_tools && !config.response_format_with_tools {
            "hint".to_string()
        } else {
            config.default_schema_mode.to_string()
        }
    } else {
        config.default_schema_mode.to_string()
    }
}

/// Build the complete system prompt with vendor-specific additions.
pub fn format_system_prompt(
    provider: &str,
    base_prompt: &str,
    has_tools: bool,
    has_media_params: bool,
    schema_json: Option<&str>,
    schema_name: Option<&str>,
    output_mode: &str,
) -> String {
    let config = get_vendor_config(provider);
    let mut result = base_prompt.to_string();

    // Tool instructions
    if has_tools {
        if config.use_generic_tool_instructions {
            result.push_str(GENERIC_TOOL_INSTRUCTIONS);
        } else if config.anti_xml_instruction {
            // Insert anti-XML instruction after "Make ONE tool call at a time"
            let mut tool_instr = BASE_TOOL_INSTRUCTIONS.to_string();
            if let Some(pos) = tool_instr.find("- Make ONE tool call at a time\n") {
                let insert_at = pos + "- Make ONE tool call at a time\n".len();
                tool_instr.insert_str(insert_at, CLAUDE_ANTI_XML_INSTRUCTION);
            }
            result.push_str(&tool_instr);
        } else {
            result.push_str(BASE_TOOL_INSTRUCTIONS);
        }
    }

    // Media parameters
    if has_media_params {
        result.push_str(MEDIA_PARAM_INSTRUCTIONS);
    }

    // Output mode formatting
    if output_mode == "text" {
        return result;
    }

    if output_mode == "strict" {
        let name = schema_name.unwrap_or("output");
        result.push_str(&format!(
            "\n\nYour final response will be structured as JSON matching the {} format.",
            name
        ));
        return result;
    }

    if output_mode == "hint" {
        if let Some(schema_str) = schema_json {
            if let Ok(schema) = serde_json::from_str::<Value>(schema_str) {
                let name = schema_name.unwrap_or("output");
                let hint = match config.hint_style {
                    "detailed" => format_hint_detailed(&schema, name, has_tools),
                    "example" => format_hint_example(&schema, has_tools),
                    "full_schema" => format_hint_full_schema(&schema),
                    _ => format_hint_full_schema(&schema),
                };
                result.push_str(&hint);
            }
        }
    }

    result
}

/// Build the `response_format` JSON object if the vendor supports it.
///
/// Returns `None` for vendors that do not use response_format, or when
/// tools are present and the vendor does not support that combination.
pub fn build_response_format(
    provider: &str,
    schema_json: &str,
    schema_name: &str,
    has_tools: bool,
) -> Option<String> {
    let config = get_vendor_config(provider);

    if !config.supports_response_format {
        return None;
    }

    if has_tools && !config.response_format_with_tools {
        return None;
    }

    // Sanitize and make strict
    let sanitized = crate::schema::sanitize_schema(schema_json).ok()?;
    let strict = crate::schema::make_schema_strict(&sanitized, true).ok()?;

    let strict_schema: Value = serde_json::from_str(&strict).ok()?;

    let response_format = serde_json::json!({
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": strict_schema,
            "strict": true
        }
    });

    Some(response_format.to_string())
}

/// Return vendor capabilities as a JSON string.
pub fn get_vendor_capabilities(provider: &str) -> String {
    let config = get_vendor_config(provider);
    let caps = match config.name {
        "anthropic" => serde_json::json!({
            "native_tool_calling": true,
            "structured_output": false,
            "streaming": true,
            "vision": true,
            "json_mode": false,
            "prompt_caching": true,
        }),
        "openai" => serde_json::json!({
            "native_tool_calling": true,
            "structured_output": true,
            "streaming": true,
            "vision": true,
            "json_mode": true,
        }),
        "gemini" => serde_json::json!({
            "native_tool_calling": true,
            "structured_output": true,
            "streaming": true,
            "vision": true,
            "json_mode": true,
            "large_context": true,
        }),
        _ => serde_json::json!({
            "native_tool_calling": true,
            "structured_output": false,
            "streaming": false,
            "vision": false,
            "json_mode": false,
        }),
    };
    caps.to_string()
}

// ---------------------------------------------------------------------------
// Hint formatting helpers
// ---------------------------------------------------------------------------

fn format_hint_detailed(schema: &Value, schema_name: &str, has_tools: bool) -> String {
    let mut result = String::new();

    if has_tools {
        result.push_str(DECISION_GUIDE);
    }

    result.push_str(&format!(
        "\nRESPONSE FORMAT:\nYou MUST respond with valid JSON matching the {} schema:\n{{\n",
        schema_name
    ));

    if let Some(properties) = schema.get("properties").and_then(|p| p.as_object()) {
        let required: Vec<&str> = schema
            .get("required")
            .and_then(|r| r.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect())
            .unwrap_or_default();

        for (name, prop) in properties {
            let field_type = prop
                .get("type")
                .and_then(|t| t.as_str())
                .unwrap_or("any");
            let req_marker = if required.contains(&name.as_str()) {
                " (required)"
            } else {
                " (optional)"
            };
            let desc = prop
                .get("description")
                .and_then(|d| d.as_str())
                .unwrap_or("");
            let desc_text = if !desc.is_empty() {
                format!(" - {}", desc)
            } else {
                String::new()
            };
            result.push_str(&format!(
                "  - {}: {}{}{}\n",
                name, field_type, req_marker, desc_text
            ));
        }
    }

    result.push_str(
        "}\n\nCRITICAL: Your response must be ONLY the raw JSON object.\n\
         - DO NOT wrap in markdown code fences (```json or ```)\n\
         - DO NOT include any text before or after the JSON\n\
         - Start directly with { and end with }",
    );
    result
}

fn format_hint_example(schema: &Value, has_tools: bool) -> String {
    let mut result = String::new();
    result.push_str("\n\nOUTPUT FORMAT:\n");

    if has_tools {
        result.push_str("DECISION GUIDE:\n");
        result.push_str("- If your answer requires real-time data (weather, calculations, etc.), call the appropriate tool FIRST, then format your response as JSON.\n");
        result.push_str("- If your answer is general knowledge (like facts, explanations, definitions), directly return your response as JSON WITHOUT calling tools.\n\n");
    }

    result.push_str("Your FINAL response must be ONLY valid JSON (no markdown, no code blocks) with this exact structure:\n");
    result.push_str(&build_json_example(schema));
    result.push_str("\n\nReturn ONLY the JSON object with actual values. Do not include the schema definition, markdown formatting, or code blocks.");
    result
}

fn build_json_example(schema: &Value) -> String {
    if let Some(properties) = schema.get("properties").and_then(|p| p.as_object()) {
        if properties.is_empty() {
            return "{}".to_string();
        }

        let mut parts = Vec::new();
        let items: Vec<_> = properties.iter().collect();
        for (i, (name, prop)) in items.iter().enumerate() {
            let prop_type = prop
                .get("type")
                .and_then(|t| t.as_str())
                .unwrap_or("string");
            let example_value = match prop_type {
                "string" => format!("\"<your {} here>\"", name),
                "number" | "integer" => "0".to_string(),
                "array" => "[\"item1\", \"item2\"]".to_string(),
                "boolean" => "true".to_string(),
                "object" => "{}".to_string(),
                _ => "...".to_string(),
            };
            let comma = if i < items.len() - 1 { "," } else { "" };
            let desc = prop.get("description").and_then(|d| d.as_str());
            if let Some(d) = desc {
                parts.push(format!(
                    "  \"{}\": {}{}  // {}",
                    name, example_value, comma, d
                ));
            } else {
                parts.push(format!("  \"{}\": {}{}", name, example_value, comma));
            }
        }
        format!("{{\n{}\n}}", parts.join("\n"))
    } else {
        "{}".to_string()
    }
}

fn format_hint_full_schema(schema: &Value) -> String {
    let schema_str = serde_json::to_string_pretty(schema).unwrap_or_default();
    format!(
        "\n\nIMPORTANT: Return your final response as valid JSON matching this exact schema:\n{}\n\nRules:\n- Return ONLY the JSON object, no markdown, no additional text\n- Ensure all required fields are present\n- Match the schema exactly\n- Use double quotes for strings\n- Do not include comments",
        schema_str
    )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // -----------------------------------------------------------------------
    // determine_output_mode
    // -----------------------------------------------------------------------

    #[test]
    fn output_mode_anthropic_string_type() {
        let mode = determine_output_mode("anthropic", true, false, None);
        assert_eq!(mode, "text");
    }

    #[test]
    fn output_mode_anthropic_schema() {
        let mode = determine_output_mode("anthropic", false, false, None);
        assert_eq!(mode, "hint");
    }

    #[test]
    fn output_mode_anthropic_alias_claude() {
        let mode = determine_output_mode("claude", false, false, None);
        assert_eq!(mode, "hint");
    }

    #[test]
    fn output_mode_openai_schema() {
        let mode = determine_output_mode("openai", false, false, None);
        assert_eq!(mode, "strict");
    }

    #[test]
    fn output_mode_openai_string_type() {
        let mode = determine_output_mode("openai", true, false, None);
        assert_eq!(mode, "text");
    }

    #[test]
    fn output_mode_openai_with_tools() {
        let mode = determine_output_mode("openai", false, true, None);
        assert_eq!(mode, "strict");
    }

    #[test]
    fn output_mode_gemini_schema_no_tools() {
        let mode = determine_output_mode("gemini", false, false, None);
        assert_eq!(mode, "strict");
    }

    #[test]
    fn output_mode_gemini_schema_with_tools_fallback() {
        let mode = determine_output_mode("gemini", false, true, None);
        assert_eq!(mode, "hint");
    }

    #[test]
    fn output_mode_gemini_alias_google() {
        let mode = determine_output_mode("google", false, true, None);
        assert_eq!(mode, "hint");
    }

    #[test]
    fn output_mode_generic_schema() {
        let mode = determine_output_mode("generic", false, false, None);
        assert_eq!(mode, "hint");
    }

    #[test]
    fn output_mode_override_wins() {
        let mode = determine_output_mode("anthropic", false, false, Some("strict"));
        assert_eq!(mode, "strict");
    }

    #[test]
    fn output_mode_override_wins_over_string() {
        let mode = determine_output_mode("openai", true, true, Some("hint"));
        assert_eq!(mode, "hint");
    }

    #[test]
    fn output_mode_unknown_vendor_generic_behavior() {
        let mode = determine_output_mode("some-unknown-vendor", false, false, None);
        assert_eq!(mode, "hint");
    }

    #[test]
    fn output_mode_gpt_alias() {
        let mode = determine_output_mode("gpt", false, false, None);
        assert_eq!(mode, "strict");
    }

    // -----------------------------------------------------------------------
    // format_system_prompt
    // -----------------------------------------------------------------------

    #[test]
    fn prompt_anthropic_with_tools_has_anti_xml() {
        let prompt = format_system_prompt(
            "anthropic",
            "You are an assistant.",
            true,
            false,
            None,
            None,
            "text",
        );
        assert!(prompt.contains("IMPORTANT TOOL CALLING RULES"));
        assert!(prompt.contains("NEVER use XML-style syntax"));
    }

    #[test]
    fn prompt_openai_with_tools_no_anti_xml() {
        let prompt = format_system_prompt(
            "openai",
            "You are an assistant.",
            true,
            false,
            None,
            None,
            "text",
        );
        assert!(prompt.contains("IMPORTANT TOOL CALLING RULES"));
        assert!(!prompt.contains("NEVER use XML-style syntax"));
    }

    #[test]
    fn prompt_generic_with_tools_uses_generic_instructions() {
        let prompt = format_system_prompt(
            "generic",
            "You are an assistant.",
            true,
            false,
            None,
            None,
            "text",
        );
        assert!(prompt.contains("TOOL CALLING RULES"));
        assert!(prompt.contains("Use standard JSON function calling format"));
        assert!(!prompt.contains("IMPORTANT TOOL CALLING RULES"));
    }

    #[test]
    fn prompt_media_params_appended() {
        let prompt = format_system_prompt(
            "openai",
            "Base prompt.",
            false,
            true,
            None,
            None,
            "text",
        );
        assert!(prompt.contains("MEDIA PARAMETERS"));
        assert!(prompt.contains("x-media-type"));
    }

    #[test]
    fn prompt_text_mode_no_json_instructions() {
        let schema = json!({
            "type": "object",
            "properties": {
                "answer": {"type": "string"}
            }
        });
        let prompt = format_system_prompt(
            "anthropic",
            "Base prompt.",
            false,
            false,
            Some(&schema.to_string()),
            Some("MySchema"),
            "text",
        );
        assert!(!prompt.contains("RESPONSE FORMAT"));
        assert!(!prompt.contains("OUTPUT FORMAT"));
        assert!(!prompt.contains("IMPORTANT: Return your final response"));
    }

    #[test]
    fn prompt_strict_mode_brief_note() {
        let prompt = format_system_prompt(
            "openai",
            "Base prompt.",
            false,
            false,
            None,
            Some("WeatherResponse"),
            "strict",
        );
        assert!(prompt.contains("structured as JSON matching the WeatherResponse format"));
    }

    #[test]
    fn prompt_hint_mode_anthropic_detailed() {
        let schema = json!({
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "The answer"},
                "confidence": {"type": "number"}
            },
            "required": ["answer"]
        });
        let prompt = format_system_prompt(
            "anthropic",
            "Base prompt.",
            false,
            false,
            Some(&schema.to_string()),
            Some("Result"),
            "hint",
        );
        assert!(prompt.contains("RESPONSE FORMAT"));
        assert!(prompt.contains("Result schema"));
        assert!(prompt.contains("answer: string (required) - The answer"));
        assert!(prompt.contains("confidence: number (optional)"));
        assert!(prompt.contains("CRITICAL"));
    }

    #[test]
    fn prompt_hint_mode_gemini_example() {
        let schema = json!({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"}
            }
        });
        let prompt = format_system_prompt(
            "gemini",
            "Base prompt.",
            false,
            false,
            Some(&schema.to_string()),
            Some("Output"),
            "hint",
        );
        assert!(prompt.contains("OUTPUT FORMAT"));
        assert!(prompt.contains("<your name here>"));
        assert!(prompt.contains("Return ONLY the JSON object"));
    }

    #[test]
    fn prompt_hint_mode_generic_full_schema() {
        let schema = json!({
            "type": "object",
            "properties": {
                "status": {"type": "string"}
            }
        });
        let prompt = format_system_prompt(
            "some-random-vendor",
            "Base prompt.",
            false,
            false,
            Some(&schema.to_string()),
            None,
            "hint",
        );
        assert!(prompt.contains("IMPORTANT: Return your final response as valid JSON"));
        assert!(prompt.contains("Match the schema exactly"));
    }

    #[test]
    fn prompt_hint_with_tools_includes_decision_guide_anthropic() {
        let schema = json!({
            "type": "object",
            "properties": {
                "result": {"type": "string"}
            }
        });
        let prompt = format_system_prompt(
            "anthropic",
            "Base prompt.",
            true,
            false,
            Some(&schema.to_string()),
            Some("Out"),
            "hint",
        );
        assert!(prompt.contains("DECISION GUIDE"));
    }

    #[test]
    fn prompt_hint_with_tools_includes_decision_guide_gemini() {
        let schema = json!({
            "type": "object",
            "properties": {
                "result": {"type": "string"}
            }
        });
        let prompt = format_system_prompt(
            "gemini",
            "Base prompt.",
            true,
            false,
            Some(&schema.to_string()),
            Some("Out"),
            "hint",
        );
        assert!(prompt.contains("DECISION GUIDE"));
    }

    #[test]
    fn prompt_no_tools_no_tool_instructions() {
        let prompt = format_system_prompt(
            "openai",
            "Base prompt.",
            false,
            false,
            None,
            None,
            "text",
        );
        assert!(!prompt.contains("TOOL CALLING RULES"));
    }

    // -----------------------------------------------------------------------
    // build_response_format
    // -----------------------------------------------------------------------

    #[test]
    fn response_format_openai_returns_some() {
        let schema = json!({
            "type": "object",
            "properties": {
                "answer": {"type": "string"}
            }
        });
        let result = build_response_format("openai", &schema.to_string(), "Answer", false);
        assert!(result.is_some());
        let parsed: Value = serde_json::from_str(&result.unwrap()).unwrap();
        assert_eq!(parsed["type"], "json_schema");
        assert_eq!(parsed["json_schema"]["name"], "Answer");
        assert_eq!(parsed["json_schema"]["strict"], true);
        assert!(parsed["json_schema"]["schema"].is_object());
    }

    #[test]
    fn response_format_openai_with_tools_returns_some() {
        let schema = json!({
            "type": "object",
            "properties": {
                "answer": {"type": "string"}
            }
        });
        let result = build_response_format("openai", &schema.to_string(), "Answer", true);
        assert!(result.is_some());
    }

    #[test]
    fn response_format_anthropic_returns_none() {
        let schema = json!({
            "type": "object",
            "properties": {
                "answer": {"type": "string"}
            }
        });
        let result = build_response_format("anthropic", &schema.to_string(), "Answer", false);
        assert!(result.is_none());
    }

    #[test]
    fn response_format_gemini_no_tools_returns_some() {
        let schema = json!({
            "type": "object",
            "properties": {
                "answer": {"type": "string"}
            }
        });
        let result = build_response_format("gemini", &schema.to_string(), "Answer", false);
        assert!(result.is_some());
        let parsed: Value = serde_json::from_str(&result.unwrap()).unwrap();
        assert_eq!(parsed["type"], "json_schema");
    }

    #[test]
    fn response_format_gemini_with_tools_returns_none() {
        let schema = json!({
            "type": "object",
            "properties": {
                "answer": {"type": "string"}
            }
        });
        let result = build_response_format("gemini", &schema.to_string(), "Answer", true);
        assert!(result.is_none());
    }

    #[test]
    fn response_format_generic_returns_none() {
        let schema = json!({
            "type": "object",
            "properties": {
                "answer": {"type": "string"}
            }
        });
        let result = build_response_format("generic", &schema.to_string(), "Answer", false);
        assert!(result.is_none());
    }

    #[test]
    fn response_format_schema_made_strict() {
        let schema = json!({
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "integer"}
            }
        });
        let result = build_response_format("openai", &schema.to_string(), "Test", false).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        let inner_schema = &parsed["json_schema"]["schema"];
        assert_eq!(inner_schema["additionalProperties"], false);
        let required = inner_schema["required"].as_array().unwrap();
        assert_eq!(required.len(), 2);
    }

    #[test]
    fn response_format_invalid_schema_returns_none() {
        let result = build_response_format("openai", "not valid json", "Test", false);
        assert!(result.is_none());
    }

    // -----------------------------------------------------------------------
    // get_vendor_capabilities
    // -----------------------------------------------------------------------

    #[test]
    fn capabilities_anthropic() {
        let caps_str = get_vendor_capabilities("anthropic");
        let caps: Value = serde_json::from_str(&caps_str).unwrap();
        assert_eq!(caps["structured_output"], false);
        assert_eq!(caps["prompt_caching"], true);
        assert_eq!(caps["native_tool_calling"], true);
        assert_eq!(caps["vision"], true);
    }

    #[test]
    fn capabilities_openai() {
        let caps_str = get_vendor_capabilities("openai");
        let caps: Value = serde_json::from_str(&caps_str).unwrap();
        assert_eq!(caps["structured_output"], true);
        assert_eq!(caps["json_mode"], true);
        assert_eq!(caps["streaming"], true);
    }

    #[test]
    fn capabilities_gemini() {
        let caps_str = get_vendor_capabilities("gemini");
        let caps: Value = serde_json::from_str(&caps_str).unwrap();
        assert_eq!(caps["structured_output"], true);
        assert_eq!(caps["large_context"], true);
    }

    #[test]
    fn capabilities_unknown_conservative() {
        let caps_str = get_vendor_capabilities("some-random-vendor");
        let caps: Value = serde_json::from_str(&caps_str).unwrap();
        assert_eq!(caps["structured_output"], false);
        assert_eq!(caps["streaming"], false);
        assert_eq!(caps["vision"], false);
        assert_eq!(caps["json_mode"], false);
        assert_eq!(caps["native_tool_calling"], true);
    }

    #[test]
    fn capabilities_claude_alias() {
        let caps_str = get_vendor_capabilities("claude");
        let caps: Value = serde_json::from_str(&caps_str).unwrap();
        assert_eq!(caps["prompt_caching"], true);
    }

    #[test]
    fn capabilities_gpt_alias() {
        let caps_str = get_vendor_capabilities("gpt");
        let caps: Value = serde_json::from_str(&caps_str).unwrap();
        assert_eq!(caps["structured_output"], true);
    }

    // -----------------------------------------------------------------------
    // Hint formatting helpers
    // -----------------------------------------------------------------------

    #[test]
    fn hint_detailed_empty_properties() {
        let schema = json!({"type": "object", "properties": {}});
        let hint = format_hint_detailed(&schema, "Empty", false);
        assert!(hint.contains("RESPONSE FORMAT"));
        assert!(hint.contains("CRITICAL"));
    }

    #[test]
    fn hint_example_typed_placeholders() {
        let schema = json!({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "items": {"type": "array"},
                "active": {"type": "boolean"},
                "data": {"type": "object"}
            }
        });
        let hint = format_hint_example(&schema, false);
        assert!(hint.contains("<your name here>"));
        assert!(hint.contains("0"));
        assert!(hint.contains("[\"item1\", \"item2\"]"));
        assert!(hint.contains("true"));
        assert!(hint.contains("{}"));
    }

    #[test]
    fn hint_example_with_description() {
        let schema = json!({
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Name of the city"}
            }
        });
        let hint = format_hint_example(&schema, false);
        assert!(hint.contains("// Name of the city"));
    }

    #[test]
    fn hint_full_schema_includes_rules() {
        let schema = json!({"type": "object", "properties": {"x": {"type": "string"}}});
        let hint = format_hint_full_schema(&schema);
        assert!(hint.contains("IMPORTANT: Return your final response"));
        assert!(hint.contains("Match the schema exactly"));
        assert!(hint.contains("Do not include comments"));
    }

    #[test]
    fn hint_example_empty_properties() {
        let schema = json!({"type": "object", "properties": {}});
        let hint = build_json_example(&schema);
        assert_eq!(hint, "{}");
    }

    #[test]
    fn hint_example_no_properties_key() {
        let schema = json!({"type": "string"});
        let hint = build_json_example(&schema);
        assert_eq!(hint, "{}");
    }
}
