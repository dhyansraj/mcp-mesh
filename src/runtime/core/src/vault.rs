//! Vault credential provider — fetches TLS certificates from HashiCorp Vault PKI.
//!
//! Reads configuration from environment variables:
//! - `MCP_MESH_VAULT_ADDR` — Vault server URL (required)
//! - `MCP_MESH_VAULT_PKI_PATH` — PKI issue path (required, e.g., "pki_int/issue/mesh-agent")
//! - `VAULT_TOKEN` — Vault authentication token (required)
//! - `MCP_MESH_TRUST_DOMAIN` — Trust domain for CN (default: "mcp-mesh.local")
//! - `MCP_MESH_VAULT_TTL` — Certificate TTL (default: "24h")

use async_trait::async_trait;
use serde::Deserialize;
use tracing::{debug, info};

use crate::tls::{CredentialProvider, TlsCredentials, TlsError};

#[derive(Debug)]
pub struct VaultProvider {
    vault_addr: String,
    pki_path: String,
    token: String,
    trust_domain: String,
    ttl: String,
}

#[derive(Deserialize)]
struct VaultResponse {
    data: VaultCertData,
}

#[derive(Deserialize)]
struct VaultCertData {
    certificate: String,
    private_key: String,
    #[serde(default)]
    ca_chain: Vec<String>,
    #[serde(default)]
    issuing_ca: String,
}

impl VaultProvider {
    pub fn from_env() -> Result<Self, TlsError> {
        let vault_addr = crate::tls::get_env_string("MCP_MESH_VAULT_ADDR")
            .ok_or_else(|| {
                TlsError::MissingConfig("vault".into(), "MCP_MESH_VAULT_ADDR".into())
            })?;
        let pki_path = crate::tls::get_env_string("MCP_MESH_VAULT_PKI_PATH")
            .ok_or_else(|| {
                TlsError::MissingConfig("vault".into(), "MCP_MESH_VAULT_PKI_PATH".into())
            })?;
        let token = crate::tls::get_env_string("VAULT_TOKEN")
            .ok_or_else(|| TlsError::MissingConfig("vault".into(), "VAULT_TOKEN".into()))?;
        let trust_domain = crate::tls::get_env_string("MCP_MESH_TRUST_DOMAIN")
            .unwrap_or_else(|| "mcp-mesh.local".to_string());
        let ttl = crate::tls::get_env_string("MCP_MESH_VAULT_TTL")
            .unwrap_or_else(|| "24h".to_string());

        Ok(Self {
            vault_addr,
            pki_path,
            token,
            trust_domain,
            ttl,
        })
    }
}

#[async_trait]
impl CredentialProvider for VaultProvider {
    async fn get_credentials(&self, agent_name: &str, advertised_host: &str) -> Result<TlsCredentials, TlsError> {
        let common_name = format!("{}.{}", agent_name, self.trust_domain);
        let url = format!(
            "{}/v1/{}",
            self.vault_addr.trim_end_matches('/'),
            self.pki_path
        );

        info!("Requesting certificate from Vault for CN={}", common_name);
        debug!("Vault PKI URL: {}", url);

        // Determine if advertised_host is an IP or hostname for proper SAN
        let is_ip = advertised_host.parse::<std::net::IpAddr>().is_ok();

        let mut request_body = serde_json::json!({
            "common_name": common_name,
            "ttl": self.ttl,
        });

        if is_ip {
            request_body["ip_sans"] = serde_json::Value::String(advertised_host.to_string());
            info!("Including IP SAN: {}", advertised_host);
        } else if !advertised_host.is_empty() {
            request_body["alt_names"] = serde_json::Value::String(advertised_host.to_string());
            info!("Including DNS SAN: {}", advertised_host);
        }

        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .connect_timeout(std::time::Duration::from_secs(10))
            .build()
            .map_err(|e| TlsError::VaultError(format!("Failed to create HTTP client: {}", e)))?;
        let response = client
            .post(&url)
            .header("X-Vault-Token", &self.token)
            .json(&request_body)
            .send()
            .await
            .map_err(|e| TlsError::VaultError(format!("Failed to contact Vault: {}", e)))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(TlsError::VaultError(format!(
                "Vault returned {}: {}",
                status, body
            )));
        }

        let vault_resp: VaultResponse = response
            .json()
            .await
            .map_err(|e| TlsError::VaultError(format!("Failed to parse Vault response: {}", e)))?;

        let ca_pem = if !vault_resp.data.ca_chain.is_empty() {
            Some(vault_resp.data.ca_chain.join("\n").into_bytes())
        } else if !vault_resp.data.issuing_ca.is_empty() {
            Some(vault_resp.data.issuing_ca.into_bytes())
        } else {
            None
        };

        info!("Certificate obtained from Vault for CN={}", common_name);

        Ok(TlsCredentials {
            cert_pem: vault_resp.data.certificate.into_bytes(),
            key_pem: vault_resp.data.private_key.into_bytes(),
            ca_pem,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static TEST_ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn test_vault_provider_missing_env() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        std::env::remove_var("MCP_MESH_VAULT_ADDR");
        std::env::remove_var("MCP_MESH_VAULT_PKI_PATH");
        std::env::remove_var("VAULT_TOKEN");

        let result = VaultProvider::from_env();
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.to_string().contains("MCP_MESH_VAULT_ADDR"));
    }

    #[test]
    fn test_vault_provider_missing_pki_path() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        std::env::set_var("MCP_MESH_VAULT_ADDR", "http://vault:8200");
        std::env::remove_var("MCP_MESH_VAULT_PKI_PATH");
        std::env::remove_var("VAULT_TOKEN");

        let result = VaultProvider::from_env();
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.to_string().contains("MCP_MESH_VAULT_PKI_PATH"));

        std::env::remove_var("MCP_MESH_VAULT_ADDR");
    }

    #[test]
    fn test_vault_provider_missing_token() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        std::env::set_var("MCP_MESH_VAULT_ADDR", "http://vault:8200");
        std::env::set_var("MCP_MESH_VAULT_PKI_PATH", "pki_int/issue/mesh-agent");
        std::env::remove_var("VAULT_TOKEN");

        let result = VaultProvider::from_env();
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.to_string().contains("VAULT_TOKEN"));

        std::env::remove_var("MCP_MESH_VAULT_ADDR");
        std::env::remove_var("MCP_MESH_VAULT_PKI_PATH");
    }

    #[test]
    fn test_vault_provider_defaults() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        std::env::set_var("MCP_MESH_VAULT_ADDR", "http://vault:8200");
        std::env::set_var("MCP_MESH_VAULT_PKI_PATH", "pki_int/issue/mesh-agent");
        std::env::set_var("VAULT_TOKEN", "s.test-token");
        std::env::remove_var("MCP_MESH_TRUST_DOMAIN");
        std::env::remove_var("MCP_MESH_VAULT_TTL");

        let provider = VaultProvider::from_env().unwrap();
        assert_eq!(provider.vault_addr, "http://vault:8200");
        assert_eq!(provider.pki_path, "pki_int/issue/mesh-agent");
        assert_eq!(provider.token, "s.test-token");
        assert_eq!(provider.trust_domain, "mcp-mesh.local");
        assert_eq!(provider.ttl, "24h");

        std::env::remove_var("MCP_MESH_VAULT_ADDR");
        std::env::remove_var("MCP_MESH_VAULT_PKI_PATH");
        std::env::remove_var("VAULT_TOKEN");
    }
}
