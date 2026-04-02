//! Fast JSON parsing with simd-json when available, serde_json fallback.

use serde_json::Value;

/// Parse a JSON string into a serde_json::Value.
/// Uses simd-json when the `simd` feature is enabled for ~2-3x speedup.
#[cfg(feature = "simd")]
pub fn parse(input: &str) -> Result<Value, String> {
    // simd-json requires mutable bytes and owned string
    let mut bytes = input.as_bytes().to_vec();
    simd_json::serde::from_slice::<Value>(&mut bytes)
        .map_err(|e| format!("JSON parse error: {}", e))
}

#[cfg(not(feature = "simd"))]
pub fn parse(input: &str) -> Result<Value, String> {
    serde_json::from_str(input)
        .map_err(|e| format!("JSON parse error: {}", e))
}

/// Check if a string is valid JSON by attempting to parse it.
#[cfg(feature = "simd")]
pub fn is_valid(input: &str) -> bool {
    let mut bytes = input.as_bytes().to_vec();
    simd_json::serde::from_slice::<Value>(&mut bytes).is_ok()
}

#[cfg(not(feature = "simd"))]
pub fn is_valid(input: &str) -> bool {
    serde_json::from_str::<Value>(input).is_ok()
}
