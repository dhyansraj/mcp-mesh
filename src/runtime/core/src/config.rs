//! Configuration resolution for MCP Mesh.
//!
//! Provides centralized config resolution with priority: ENV > param > default.
//! This ensures consistent behavior across all language SDKs.

use std::env;
use std::net::UdpSocket;
use tracing::{debug, warn};

#[cfg(feature = "python")]
use pyo3::prelude::*;

/// Configuration keys supported by MCP Mesh.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConfigKey {
    /// Registry URL (MCP_MESH_REGISTRY_URL)
    RegistryUrl,
    /// HTTP host announced to registry (MCP_MESH_HTTP_HOST)
    HttpHost,
    /// HTTP port (MCP_MESH_HTTP_PORT)
    HttpPort,
    /// Namespace for isolation (MCP_MESH_NAMESPACE)
    Namespace,
    /// Agent name (MCP_MESH_AGENT_NAME)
    AgentName,
    /// Heartbeat interval in seconds (MCP_MESH_HEALTH_INTERVAL)
    HealthInterval,
    /// Enable distributed tracing (MCP_MESH_DISTRIBUTED_TRACING_ENABLED)
    DistributedTracingEnabled,
    /// Redis URL (REDIS_URL)
    RedisUrl,
}

impl ConfigKey {
    /// Get the environment variable name for this config key.
    pub fn env_var(&self) -> &'static str {
        match self {
            ConfigKey::RegistryUrl => "MCP_MESH_REGISTRY_URL",
            ConfigKey::HttpHost => "MCP_MESH_HTTP_HOST",
            ConfigKey::HttpPort => "MCP_MESH_HTTP_PORT",
            ConfigKey::Namespace => "MCP_MESH_NAMESPACE",
            ConfigKey::AgentName => "MCP_MESH_AGENT_NAME",
            ConfigKey::HealthInterval => "MCP_MESH_HEALTH_INTERVAL",
            ConfigKey::DistributedTracingEnabled => "MCP_MESH_DISTRIBUTED_TRACING_ENABLED",
            ConfigKey::RedisUrl => "REDIS_URL",
        }
    }

    /// Get the default value for this config key.
    /// Returns None for keys that require a param value (no sensible default).
    pub fn default_value(&self) -> Option<&'static str> {
        match self {
            ConfigKey::RegistryUrl => Some("http://localhost:8000"),
            ConfigKey::HttpHost => None, // Special: auto-detect IP
            ConfigKey::HttpPort => None, // Required from param
            ConfigKey::Namespace => Some("default"),
            ConfigKey::AgentName => None, // Required from param
            ConfigKey::HealthInterval => Some("5"),
            ConfigKey::DistributedTracingEnabled => Some("false"),
            ConfigKey::RedisUrl => Some("redis://localhost:6379"),
        }
    }

    /// Parse a config key from string name.
    pub fn from_name(name: &str) -> Option<ConfigKey> {
        match name.to_lowercase().as_str() {
            "registry_url" => Some(ConfigKey::RegistryUrl),
            "http_host" => Some(ConfigKey::HttpHost),
            "http_port" => Some(ConfigKey::HttpPort),
            "namespace" => Some(ConfigKey::Namespace),
            "agent_name" => Some(ConfigKey::AgentName),
            "health_interval" => Some(ConfigKey::HealthInterval),
            "distributed_tracing_enabled" => Some(ConfigKey::DistributedTracingEnabled),
            "redis_url" => Some(ConfigKey::RedisUrl),
            _ => None,
        }
    }
}

/// Auto-detect external IP address.
///
/// Uses UDP socket trick to find the IP that would route to external networks.
/// Falls back to "localhost" if detection fails.
pub fn auto_detect_external_ip() -> String {
    // Try to connect to a public IP (doesn't actually send data)
    // This gives us the local IP that would be used to reach external networks
    match UdpSocket::bind("0.0.0.0:0") {
        Ok(socket) => {
            // Connect to Google DNS (doesn't send any data)
            if socket.connect("8.8.8.8:80").is_ok() {
                if let Ok(addr) = socket.local_addr() {
                    let ip = addr.ip().to_string();
                    debug!("Auto-detected external IP: {}", ip);
                    return ip;
                }
            }
        }
        Err(e) => {
            debug!("Failed to create socket for IP detection: {}", e);
        }
    }

    // Fallback to localhost
    debug!("IP auto-detection failed, using localhost");
    "localhost".to_string()
}

/// Resolve configuration value with priority: ENV > param > default.
///
/// # Arguments
/// * `key` - The configuration key to resolve
/// * `param_value` - Optional value from script/decorator parameters
///
/// # Returns
/// The resolved configuration value, or None if no value could be determined.
pub fn resolve_config(key: ConfigKey, param_value: Option<&str>) -> Option<String> {
    // Priority 1: Environment variable
    let env_var = key.env_var();
    if let Ok(value) = env::var(env_var) {
        if !value.is_empty() {
            debug!("Config '{}' resolved from ENV: {}", env_var, value);
            return Some(value);
        }
    }

    // Priority 2: Parameter value (from decorator/script)
    if let Some(value) = param_value {
        if !value.is_empty() {
            debug!("Config '{}' resolved from param: {}", env_var, value);
            return Some(value.to_string());
        }
    }

    // Priority 3: Default value
    // Special case for HttpHost: auto-detect IP
    if key == ConfigKey::HttpHost {
        let ip = auto_detect_external_ip();
        debug!("Config '{}' resolved from auto-detect: {}", env_var, ip);
        return Some(ip);
    }

    if let Some(default) = key.default_value() {
        debug!("Config '{}' resolved from default: {}", env_var, default);
        return Some(default.to_string());
    }

    // No value available
    warn!("Config '{}' has no value and no default", env_var);
    None
}

/// Resolve configuration value by key name (string-based API for FFI).
///
/// # Arguments
/// * `key_name` - The configuration key name (e.g., "registry_url", "http_host")
/// * `param_value` - Optional value from script/decorator parameters
///
/// # Returns
/// The resolved configuration value, or empty string if unknown key.
pub fn resolve_config_by_name(key_name: &str, param_value: Option<&str>) -> String {
    match ConfigKey::from_name(key_name) {
        Some(key) => resolve_config(key, param_value).unwrap_or_default(),
        None => {
            warn!("Unknown config key: {}", key_name);
            String::new()
        }
    }
}

/// Resolve boolean configuration value with priority: ENV > param > default.
///
/// # Arguments
/// * `key` - The configuration key to resolve
/// * `param_value` - Optional value from script/decorator parameters
///
/// # Returns
/// The resolved boolean value.
pub fn resolve_config_bool(key: ConfigKey, param_value: Option<bool>) -> bool {
    // Priority 1: Environment variable
    let env_var = key.env_var();
    if let Ok(value) = env::var(env_var) {
        let lower = value.to_lowercase();
        let result = matches!(lower.as_str(), "true" | "1" | "yes" | "on");
        debug!("Config '{}' (bool) resolved from ENV: {} -> {}", env_var, value, result);
        return result;
    }

    // Priority 2: Parameter value
    if let Some(value) = param_value {
        debug!("Config '{}' (bool) resolved from param: {}", env_var, value);
        return value;
    }

    // Priority 3: Default value
    if let Some(default) = key.default_value() {
        let lower = default.to_lowercase();
        let result = matches!(lower.as_str(), "true" | "1" | "yes" | "on");
        debug!("Config '{}' (bool) resolved from default: {} -> {}", env_var, default, result);
        return result;
    }

    false
}

/// Resolve integer configuration value with priority: ENV > param > default.
///
/// # Arguments
/// * `key` - The configuration key to resolve
/// * `param_value` - Optional value from script/decorator parameters
///
/// # Returns
/// The resolved integer value, or None if parsing fails.
pub fn resolve_config_int(key: ConfigKey, param_value: Option<i64>) -> Option<i64> {
    // Priority 1: Environment variable
    let env_var = key.env_var();
    if let Ok(value) = env::var(env_var) {
        if let Ok(parsed) = value.parse::<i64>() {
            debug!("Config '{}' (int) resolved from ENV: {}", env_var, parsed);
            return Some(parsed);
        }
    }

    // Priority 2: Parameter value
    if let Some(value) = param_value {
        debug!("Config '{}' (int) resolved from param: {}", env_var, value);
        return Some(value);
    }

    // Priority 3: Default value
    if let Some(default) = key.default_value() {
        if let Ok(parsed) = default.parse::<i64>() {
            debug!("Config '{}' (int) resolved from default: {}", env_var, parsed);
            return Some(parsed);
        }
    }

    None
}

/// Check if distributed tracing is enabled.
///
/// Convenience function that checks MCP_MESH_DISTRIBUTED_TRACING_ENABLED.
pub fn is_tracing_enabled() -> bool {
    resolve_config_bool(ConfigKey::DistributedTracingEnabled, None)
}

/// Get Redis URL with fallback to default.
///
/// Convenience function that resolves REDIS_URL.
pub fn get_redis_url() -> String {
    resolve_config(ConfigKey::RedisUrl, None)
        .unwrap_or_else(|| "redis://localhost:6379".to_string())
}

// =============================================================================
// Python bindings
// =============================================================================

#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (key_name, param_value=None))]
pub fn resolve_config_py(key_name: &str, param_value: Option<&str>) -> String {
    resolve_config_by_name(key_name, param_value)
}

#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (key_name, param_value=None))]
pub fn resolve_config_bool_py(key_name: &str, param_value: Option<bool>) -> bool {
    match ConfigKey::from_name(key_name) {
        Some(key) => resolve_config_bool(key, param_value),
        None => {
            warn!("Unknown config key for bool resolution: {}", key_name);
            false
        }
    }
}

#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (key_name, param_value=None))]
pub fn resolve_config_int_py(key_name: &str, param_value: Option<i64>) -> Option<i64> {
    match ConfigKey::from_name(key_name) {
        Some(key) => resolve_config_int(key, param_value),
        None => {
            warn!("Unknown config key for int resolution: {}", key_name);
            None
        }
    }
}

#[cfg(feature = "python")]
#[pyfunction]
pub fn is_tracing_enabled_py() -> bool {
    is_tracing_enabled()
}

#[cfg(feature = "python")]
#[pyfunction]
pub fn get_redis_url_py() -> String {
    get_redis_url()
}

#[cfg(feature = "python")]
#[pyfunction]
pub fn auto_detect_ip_py() -> String {
    auto_detect_external_ip()
}

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    #[test]
    fn test_config_key_env_var() {
        assert_eq!(ConfigKey::RegistryUrl.env_var(), "MCP_MESH_REGISTRY_URL");
        assert_eq!(ConfigKey::RedisUrl.env_var(), "REDIS_URL");
    }

    #[test]
    fn test_config_key_default_value() {
        assert_eq!(ConfigKey::RegistryUrl.default_value(), Some("http://localhost:8000"));
        assert_eq!(ConfigKey::Namespace.default_value(), Some("default"));
        assert_eq!(ConfigKey::HttpPort.default_value(), None);
    }

    #[test]
    fn test_resolve_config_default() {
        // Clear any existing env var
        env::remove_var("MCP_MESH_NAMESPACE");

        let value = resolve_config(ConfigKey::Namespace, None);
        assert_eq!(value, Some("default".to_string()));
    }

    #[test]
    fn test_resolve_config_param_over_default() {
        env::remove_var("MCP_MESH_NAMESPACE");

        let value = resolve_config(ConfigKey::Namespace, Some("production"));
        assert_eq!(value, Some("production".to_string()));
    }

    #[test]
    fn test_resolve_config_env_over_param() {
        env::set_var("MCP_MESH_NAMESPACE", "staging");

        let value = resolve_config(ConfigKey::Namespace, Some("production"));
        assert_eq!(value, Some("staging".to_string()));

        env::remove_var("MCP_MESH_NAMESPACE");
    }

    #[test]
    fn test_resolve_config_bool() {
        env::remove_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");

        // Default is false
        assert!(!resolve_config_bool(ConfigKey::DistributedTracingEnabled, None));

        // Param override
        assert!(resolve_config_bool(ConfigKey::DistributedTracingEnabled, Some(true)));

        // Env override
        env::set_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "true");
        assert!(resolve_config_bool(ConfigKey::DistributedTracingEnabled, Some(false)));

        env::remove_var("MCP_MESH_DISTRIBUTED_TRACING_ENABLED");
    }

    #[test]
    fn test_auto_detect_ip() {
        let ip = auto_detect_external_ip();
        // Should return something (either real IP or localhost)
        assert!(!ip.is_empty());
    }

    #[test]
    fn test_config_key_from_name() {
        assert_eq!(ConfigKey::from_name("registry_url"), Some(ConfigKey::RegistryUrl));
        assert_eq!(ConfigKey::from_name("REGISTRY_URL"), Some(ConfigKey::RegistryUrl));
        assert_eq!(ConfigKey::from_name("unknown"), None);
    }
}
