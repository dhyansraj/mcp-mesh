//! JSON Schema normalization utilities for LLM structured output.
//!
//! Provides schema transformations needed by all provider handlers:
//! - Strict mode enforcement (additionalProperties, required)
//! - Validation keyword sanitization
//! - Media parameter detection
//! - Schema complexity analysis

use serde_json::Value;

/// Keywords removed by [`sanitize_schema`] — validation-only, not supported by LLM APIs.
const UNSUPPORTED_KEYWORDS: &[&str] = &[
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "multipleOf",
];

/// Make a JSON schema strict for structured output.
///
/// Deep-traverses the schema and for every object type:
/// - Sets `additionalProperties: false`
/// - If `add_all_required` is true, sets `required` to include ALL property keys
///
/// Handles `$defs`, `properties`, `items`, `prefixItems`, `anyOf`, `oneOf`, `allOf`.
pub fn make_schema_strict(schema_json: &str, add_all_required: bool) -> Result<String, String> {
    let mut schema: Value =
        serde_json::from_str(schema_json).map_err(|e| format!("Invalid JSON schema: {}", e))?;
    traverse_schema(&mut schema, &|map| {
        add_strict_constraints(map, add_all_required)
    });
    serde_json::to_string(&schema).map_err(|e| format!("Failed to serialize: {}", e))
}

/// Sanitize a JSON schema by removing unsupported validation keywords.
///
/// Removes keywords like `minimum`, `maximum`, `pattern`, `minLength`, etc.
/// that are not supported by LLM APIs for structured output.
pub fn sanitize_schema(schema_json: &str) -> Result<String, String> {
    let mut schema: Value =
        serde_json::from_str(schema_json).map_err(|e| format!("Invalid JSON schema: {}", e))?;
    traverse_schema(&mut schema, &strip_unsupported_keywords);
    serde_json::to_string(&schema).map_err(|e| format!("Failed to serialize: {}", e))
}

/// Check if any tool schema property contains `x-media-type`.
///
/// Input is a JSON string of a single tool schema in OpenAI format:
/// ```json
/// {"type": "function", "function": {"parameters": {"properties": {"image": {"type": "string", "x-media-type": "image"}}}}}
/// ```
pub fn detect_media_params(schema_json: &str) -> bool {
    let Ok(schema) = serde_json::from_str::<Value>(schema_json) else {
        return false;
    };

    // Navigate into function.parameters if present (OpenAI tool format)
    let target = schema
        .get("function")
        .and_then(|f| f.get("parameters"))
        .unwrap_or(&schema);

    has_media_type(target)
}

/// Returns true if the schema is simple enough for hint mode.
///
/// A schema is simple when:
/// - Less than 5 properties
/// - All properties are basic types (string, integer, number, boolean,
///   or array without nested objects)
/// - No nested objects with properties
/// - No `$ref` references
pub fn is_simple_schema(schema_json: &str) -> bool {
    let Ok(schema) = serde_json::from_str::<Value>(schema_json) else {
        return false;
    };
    check_simple(&schema)
}

// ---------------------------------------------------------------------------
// Internal traversal
// ---------------------------------------------------------------------------

/// Deep-traverse a JSON Schema value, applying `visitor` to every object node.
fn traverse_schema(
    value: &mut Value,
    visitor: &dyn Fn(&mut serde_json::Map<String, Value>),
) {
    match value {
        Value::Object(map) => {
            visitor(map);

            // Recurse into $defs
            if let Some(defs) = map.get_mut("$defs") {
                if let Value::Object(defs_map) = defs {
                    for def_value in defs_map.values_mut() {
                        traverse_schema(def_value, visitor);
                    }
                }
            }

            // Recurse into properties
            if let Some(props) = map.get_mut("properties") {
                if let Value::Object(props_map) = props {
                    for prop_value in props_map.values_mut() {
                        traverse_schema(prop_value, visitor);
                    }
                }
            }

            // Recurse into items (object or array)
            if let Some(items) = map.get_mut("items") {
                match items {
                    Value::Object(_) => traverse_schema(items, visitor),
                    Value::Array(arr) => {
                        for item in arr.iter_mut() {
                            traverse_schema(item, visitor);
                        }
                    }
                    _ => {}
                }
            }

            // Recurse into prefixItems
            if let Some(Value::Array(prefix_items)) = map.get_mut("prefixItems") {
                for item in prefix_items.iter_mut() {
                    traverse_schema(item, visitor);
                }
            }

            // Recurse into anyOf, oneOf, allOf
            for key in &["anyOf", "oneOf", "allOf"] {
                if let Some(Value::Array(variants)) = map.get_mut(*key) {
                    for variant in variants.iter_mut() {
                        traverse_schema(variant, visitor);
                    }
                }
            }
        }
        Value::Array(arr) => {
            for item in arr.iter_mut() {
                traverse_schema(item, visitor);
            }
        }
        _ => {}
    }
}

// ---------------------------------------------------------------------------
// Visitors
// ---------------------------------------------------------------------------

/// Visitor: add strict constraints to object-type nodes.
fn add_strict_constraints(
    map: &mut serde_json::Map<String, Value>,
    add_all_required: bool,
) {
    if map.get("type").and_then(|v| v.as_str()) == Some("object") {
        map.insert(
            "additionalProperties".to_string(),
            Value::Bool(false),
        );
        if add_all_required {
            if let Some(Value::Object(props)) = map.get("properties") {
                let keys: Vec<Value> =
                    props.keys().map(|k| Value::String(k.clone())).collect();
                map.insert("required".to_string(), Value::Array(keys));
            }
        }
    }
}

/// Visitor: strip validation-only keywords.
fn strip_unsupported_keywords(map: &mut serde_json::Map<String, Value>) {
    for keyword in UNSUPPORTED_KEYWORDS {
        map.remove(*keyword);
    }
}

// ---------------------------------------------------------------------------
// detect_media_params helpers
// ---------------------------------------------------------------------------

/// Recursively check if any property in the value contains `x-media-type`.
fn has_media_type(value: &Value) -> bool {
    match value {
        Value::Object(map) => {
            if map.contains_key("x-media-type") {
                return true;
            }
            // Check nested properties
            if let Some(Value::Object(props)) = map.get("properties") {
                for prop_value in props.values() {
                    if has_media_type(prop_value) {
                        return true;
                    }
                }
            }
            // Check items
            if let Some(items) = map.get("items") {
                if has_media_type(items) {
                    return true;
                }
            }
            // Check anyOf, oneOf, allOf
            for key in &["anyOf", "oneOf", "allOf"] {
                if let Some(Value::Array(variants)) = map.get(*key) {
                    for variant in variants {
                        if has_media_type(variant) {
                            return true;
                        }
                    }
                }
            }
            // Check $defs
            if let Some(Value::Object(defs)) = map.get("$defs") {
                for def_value in defs.values() {
                    if has_media_type(def_value) {
                        return true;
                    }
                }
            }
            false
        }
        Value::Array(arr) => arr.iter().any(|item| has_media_type(item)),
        _ => false,
    }
}

// ---------------------------------------------------------------------------
// is_simple_schema helpers
// ---------------------------------------------------------------------------

/// Check if a schema value is simple enough for hint mode.
fn check_simple(value: &Value) -> bool {
    let Some(obj) = value.as_object() else {
        return false;
    };

    // $ref means external/internal reference — not simple
    if obj.contains_key("$ref") {
        return false;
    }

    let Some(Value::Object(props)) = obj.get("properties") else {
        // No properties object — could be a primitive type, consider it simple
        return true;
    };

    // Must have fewer than 5 properties
    if props.len() >= 5 {
        return false;
    }

    // Every property must be a basic type
    for prop_value in props.values() {
        if !is_basic_type(prop_value) {
            return false;
        }
    }

    true
}

/// Returns true if the property schema represents a basic type.
///
/// Basic types: string, integer, number, boolean, or array without nested objects.
fn is_basic_type(value: &Value) -> bool {
    let Some(obj) = value.as_object() else {
        return false;
    };

    // $ref is never basic
    if obj.contains_key("$ref") {
        return false;
    }

    // Nested object with properties is not basic
    if obj.contains_key("properties") {
        return false;
    }

    let type_val = obj.get("type").and_then(|v| v.as_str());

    match type_val {
        Some("string" | "integer" | "number" | "boolean") => true,
        Some("array") => {
            // Array is basic only if items are not objects with properties
            match obj.get("items") {
                Some(items) => {
                    let items_obj = items.as_object();
                    match items_obj {
                        Some(m) => !m.contains_key("properties") && !m.contains_key("$ref"),
                        None => true,
                    }
                }
                None => true,
            }
        }
        // anyOf/oneOf could be a union — not simple
        _ => {
            if obj.contains_key("anyOf") || obj.contains_key("oneOf") || obj.contains_key("allOf")
            {
                return false;
            }
            // No type specified but no complex structures — treat as basic
            // (could be enum, const, etc.)
            !obj.contains_key("properties") && !obj.contains_key("$ref")
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // -----------------------------------------------------------------------
    // make_schema_strict
    // -----------------------------------------------------------------------

    #[test]
    fn strict_simple_object() {
        let schema = json!({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            }
        });
        let result = make_schema_strict(&schema.to_string(), true).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(parsed["additionalProperties"], Value::Bool(false));

        let required = parsed["required"].as_array().unwrap();
        assert_eq!(required.len(), 2);
        assert!(required.contains(&Value::String("name".to_string())));
        assert!(required.contains(&Value::String("age".to_string())));
    }

    #[test]
    fn strict_nested_defs() {
        let schema = json!({
            "type": "object",
            "properties": {
                "address": {"$ref": "#/$defs/Address"}
            },
            "$defs": {
                "Address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"},
                        "city": {"type": "string"}
                    }
                }
            }
        });
        let result = make_schema_strict(&schema.to_string(), true).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        // Root object
        assert_eq!(parsed["additionalProperties"], Value::Bool(false));

        // Nested def
        let address = &parsed["$defs"]["Address"];
        assert_eq!(address["additionalProperties"], Value::Bool(false));
        let required = address["required"].as_array().unwrap();
        assert!(required.contains(&Value::String("street".to_string())));
        assert!(required.contains(&Value::String("city".to_string())));
    }

    #[test]
    fn strict_array_items_object() {
        let schema = json!({
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "label": {"type": "string"}
                        }
                    }
                }
            }
        });
        let result = make_schema_strict(&schema.to_string(), true).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        let item_schema = &parsed["properties"]["items"]["items"];
        assert_eq!(item_schema["additionalProperties"], Value::Bool(false));
        let required = item_schema["required"].as_array().unwrap();
        assert_eq!(required.len(), 2);
    }

    #[test]
    fn strict_no_required_override() {
        let schema = json!({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            },
            "required": ["name"]
        });
        let result = make_schema_strict(&schema.to_string(), false).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        assert_eq!(parsed["additionalProperties"], Value::Bool(false));
        // Original required preserved — only "name"
        let required = parsed["required"].as_array().unwrap();
        assert_eq!(required.len(), 1);
        assert_eq!(required[0], "name");
    }

    #[test]
    fn strict_anyof_oneof_composition() {
        let schema = json!({
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"}
                    }
                },
                {
                    "type": "object",
                    "properties": {
                        "code": {"type": "integer"}
                    }
                }
            ]
        });
        let result = make_schema_strict(&schema.to_string(), true).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        for variant in parsed["anyOf"].as_array().unwrap() {
            assert_eq!(variant["additionalProperties"], Value::Bool(false));
            assert!(variant["required"].is_array());
        }

        // Test oneOf as well
        let schema2 = json!({
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "a": {"type": "string"}
                    }
                }
            ]
        });
        let result2 = make_schema_strict(&schema2.to_string(), true).unwrap();
        let parsed2: Value = serde_json::from_str(&result2).unwrap();
        assert_eq!(
            parsed2["oneOf"][0]["additionalProperties"],
            Value::Bool(false)
        );
    }

    #[test]
    fn strict_prefix_items() {
        let schema = json!({
            "type": "array",
            "prefixItems": [
                {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"}
                    }
                },
                {
                    "type": "object",
                    "properties": {
                        "y": {"type": "number"}
                    }
                }
            ]
        });
        let result = make_schema_strict(&schema.to_string(), true).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        for item in parsed["prefixItems"].as_array().unwrap() {
            assert_eq!(item["additionalProperties"], Value::Bool(false));
            assert!(item["required"].is_array());
        }
    }

    #[test]
    fn strict_invalid_json() {
        let result = make_schema_strict("not valid json", true);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Invalid JSON schema"));
    }

    // -----------------------------------------------------------------------
    // sanitize_schema
    // -----------------------------------------------------------------------

    #[test]
    fn sanitize_removes_min_max() {
        let schema = json!({
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100
                }
            }
        });
        let result = sanitize_schema(&schema.to_string()).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        let count = &parsed["properties"]["count"];
        assert!(count.get("minimum").is_none());
        assert!(count.get("maximum").is_none());
        assert_eq!(count["type"], "integer");
    }

    #[test]
    fn sanitize_removes_pattern() {
        let schema = json!({
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "pattern": "^[a-z]+@[a-z]+\\.[a-z]+$"
                }
            }
        });
        let result = sanitize_schema(&schema.to_string()).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert!(parsed["properties"]["email"].get("pattern").is_none());
        assert_eq!(parsed["properties"]["email"]["type"], "string");
    }

    #[test]
    fn sanitize_removes_length_constraints() {
        let schema = json!({
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255
                },
                "tags": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {"type": "string"}
                }
            }
        });
        let result = sanitize_schema(&schema.to_string()).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        let name = &parsed["properties"]["name"];
        assert!(name.get("minLength").is_none());
        assert!(name.get("maxLength").is_none());

        let tags = &parsed["properties"]["tags"];
        assert!(tags.get("minItems").is_none());
        assert!(tags.get("maxItems").is_none());
        // items still present
        assert_eq!(tags["items"]["type"], "string");
    }

    #[test]
    fn sanitize_nested_schemas() {
        let schema = json!({
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "properties": {
                        "inner": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "exclusiveMinimum": 0,
                            "exclusiveMaximum": 1,
                            "multipleOf": 0.1
                        }
                    }
                }
            }
        });
        let result = sanitize_schema(&schema.to_string()).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        let inner = &parsed["properties"]["outer"]["properties"]["inner"];
        assert!(inner.get("minimum").is_none());
        assert!(inner.get("maximum").is_none());
        assert!(inner.get("exclusiveMinimum").is_none());
        assert!(inner.get("exclusiveMaximum").is_none());
        assert!(inner.get("multipleOf").is_none());
        assert_eq!(inner["type"], "number");
    }

    #[test]
    fn sanitize_preserves_structural_keywords() {
        let schema = json!({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["name"],
            "additionalProperties": false,
            "$defs": {
                "Foo": {
                    "type": "object",
                    "properties": {
                        "bar": {"type": "integer"}
                    }
                }
            }
        });
        let result = sanitize_schema(&schema.to_string()).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();
        assert_eq!(parsed["type"], "object");
        assert!(parsed["properties"].is_object());
        assert!(parsed["required"].is_array());
        assert_eq!(parsed["additionalProperties"], Value::Bool(false));
        assert!(parsed["$defs"]["Foo"]["properties"].is_object());
    }

    #[test]
    fn sanitize_invalid_json() {
        let result = sanitize_schema("{bad");
        assert!(result.is_err());
    }

    // -----------------------------------------------------------------------
    // detect_media_params
    // -----------------------------------------------------------------------

    #[test]
    fn detect_media_openai_format() {
        let schema = json!({
            "type": "function",
            "function": {
                "name": "upload",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image": {
                            "type": "string",
                            "x-media-type": "image"
                        }
                    }
                }
            }
        });
        assert!(detect_media_params(&schema.to_string()));
    }

    #[test]
    fn detect_media_not_present() {
        let schema = json!({
            "type": "function",
            "function": {
                "name": "greet",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"}
                    }
                }
            }
        });
        assert!(!detect_media_params(&schema.to_string()));
    }

    #[test]
    fn detect_media_nested_property() {
        let schema = json!({
            "type": "function",
            "function": {
                "name": "process",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "object",
                            "properties": {
                                "file": {
                                    "type": "string",
                                    "x-media-type": "audio"
                                }
                            }
                        }
                    }
                }
            }
        });
        assert!(detect_media_params(&schema.to_string()));
    }

    #[test]
    fn detect_media_invalid_json() {
        assert!(!detect_media_params("not json"));
    }

    #[test]
    fn detect_media_bare_schema() {
        // Without the OpenAI function wrapper
        let schema = json!({
            "type": "object",
            "properties": {
                "audio": {
                    "type": "string",
                    "x-media-type": "audio"
                }
            }
        });
        assert!(detect_media_params(&schema.to_string()));
    }

    // -----------------------------------------------------------------------
    // is_simple_schema
    // -----------------------------------------------------------------------

    #[test]
    fn simple_basic_fields() {
        let schema = json!({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "active": {"type": "boolean"}
            }
        });
        assert!(is_simple_schema(&schema.to_string()));
    }

    #[test]
    fn simple_too_many_fields() {
        let schema = json!({
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
                "c": {"type": "string"},
                "d": {"type": "string"},
                "e": {"type": "string"}
            }
        });
        assert!(!is_simple_schema(&schema.to_string()));
    }

    #[test]
    fn simple_nested_object_not_simple() {
        let schema = json!({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"}
                    }
                }
            }
        });
        assert!(!is_simple_schema(&schema.to_string()));
    }

    #[test]
    fn simple_ref_not_simple() {
        let schema = json!({
            "type": "object",
            "properties": {
                "data": {"$ref": "#/$defs/Data"}
            }
        });
        assert!(!is_simple_schema(&schema.to_string()));
    }

    #[test]
    fn simple_array_of_objects_not_simple() {
        let schema = json!({
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"}
                        }
                    }
                }
            }
        });
        assert!(!is_simple_schema(&schema.to_string()));
    }

    #[test]
    fn simple_array_of_strings_is_simple() {
        let schema = json!({
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "name": {"type": "string"}
            }
        });
        assert!(is_simple_schema(&schema.to_string()));
    }

    #[test]
    fn simple_top_level_ref_not_simple() {
        let schema = json!({
            "$ref": "#/$defs/Foo",
            "$defs": {
                "Foo": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "string"}
                    }
                }
            }
        });
        assert!(!is_simple_schema(&schema.to_string()));
    }

    #[test]
    fn simple_invalid_json() {
        assert!(!is_simple_schema("not json"));
    }

    #[test]
    fn simple_no_properties() {
        // Primitive or empty schema — considered simple
        let schema = json!({"type": "string"});
        assert!(is_simple_schema(&schema.to_string()));
    }

    #[test]
    fn simple_four_fields_ok() {
        let schema = json!({
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "integer"},
                "c": {"type": "number"},
                "d": {"type": "boolean"}
            }
        });
        assert!(is_simple_schema(&schema.to_string()));
    }
}
