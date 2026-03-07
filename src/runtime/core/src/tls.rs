//! TLS configuration for agent-to-registry communication.
//!
//! Reads environment variables to configure mTLS between agents and the registry.
//! Currently supports file-based certificates only. Future providers (SPIRE, Vault)
//! are deferred.
//!
//! Environment variables:
//! - `MCP_MESH_TLS_MODE` - TLS mode: "off" (default), "auto", "strict"
//! - `MCP_MESH_TLS_CERT` - Path to client certificate PEM file
//! - `MCP_MESH_TLS_KEY` - Path to client private key PEM file
//! - `MCP_MESH_TLS_CA` - Path to CA certificate PEM file
//! - `MCP_MESH_TLS_PROVIDER` - (reserved) Future credential provider name

use std::env;
use thiserror::Error;
use tracing::{debug, info, warn};

#[cfg(feature = "python")]
use pyo3::prelude::*;

/// Errors that can occur during TLS configuration.
#[derive(Debug, Error)]
pub enum TlsError {
    #[error("Failed to read file '{path}': {source}")]
    FileRead {
        path: String,
        source: std::io::Error,
    },

    #[error("Failed to parse PEM identity from cert+key: {0}")]
    IdentityParse(reqwest::Error),

    #[error("Failed to parse CA certificate PEM: {0}")]
    CertificateParse(reqwest::Error),

    #[error("TLS mode '{0}' requires {1}")]
    MissingConfig(String, String),
}

/// TLS operation mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TlsMode {
    /// No TLS (default, development)
    Off,
    /// Auto-generated certs from `meshctl --tls-auto`
    Auto,
    /// Production: require valid certificates
    Strict,
}

impl TlsMode {
    /// Parse a TLS mode from a string value.
    fn from_str_value(s: &str) -> Self {
        match s.trim().to_lowercase().as_str() {
            "auto" => TlsMode::Auto,
            "strict" => TlsMode::Strict,
            "off" | "" => TlsMode::Off,
            other => {
                warn!(
                    "Unknown MCP_MESH_TLS_MODE '{}', defaulting to Off",
                    other
                );
                TlsMode::Off
            }
        }
    }
}

/// TLS configuration resolved from environment variables.
#[derive(Debug, Clone)]
pub struct TlsConfig {
    pub mode: TlsMode,
    pub cert_path: Option<String>,
    pub key_path: Option<String>,
    pub ca_path: Option<String>,
}

impl TlsConfig {
    /// Resolve TLS config from environment variables.
    pub fn from_env() -> Self {
        let mode = env::var("MCP_MESH_TLS_MODE")
            .map(|v| TlsMode::from_str_value(&v))
            .unwrap_or(TlsMode::Off);

        let cert_path = env::var("MCP_MESH_TLS_CERT").ok().filter(|s| !s.is_empty());
        let key_path = env::var("MCP_MESH_TLS_KEY").ok().filter(|s| !s.is_empty());
        let ca_path = env::var("MCP_MESH_TLS_CA").ok().filter(|s| !s.is_empty());

        let provider = env::var("MCP_MESH_TLS_PROVIDER").ok().filter(|s| !s.is_empty());

        // Log if a provider env var is set (reserved for future use)
        if let Some(ref p) = provider {
            info!(
                "MCP_MESH_TLS_PROVIDER='{}' is set but not yet supported; using file-based certs",
                p
            );
        }

        if mode != TlsMode::Off {
            info!("TLS mode: {:?} | provider: {}",
                mode, provider.as_deref().unwrap_or("file"));
            if let Some(ref cert) = cert_path {
                debug!("TLS cert: {}", cert);
            }
            if let Some(ref ca) = ca_path {
                debug!("TLS CA: {}", ca);
            }
        } else {
            info!("TLS mode: off");
        }

        Self {
            mode,
            cert_path,
            key_path,
            ca_path,
        }
    }

    /// Check if TLS is enabled (mode != Off).
    pub fn is_enabled(&self) -> bool {
        self.mode != TlsMode::Off
    }

    /// Build a reqwest Identity from cert+key PEM files.
    ///
    /// `reqwest::Identity::from_pem()` expects concatenated cert PEM + key PEM bytes.
    /// Returns `Ok(None)` if no cert/key paths are configured.
    pub fn build_identity(&self) -> Result<Option<reqwest::Identity>, TlsError> {
        let (cert_path, key_path) = match (&self.cert_path, &self.key_path) {
            (Some(c), Some(k)) => (c, k),
            (None, None) => return Ok(None),
            (Some(_), None) => {
                return Err(TlsError::MissingConfig(
                    format!("{:?}", self.mode),
                    "MCP_MESH_TLS_KEY when MCP_MESH_TLS_CERT is set".to_string(),
                ));
            }
            (None, Some(_)) => {
                return Err(TlsError::MissingConfig(
                    format!("{:?}", self.mode),
                    "MCP_MESH_TLS_CERT when MCP_MESH_TLS_KEY is set".to_string(),
                ));
            }
        };

        let cert_pem = std::fs::read(cert_path).map_err(|e| TlsError::FileRead {
            path: cert_path.clone(),
            source: e,
        })?;
        let key_pem = std::fs::read(key_path).map_err(|e| TlsError::FileRead {
            path: key_path.clone(),
            source: e,
        })?;

        // Concatenate cert + key PEM for reqwest::Identity::from_pem
        let mut combined = cert_pem;
        combined.push(b'\n');
        combined.extend_from_slice(&key_pem);

        let identity =
            reqwest::Identity::from_pem(&combined).map_err(TlsError::IdentityParse)?;

        debug!("Built TLS client identity from {} + {}", cert_path, key_path);
        Ok(Some(identity))
    }

    /// Load CA certificate for custom trust root.
    ///
    /// Returns `Ok(None)` if no CA path is configured.
    pub fn build_ca_cert(&self) -> Result<Option<reqwest::Certificate>, TlsError> {
        let ca_path = match &self.ca_path {
            Some(p) => p,
            None => return Ok(None),
        };

        let ca_pem = std::fs::read(ca_path).map_err(|e| TlsError::FileRead {
            path: ca_path.clone(),
            source: e,
        })?;

        let cert =
            reqwest::Certificate::from_pem(&ca_pem).map_err(TlsError::CertificateParse)?;

        debug!("Loaded CA certificate from {}", ca_path);
        Ok(Some(cert))
    }
}

// =============================================================================
// Python bindings
// =============================================================================

#[cfg(feature = "python")]
#[pyfunction]
pub fn get_tls_config_py() -> String {
    let config = TlsConfig::from_env();
    let mode_str = match config.mode {
        TlsMode::Off => "off",
        TlsMode::Auto => "auto",
        TlsMode::Strict => "strict",
    };
    serde_json::json!({
        "enabled": config.is_enabled(),
        "mode": mode_str,
        "cert_path": config.cert_path,
        "key_path": config.key_path,
        "ca_path": config.ca_path,
    })
    .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use std::io::Write;
    use std::sync::Mutex;
    use tempfile::NamedTempFile;

    /// Global mutex to serialize tests that mutate environment variables.
    static TEST_ENV_LOCK: Mutex<()> = Mutex::new(());

    // Hardcoded test PEM strings (self-signed, for parsing tests only)
    const TEST_CA_CERT_PEM: &str = "-----BEGIN CERTIFICATE-----
MIIBkTCB+wIUYz3GBhRKgAoTEh9x0bBfFsMBwYEwDQYJKoZIhvcNAQELBQAwFDES
MBAGA1UEAwwJdGVzdC1tZXNoMB4XDTI1MDEwMTAwMDAwMFoXDTM1MDEwMTAwMDAw
MFowFDESMBAGA1UEAwwJdGVzdC1tZXNoMFwwDQYJKoZIhvcNAQEBBQADSwAwSAJB
AL5VWxkn6bCrhOsT+k/MFB8LNWCF7mTfGs+OAVKV6hHWfCWMIaYBLjhrPNxZueW
QLb3xjPNL+8XbFCuqN2TM00CAwEAAaMhMB8wHQYDVR0OBBYEFKn2lTl2r1G2MjfX
HaBGd+8LH9tUMA0GCSqGSIb3DQEBCwUAA0EAjSHzGBhRKgAoTEh9x0bBfFsMBwYE
-----END CERTIFICATE-----";

    const TEST_CERT_PEM: &str = "-----BEGIN CERTIFICATE-----
MIIBkTCB+wIUYz3GBhRKgAoTEh9x0bBfFsMBwYEwDQYJKoZIhvcNAQELBQAwFDES
MBAGA1UEAwwJdGVzdC1tZXNoMB4XDTI1MDEwMTAwMDAwMFoXDTM1MDEwMTAwMDAw
MFowFDESMBAGA1UEAwwJdGVzdC1tZXNoMFwwDQYJKoZIhvcNAQEBBQADSwAwSAJB
AL5VWxkn6bCrhOsT+k/MFB8LNWCF7mTfGs+OAVKV6hHWfCWMIaYBLjhrPNxZueW
QLb3xjPNL+8XbFCuqN2TM00CAwEAAaMhMB8wHQYDVR0OBBYEFKn2lTl2r1G2MjfX
HaBGd+8LH9tUMA0GCSqGSIb3DQEBCwUAA0EAjSHzGBhRKgAoTEh9x0bBfFsMBwYE
-----END CERTIFICATE-----";

    const TEST_KEY_PEM: &str = "-----BEGIN PRIVATE KEY-----
MIIBVQIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEAvlVbGSfpsKuE6xP6
T8wUHws1YIXuZN8az44BUpXqEdZ8JYwhpgEuOGs83Fm55ZAtvfGM80v7xdsUK6o3
ZZPTTQIDAQABAkEAoHqFMBSYS3p36nHJi1MlMz8HGI8mXLVPmH6nYkPRKf7l5UwZ
N1GWa3cP+KPaUG8CclOG7JGe0dJyPVHGcf/gQIhAOCWI7XRbP5fEr9NDXH5i0KU
bBt0aVzE4bFmsFJ0rOWDAiEA1+GG+gvv0Sdb7dT1r7X9VU6TUWBB9Fz/H3kFHfcr
VHECIQCttMHDou8C0xUbO0jC7PaBfbV7sP2hmQrX0WZtnz1GVwIgBnUBex3MdLqG
OE6cN7bt7uS1GdcCo1mfxirgCGzH/oECIBebsDO5CKNYzlUn71sMb0F32ssFSctH
bUWvUN+ZGbSn
-----END PRIVATE KEY-----";

    // =========================================================================
    // Tests that don't mutate environment
    // =========================================================================

    #[test]
    fn test_tls_mode_from_str() {
        assert_eq!(TlsMode::from_str_value("off"), TlsMode::Off);
        assert_eq!(TlsMode::from_str_value(""), TlsMode::Off);
        assert_eq!(TlsMode::from_str_value("auto"), TlsMode::Auto);
        assert_eq!(TlsMode::from_str_value("AUTO"), TlsMode::Auto);
        assert_eq!(TlsMode::from_str_value("strict"), TlsMode::Strict);
        assert_eq!(TlsMode::from_str_value("Strict"), TlsMode::Strict);
        assert_eq!(TlsMode::from_str_value("bogus"), TlsMode::Off);
    }

    #[test]
    fn test_is_enabled() {
        let off = TlsConfig {
            mode: TlsMode::Off,
            cert_path: None,
            key_path: None,
            ca_path: None,
        };
        assert!(!off.is_enabled());

        let auto = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: None,
        };
        assert!(auto.is_enabled());

        let strict = TlsConfig {
            mode: TlsMode::Strict,
            cert_path: None,
            key_path: None,
            ca_path: None,
        };
        assert!(strict.is_enabled());
    }

    #[test]
    fn test_build_identity_no_paths() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: None,
        };
        let result = config.build_identity().unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn test_build_identity_cert_without_key() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: Some("/tmp/cert.pem".to_string()),
            key_path: None,
            ca_path: None,
        };
        let err = config.build_identity().unwrap_err();
        assert!(err.to_string().contains("MCP_MESH_TLS_KEY"));
    }

    #[test]
    fn test_build_identity_key_without_cert() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: Some("/tmp/key.pem".to_string()),
            ca_path: None,
        };
        let err = config.build_identity().unwrap_err();
        assert!(err.to_string().contains("MCP_MESH_TLS_CERT"));
    }

    #[test]
    fn test_build_identity_missing_cert_file() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: Some("/nonexistent/cert.pem".to_string()),
            key_path: Some("/nonexistent/key.pem".to_string()),
            ca_path: None,
        };
        let err = config.build_identity().unwrap_err();
        match &err {
            TlsError::FileRead { path, .. } => {
                assert_eq!(path, "/nonexistent/cert.pem");
            }
            _ => panic!("Expected FileRead error, got: {:?}", err),
        }
    }

    #[test]
    fn test_build_ca_cert_no_path() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: None,
        };
        let result = config.build_ca_cert().unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn test_build_ca_cert_missing_file() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: Some("/nonexistent/ca.pem".to_string()),
        };
        let err = config.build_ca_cert().unwrap_err();
        match &err {
            TlsError::FileRead { path, .. } => {
                assert_eq!(path, "/nonexistent/ca.pem");
            }
            _ => panic!("Expected FileRead error, got: {:?}", err),
        }
    }

    #[test]
    fn test_build_identity_with_temp_files() {
        // Write test PEM data to temp files
        let mut cert_file = NamedTempFile::new().unwrap();
        cert_file.write_all(TEST_CERT_PEM.as_bytes()).unwrap();
        cert_file.flush().unwrap();

        let mut key_file = NamedTempFile::new().unwrap();
        key_file.write_all(TEST_KEY_PEM.as_bytes()).unwrap();
        key_file.flush().unwrap();

        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: Some(cert_file.path().to_str().unwrap().to_string()),
            key_path: Some(key_file.path().to_str().unwrap().to_string()),
            ca_path: None,
        };

        // The test PEM strings are syntactically valid PEM but may not parse
        // as valid crypto material. We verify the file-reading path works;
        // a parse error from reqwest is acceptable here.
        let result = config.build_identity();
        match result {
            Ok(Some(_)) => {} // valid parse (unlikely with fake certs)
            Err(TlsError::IdentityParse(_)) => {} // expected: fake cert data
            other => panic!("Unexpected result: {:?}", other),
        }
    }

    #[test]
    fn test_build_ca_cert_with_temp_file() {
        let mut ca_file = NamedTempFile::new().unwrap();
        ca_file.write_all(TEST_CA_CERT_PEM.as_bytes()).unwrap();
        ca_file.flush().unwrap();

        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: Some(ca_file.path().to_str().unwrap().to_string()),
        };

        let result = config.build_ca_cert();
        match result {
            Ok(Some(_)) => {}
            Err(TlsError::CertificateParse(_)) => {} // expected with fake certs
            other => panic!("Unexpected result: {:?}", other),
        }
    }

    // =========================================================================
    // Tests that mutate environment (require lock)
    // =========================================================================

    #[test]
    fn test_from_env_no_vars() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        env::remove_var("MCP_MESH_TLS_MODE");
        env::remove_var("MCP_MESH_TLS_CERT");
        env::remove_var("MCP_MESH_TLS_KEY");
        env::remove_var("MCP_MESH_TLS_CA");
        env::remove_var("MCP_MESH_TLS_PROVIDER");

        let config = TlsConfig::from_env();
        assert_eq!(config.mode, TlsMode::Off);
        assert!(config.cert_path.is_none());
        assert!(config.key_path.is_none());
        assert!(config.ca_path.is_none());
        assert!(!config.is_enabled());
    }

    #[test]
    fn test_from_env_strict_mode() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        env::set_var("MCP_MESH_TLS_MODE", "strict");
        env::remove_var("MCP_MESH_TLS_CERT");
        env::remove_var("MCP_MESH_TLS_KEY");
        env::remove_var("MCP_MESH_TLS_CA");
        env::remove_var("MCP_MESH_TLS_PROVIDER");

        let config = TlsConfig::from_env();
        assert_eq!(config.mode, TlsMode::Strict);
        assert!(config.is_enabled());

        env::remove_var("MCP_MESH_TLS_MODE");
    }

    #[test]
    fn test_from_env_with_cert_paths() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        env::set_var("MCP_MESH_TLS_MODE", "auto");
        env::set_var("MCP_MESH_TLS_CERT", "/etc/mesh/cert.pem");
        env::set_var("MCP_MESH_TLS_KEY", "/etc/mesh/key.pem");
        env::set_var("MCP_MESH_TLS_CA", "/etc/mesh/ca.pem");
        env::remove_var("MCP_MESH_TLS_PROVIDER");

        let config = TlsConfig::from_env();
        assert_eq!(config.mode, TlsMode::Auto);
        assert_eq!(config.cert_path.as_deref(), Some("/etc/mesh/cert.pem"));
        assert_eq!(config.key_path.as_deref(), Some("/etc/mesh/key.pem"));
        assert_eq!(config.ca_path.as_deref(), Some("/etc/mesh/ca.pem"));

        env::remove_var("MCP_MESH_TLS_MODE");
        env::remove_var("MCP_MESH_TLS_CERT");
        env::remove_var("MCP_MESH_TLS_KEY");
        env::remove_var("MCP_MESH_TLS_CA");
    }

    #[test]
    fn test_from_env_empty_values_treated_as_none() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        env::set_var("MCP_MESH_TLS_MODE", "auto");
        env::set_var("MCP_MESH_TLS_CERT", "");
        env::set_var("MCP_MESH_TLS_KEY", "");
        env::set_var("MCP_MESH_TLS_CA", "");
        env::remove_var("MCP_MESH_TLS_PROVIDER");

        let config = TlsConfig::from_env();
        assert_eq!(config.mode, TlsMode::Auto);
        assert!(config.cert_path.is_none());
        assert!(config.key_path.is_none());
        assert!(config.ca_path.is_none());

        env::remove_var("MCP_MESH_TLS_MODE");
        env::remove_var("MCP_MESH_TLS_CERT");
        env::remove_var("MCP_MESH_TLS_KEY");
        env::remove_var("MCP_MESH_TLS_CA");
    }
}
