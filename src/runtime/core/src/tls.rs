//! TLS configuration for agent-to-registry communication.
//!
//! Supports pluggable credential providers via the `CredentialProvider` trait.
//! Built-in providers:
//! - `file` (default) — reads PEM files from disk
//! - `vault` — fetches certificates from HashiCorp Vault PKI
//!
//! Environment variables:
//! - `MCP_MESH_TLS_MODE` - TLS mode: "off" (default), "auto", "strict"
//! - `MCP_MESH_TLS_CERT` - Path to client certificate PEM file
//! - `MCP_MESH_TLS_KEY` - Path to client private key PEM file
//! - `MCP_MESH_TLS_CA` - Path to CA certificate PEM file
//! - `MCP_MESH_TLS_PROVIDER` - Credential provider: "file" (default) or "vault"

use std::env;
use std::sync::OnceLock;

use async_trait::async_trait;
use thiserror::Error;
use tracing::{debug, info, warn};

#[cfg(feature = "python")]
use pyo3::prelude::*;

// Global resolved TLS config -- written by prepare_tls(), read by get_tls_config and AgentRuntime
static RESOLVED_CONFIG: OnceLock<TlsConfig> = OnceLock::new();
static RESOLVE_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

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

    #[error("Vault error: {0}")]
    VaultError(String),

    #[error("Provider error: {0}")]
    ProviderError(String),
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

// =============================================================================
// Credential provider trait and types
// =============================================================================

/// In-memory TLS credentials (PEM content).
#[derive(Debug, Clone)]
pub struct TlsCredentials {
    pub cert_pem: Vec<u8>,
    pub key_pem: Vec<u8>,
    pub ca_pem: Option<Vec<u8>>,
}

/// Trait for pluggable TLS credential providers.
#[async_trait]
pub trait CredentialProvider: Send + Sync + std::fmt::Debug {
    async fn get_credentials(&self, agent_name: &str, advertised_host: &str) -> Result<TlsCredentials, TlsError>;
}

/// File-based credential provider — reads PEM files from disk.
#[derive(Debug)]
pub struct FileProvider {
    cert_path: String,
    key_path: String,
    ca_path: Option<String>,
}

impl FileProvider {
    pub fn from_env() -> Result<Self, TlsError> {
        let cert_path = env::var("MCP_MESH_TLS_CERT").ok().filter(|s| !s.is_empty());
        let key_path = env::var("MCP_MESH_TLS_KEY").ok().filter(|s| !s.is_empty());
        let ca_path = env::var("MCP_MESH_TLS_CA").ok().filter(|s| !s.is_empty());

        match (&cert_path, &key_path) {
            (Some(_), None) => {
                return Err(TlsError::MissingConfig(
                    "file".into(),
                    "MCP_MESH_TLS_KEY when MCP_MESH_TLS_CERT is set".into(),
                ))
            }
            (None, Some(_)) => {
                return Err(TlsError::MissingConfig(
                    "file".into(),
                    "MCP_MESH_TLS_CERT when MCP_MESH_TLS_KEY is set".into(),
                ))
            }
            (None, None) => {
                return Err(TlsError::MissingConfig(
                    "file".into(),
                    "MCP_MESH_TLS_CERT and MCP_MESH_TLS_KEY".into(),
                ))
            }
            _ => {}
        }

        Ok(Self {
            cert_path: cert_path.unwrap(),
            key_path: key_path.unwrap(),
            ca_path,
        })
    }
}

#[async_trait]
impl CredentialProvider for FileProvider {
    async fn get_credentials(&self, _agent_name: &str, _advertised_host: &str) -> Result<TlsCredentials, TlsError> {
        let cert_pem = std::fs::read(&self.cert_path).map_err(|e| TlsError::FileRead {
            path: self.cert_path.clone(),
            source: e,
        })?;
        let key_pem = std::fs::read(&self.key_path).map_err(|e| TlsError::FileRead {
            path: self.key_path.clone(),
            source: e,
        })?;
        let ca_pem = match &self.ca_path {
            Some(p) => Some(std::fs::read(p).map_err(|e| TlsError::FileRead {
                path: p.clone(),
                source: e,
            })?),
            None => None,
        };
        Ok(TlsCredentials {
            cert_pem,
            key_pem,
            ca_pem,
        })
    }
}

/// Create a credential provider by name.
pub fn create_provider(name: &str) -> Result<Box<dyn CredentialProvider>, TlsError> {
    match name {
        "file" => Ok(Box::new(FileProvider::from_env()?)),
        "vault" => Ok(Box::new(crate::vault::VaultProvider::from_env()?)),
        other => Err(TlsError::ProviderError(format!(
            "Unknown TLS provider: {}",
            other
        ))),
    }
}

// =============================================================================
// Secure temp file helpers
// =============================================================================

/// Write TLS credentials to secure temporary files.
///
/// Security properties:
/// - Directory: 0700 (owner-only access)
/// - Files: 0600 (owner read/write only)
/// - Prefers /dev/shm (tmpfs) on Linux so private keys never touch physical disk
/// - Named with PID for process isolation
fn write_credentials_to_files(
    creds: &TlsCredentials,
    agent_name: &str,
) -> Result<(String, String, Option<String>), TlsError> {
    let base = if cfg!(target_os = "linux") {
        let shm = std::path::Path::new("/dev/shm");
        if shm.exists() && shm.is_dir() {
            "/dev/shm".to_string()
        } else {
            std::env::temp_dir().to_string_lossy().to_string()
        }
    } else {
        std::env::temp_dir().to_string_lossy().to_string()
    };

    // Sanitize agent_name to prevent path traversal
    let safe_name: String = agent_name
        .chars()
        .map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .collect();

    let dir = format!("{}/mcp-mesh-tls-{}-{}", base, safe_name, std::process::id());
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        std::fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&dir)
            .map_err(|e| {
                TlsError::ProviderError(format!("Failed to create TLS temp dir: {}", e))
            })?;
    }
    #[cfg(not(unix))]
    {
        std::fs::create_dir_all(&dir).map_err(|e| {
            TlsError::ProviderError(format!("Failed to create TLS temp dir: {}", e))
        })?;
    }

    let cert_path = format!("{}/cert.pem", dir);
    let key_path = format!("{}/key.pem", dir);

    write_secure_file(&cert_path, &creds.cert_pem)?;
    write_secure_file(&key_path, &creds.key_pem)?;

    let ca_path = if let Some(ref ca) = creds.ca_pem {
        let p = format!("{}/ca.pem", dir);
        write_secure_file(&p, ca)?;
        Some(p)
    } else {
        None
    };

    info!("TLS credentials written to secure temp files in {}", dir);
    Ok((cert_path, key_path, ca_path))
}

fn write_secure_file(path: &str, content: &[u8]) -> Result<(), TlsError> {
    use std::io::Write;

    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)
            .map_err(|e| TlsError::ProviderError(format!("Failed to create {}: {}", path, e)))?;
        file.write_all(content)
            .map_err(|e| TlsError::ProviderError(format!("Failed to write {}: {}", path, e)))?;
    }
    #[cfg(not(unix))]
    {
        std::fs::write(path, content)
            .map_err(|e| TlsError::ProviderError(format!("Failed to write {}: {}", path, e)))?;
    }
    Ok(())
}

// =============================================================================
// TLS configuration
// =============================================================================

/// TLS configuration resolved from environment variables.
#[derive(Debug, Clone)]
pub struct TlsConfig {
    pub mode: TlsMode,
    pub cert_path: Option<String>,
    pub key_path: Option<String>,
    pub ca_path: Option<String>,
    pub provider: String,
    pub credentials: Option<TlsCredentials>,
}

impl TlsConfig {
    /// Resolve TLS config from environment variables (synchronous, backward-compatible).
    ///
    /// This is the original sync path. It reads file paths from env but does NOT
    /// invoke any credential provider. Use `resolve()` for the async provider path.
    pub fn from_env() -> Self {
        let mode = env::var("MCP_MESH_TLS_MODE")
            .map(|v| TlsMode::from_str_value(&v))
            .unwrap_or(TlsMode::Off);

        let cert_path = env::var("MCP_MESH_TLS_CERT").ok().filter(|s| !s.is_empty());
        let key_path = env::var("MCP_MESH_TLS_KEY").ok().filter(|s| !s.is_empty());
        let ca_path = env::var("MCP_MESH_TLS_CA").ok().filter(|s| !s.is_empty());

        let provider = env::var("MCP_MESH_TLS_PROVIDER")
            .ok()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "file".to_string());

        if mode != TlsMode::Off {
            info!("TLS mode: {:?} | provider: {}", mode, provider);
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
            provider,
            credentials: None,
        }
    }

    /// Resolve TLS config asynchronously using the configured credential provider.
    ///
    /// This is the preferred path for runtime initialization. It reads TLS mode
    /// and provider from env, then calls the provider to fetch credentials.
    /// For non-file providers (e.g., Vault), credentials are written to secure
    /// temp files so language runtimes (uvicorn, httpx) can reference them by path.
    /// Results are cached globally via RESOLVED_CONFIG.
    pub async fn resolve(agent_name: &str) -> Result<Self, TlsError> {
        // Return cached config if already resolved (e.g., by prepare_blocking at startup)
        if let Some(config) = RESOLVED_CONFIG.get() {
            return Ok(config.clone());
        }

        let mode = env::var("MCP_MESH_TLS_MODE")
            .map(|v| TlsMode::from_str_value(&v))
            .unwrap_or(TlsMode::Off);

        if mode == TlsMode::Off {
            info!("TLS mode: off");
            let config = Self {
                mode,
                cert_path: None,
                key_path: None,
                ca_path: None,
                provider: "file".to_string(),
                credentials: None,
            };
            let _ = RESOLVED_CONFIG.set(config.clone());
            return Ok(config);
        }

        let provider_name = env::var("MCP_MESH_TLS_PROVIDER")
            .ok()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "file".to_string());

        info!(
            "TLS mode: {:?} | provider: {} | resolving credentials for '{}'",
            mode, provider_name, agent_name
        );

        let provider = match create_provider(&provider_name) {
            Ok(p) => p,
            Err(e) => {
                if provider_name == "file" {
                    // File provider fails when cert/key not set — fall back to
                    // no-credentials config (agent can still connect without mTLS,
                    // e.g., for strict mode rejection testing).
                    warn!("File provider init failed ({}), continuing without credentials", e);
                    let config = Self::from_env();
                    let _ = RESOLVED_CONFIG.set(config.clone());
                    return Ok(config);
                }
                return Err(e);
            }
        };
        let advertised_host = env::var("MCP_MESH_HTTP_HOST")
            .ok()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| crate::config::auto_detect_external_ip());
        let credentials = provider.get_credentials(agent_name, &advertised_host).await?;

        // For non-file providers, write credentials to secure temp files
        // so language runtimes (uvicorn, httpx, etc.) can use them by path
        let (cert_path, key_path, ca_path) = if provider_name != "file" {
            let (c, k, ca) = write_credentials_to_files(&credentials, agent_name)?;
            (Some(c), Some(k), ca)
        } else {
            // File provider: use the original paths from env vars
            (
                env::var("MCP_MESH_TLS_CERT").ok().filter(|s| !s.is_empty()),
                env::var("MCP_MESH_TLS_KEY").ok().filter(|s| !s.is_empty()),
                env::var("MCP_MESH_TLS_CA").ok().filter(|s| !s.is_empty()),
            )
        };

        let config = Self {
            mode,
            cert_path,
            key_path,
            ca_path,
            provider: provider_name,
            credentials: Some(credentials),
        };

        let _ = RESOLVED_CONFIG.set(config.clone());
        Ok(config)
    }

    /// Check if TLS is enabled (mode != Off).
    pub fn is_enabled(&self) -> bool {
        self.mode != TlsMode::Off
    }

    /// Get the globally resolved TLS config, or fall back to from_env().
    ///
    /// Used by `get_tls_config_py()` and FFI `mesh_get_tls_config()`
    /// to return resolved paths (including temp file paths from Vault provider).
    pub fn get_resolved_or_env() -> Self {
        match RESOLVED_CONFIG.get() {
            Some(config) => config.clone(),
            None => Self::from_env(),
        }
    }

    /// Get the cached resolved config, if any.
    pub fn get_resolved_config() -> Option<Self> {
        RESOLVED_CONFIG.get().cloned()
    }

    /// Resolve TLS config synchronously (blocks on async).
    ///
    /// Called early in agent startup (before HTTP server) to ensure
    /// credentials are fetched and temp files are written.
    /// Results are cached globally via RESOLVED_CONFIG.
    ///
    /// Uses RESOLVE_LOCK to prevent duplicate calls from concurrent threads.
    /// Does NOT call resolve() to avoid deadlock (mutex + block_on + async mutex).
    pub fn prepare_blocking(agent_name: &str) -> Result<Self, TlsError> {
        // Serialize concurrent sync callers (e.g., multiple Python threads)
        let _guard = RESOLVE_LOCK.lock().unwrap_or_else(|e| e.into_inner());

        // Already resolved by another thread
        if let Some(config) = RESOLVED_CONFIG.get() {
            return Ok(config.clone());
        }

        let mode = env::var("MCP_MESH_TLS_MODE")
            .map(|v| TlsMode::from_str_value(&v))
            .unwrap_or(TlsMode::Off);

        if mode == TlsMode::Off {
            let config = Self::from_env();
            let _ = RESOLVED_CONFIG.set(config.clone());
            return Ok(config);
        }

        // Check if we're already inside a Tokio runtime (would panic on block_on)
        if tokio::runtime::Handle::try_current().is_ok() {
            let provider_name = env::var("MCP_MESH_TLS_PROVIDER")
                .ok()
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| "file".to_string());
            if provider_name != "file" {
                return Err(TlsError::ProviderError(format!(
                    "prepare_blocking called from within Tokio runtime but provider '{}' requires async I/O; use resolve() instead",
                    provider_name
                )));
            }
            warn!("prepare_blocking called from within Tokio runtime; falling back to from_env()");
            return Ok(Self::from_env());
        }

        let provider_name = env::var("MCP_MESH_TLS_PROVIDER")
            .ok()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "file".to_string());

        info!(
            "TLS mode: {:?} | provider: {} | resolving credentials for '{}'",
            mode, provider_name, agent_name
        );

        let provider = match create_provider(&provider_name) {
            Ok(p) => p,
            Err(e) => {
                if provider_name == "file" {
                    warn!("File provider init failed ({}), continuing without credentials", e);
                    let config = Self::from_env();
                    let _ = RESOLVED_CONFIG.set(config.clone());
                    return Ok(config);
                }
                return Err(e);
            }
        };

        let advertised_host = env::var("MCP_MESH_HTTP_HOST")
            .ok()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| crate::config::auto_detect_external_ip());

        // Create a Tokio runtime for the async provider call
        let rt = tokio::runtime::Runtime::new().map_err(|e| {
            TlsError::ProviderError(format!("Failed to create tokio runtime: {}", e))
        })?;
        let credentials = rt.block_on(provider.get_credentials(agent_name, &advertised_host))?;

        // Write credentials to secure temp files for non-file providers
        let (cert_path, key_path, ca_path) = if provider_name != "file" {
            let (c, k, ca) = write_credentials_to_files(&credentials, agent_name)?;
            (Some(c), Some(k), ca)
        } else {
            (
                env::var("MCP_MESH_TLS_CERT").ok().filter(|s| !s.is_empty()),
                env::var("MCP_MESH_TLS_KEY").ok().filter(|s| !s.is_empty()),
                env::var("MCP_MESH_TLS_CA").ok().filter(|s| !s.is_empty()),
            )
        };

        let config = Self {
            mode,
            cert_path,
            key_path,
            ca_path,
            provider: provider_name,
            credentials: Some(credentials),
        };

        let _ = RESOLVED_CONFIG.set(config.clone());
        Ok(config)
    }

    /// Clean up temporary TLS credential files.
    ///
    /// Should be called during agent shutdown. Safe to call multiple times.
    pub fn cleanup_tls_files() {
        if let Some(config) = RESOLVED_CONFIG.get() {
            if config.provider == "file" {
                return; // File provider uses user-provided paths, don't delete
            }
            if let Some(ref cert) = config.cert_path {
                let dir = std::path::Path::new(cert).parent();
                if let Some(dir) = dir {
                    if dir.to_string_lossy().contains("mcp-mesh-tls-") {
                        if let Err(e) = std::fs::remove_dir_all(dir) {
                            warn!("Failed to clean up TLS temp dir {:?}: {}", dir, e);
                        } else {
                            info!("Cleaned up TLS temp files in {:?}", dir);
                        }
                    }
                }
            }
        }
    }

    /// Build a reqwest Identity from credentials or cert+key PEM files.
    ///
    /// If `credentials` is populated (from `resolve()`), uses in-memory PEM data.
    /// Otherwise falls back to reading file paths (from `from_env()`).
    ///
    /// `reqwest::Identity::from_pem()` expects concatenated cert PEM + key PEM bytes.
    /// Returns `Ok(None)` if no cert/key paths are configured and no credentials available.
    pub fn build_identity(&self) -> Result<Option<reqwest::Identity>, TlsError> {
        if let Some(ref creds) = self.credentials {
            let mut combined = creds.cert_pem.clone();
            combined.push(b'\n');
            combined.extend_from_slice(&creds.key_pem);

            let identity =
                reqwest::Identity::from_pem(&combined).map_err(TlsError::IdentityParse)?;

            debug!("Built TLS client identity from provider credentials");
            return Ok(Some(identity));
        }

        // Fall back to file paths
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
    /// If `credentials` is populated (from `resolve()`), uses in-memory CA PEM data.
    /// Otherwise falls back to reading the CA file path (from `from_env()`).
    ///
    /// Returns `Ok(None)` if no CA path is configured and no CA credentials available.
    pub fn build_ca_cert(&self) -> Result<Option<reqwest::Certificate>, TlsError> {
        if let Some(ref creds) = self.credentials {
            if let Some(ref ca_pem) = creds.ca_pem {
                let cert = reqwest::Certificate::from_pem(ca_pem)
                    .map_err(TlsError::CertificateParse)?;

                debug!("Loaded CA certificate from provider credentials");
                return Ok(Some(cert));
            }
        }

        // Fall back to file path
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
    let config = TlsConfig::get_resolved_or_env();
    let mode_str = match config.mode {
        TlsMode::Off => "off",
        TlsMode::Auto => "auto",
        TlsMode::Strict => "strict",
    };
    serde_json::json!({
        "enabled": config.is_enabled(),
        "mode": mode_str,
        "provider": config.provider,
        "cert_path": config.cert_path,
        "key_path": config.key_path,
        "ca_path": config.ca_path,
    })
    .to_string()
}

#[cfg(feature = "python")]
#[pyfunction]
pub fn prepare_tls_py(agent_name: String) -> PyResult<String> {
    let config = TlsConfig::prepare_blocking(&agent_name)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
    let mode_str = match config.mode {
        TlsMode::Off => "off",
        TlsMode::Auto => "auto",
        TlsMode::Strict => "strict",
    };
    Ok(serde_json::json!({
        "enabled": config.is_enabled(),
        "mode": mode_str,
        "provider": config.provider,
        "cert_path": config.cert_path,
        "key_path": config.key_path,
        "ca_path": config.ca_path,
    })
    .to_string())
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
            provider: "file".to_string(),
            credentials: None,
        };
        assert!(!off.is_enabled());

        let auto = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: None,
            provider: "file".to_string(),
            credentials: None,
        };
        assert!(auto.is_enabled());

        let strict = TlsConfig {
            mode: TlsMode::Strict,
            cert_path: None,
            key_path: None,
            ca_path: None,
            provider: "file".to_string(),
            credentials: None,
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
            provider: "file".to_string(),
            credentials: None,
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
            provider: "file".to_string(),
            credentials: None,
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
            provider: "file".to_string(),
            credentials: None,
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
            provider: "file".to_string(),
            credentials: None,
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
            provider: "file".to_string(),
            credentials: None,
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
            provider: "file".to_string(),
            credentials: None,
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
            provider: "file".to_string(),
            credentials: None,
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
            provider: "file".to_string(),
            credentials: None,
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

    // =========================================================================
    // Provider factory tests
    // =========================================================================

    #[test]
    fn test_create_provider_file() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        env::set_var("MCP_MESH_TLS_CERT", "/tmp/cert.pem");
        env::set_var("MCP_MESH_TLS_KEY", "/tmp/key.pem");
        env::remove_var("MCP_MESH_TLS_CA");

        let result = create_provider("file");
        assert!(result.is_ok());

        env::remove_var("MCP_MESH_TLS_CERT");
        env::remove_var("MCP_MESH_TLS_KEY");
    }

    #[test]
    fn test_create_provider_vault() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        // Without required env vars, VaultProvider::from_env should error
        env::remove_var("MCP_MESH_VAULT_ADDR");
        env::remove_var("MCP_MESH_VAULT_PKI_PATH");
        env::remove_var("VAULT_TOKEN");

        let result = create_provider("vault");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("MCP_MESH_VAULT_ADDR"));
    }

    #[test]
    fn test_create_provider_unknown() {
        let result = create_provider("spire");
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.to_string().contains("Unknown TLS provider: spire"));
    }

    // =========================================================================
    // Credentials-based build tests
    // =========================================================================

    #[test]
    fn test_tls_credentials_build_identity() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: None,
            provider: "vault".to_string(),
            credentials: Some(TlsCredentials {
                cert_pem: TEST_CERT_PEM.as_bytes().to_vec(),
                key_pem: TEST_KEY_PEM.as_bytes().to_vec(),
                ca_pem: None,
            }),
        };

        let result = config.build_identity();
        match result {
            Ok(Some(_)) => {}
            Err(TlsError::IdentityParse(_)) => {} // expected with fake certs
            other => panic!("Unexpected result: {:?}", other),
        }
    }

    #[test]
    fn test_tls_credentials_build_ca_cert() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: None,
            provider: "vault".to_string(),
            credentials: Some(TlsCredentials {
                cert_pem: TEST_CERT_PEM.as_bytes().to_vec(),
                key_pem: TEST_KEY_PEM.as_bytes().to_vec(),
                ca_pem: Some(TEST_CA_CERT_PEM.as_bytes().to_vec()),
            }),
        };

        let result = config.build_ca_cert();
        match result {
            Ok(Some(_)) => {}
            Err(TlsError::CertificateParse(_)) => {} // expected with fake certs
            other => panic!("Unexpected result: {:?}", other),
        }
    }

    #[test]
    fn test_tls_credentials_no_ca_falls_through() {
        let config = TlsConfig {
            mode: TlsMode::Auto,
            cert_path: None,
            key_path: None,
            ca_path: None,
            provider: "vault".to_string(),
            credentials: Some(TlsCredentials {
                cert_pem: TEST_CERT_PEM.as_bytes().to_vec(),
                key_pem: TEST_KEY_PEM.as_bytes().to_vec(),
                ca_pem: None,
            }),
        };

        // No CA in credentials and no ca_path, should return None
        let result = config.build_ca_cert().unwrap();
        assert!(result.is_none());
    }

    // =========================================================================
    // Secure temp file tests
    // =========================================================================

    #[test]
    fn test_write_secure_file() {
        let dir = std::env::temp_dir();
        let path = format!("{}/mesh-test-secure-{}", dir.display(), std::process::id());
        write_secure_file(&path, b"test content").unwrap();

        let content = std::fs::read_to_string(&path).unwrap();
        assert_eq!(content, "test content");

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let perms = std::fs::metadata(&path).unwrap().permissions();
            assert_eq!(perms.mode() & 0o777, 0o600);
        }

        std::fs::remove_file(&path).unwrap();
    }

    #[test]
    fn test_write_credentials_to_files() {
        let creds = TlsCredentials {
            cert_pem: b"-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----".to_vec(),
            key_pem: b"-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----".to_vec(),
            ca_pem: Some(b"-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----".to_vec()),
        };

        let (cert_path, key_path, ca_path) = write_credentials_to_files(&creds, "test-agent").unwrap();

        assert!(std::path::Path::new(&cert_path).exists());
        assert!(std::path::Path::new(&key_path).exists());
        assert!(ca_path.is_some());
        assert!(std::path::Path::new(ca_path.as_ref().unwrap()).exists());

        // Verify content
        let cert_content = std::fs::read(&cert_path).unwrap();
        assert_eq!(cert_content, creds.cert_pem);
        let key_content = std::fs::read(&key_path).unwrap();
        assert_eq!(key_content, creds.key_pem);

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let key_perms = std::fs::metadata(&key_path).unwrap().permissions();
            assert_eq!(key_perms.mode() & 0o777, 0o600, "Key file should be 0600");

            let dir = std::path::Path::new(&cert_path).parent().unwrap();
            let dir_perms = std::fs::metadata(dir).unwrap().permissions();
            assert_eq!(dir_perms.mode() & 0o777, 0o700, "Dir should be 0700");
        }

        // Cleanup
        let dir = std::path::Path::new(&cert_path).parent().unwrap();
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn test_write_credentials_to_files_no_ca() {
        let creds = TlsCredentials {
            cert_pem: b"cert-data".to_vec(),
            key_pem: b"key-data".to_vec(),
            ca_pem: None,
        };

        let (cert_path, key_path, ca_path) = write_credentials_to_files(&creds, "no-ca-agent").unwrap();

        assert!(std::path::Path::new(&cert_path).exists());
        assert!(std::path::Path::new(&key_path).exists());
        assert!(ca_path.is_none());

        let dir = std::path::Path::new(&cert_path).parent().unwrap();
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn test_get_resolved_or_env_fallback() {
        // When RESOLVED_CONFIG has not been set for this process,
        // get_resolved_or_env should fall back to from_env().
        // Note: OnceLock is global, so if another test set it, this test
        // just verifies it returns a valid config without panicking.
        let config = TlsConfig::get_resolved_or_env();
        // Should always return a valid config
        assert!(config.provider.len() > 0);
    }
}
