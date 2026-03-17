//! SPIRE credential provider — fetches X.509-SVIDs from SPIRE agent Workload API.
//!
//! Connects to the SPIRE agent's Unix domain socket to fetch workload certificates.
//! The SPIRE agent must be running on the same node (in K8s, deployed as a DaemonSet).
//!
//! Environment variables:
//! - `MCP_MESH_SPIRE_SOCKET` — Path to SPIRE agent socket (default: `/run/spire/agent/sockets/agent.sock`)
//! - `MCP_MESH_TRUST_DOMAIN` — Expected trust domain (default: `mcp-mesh.local`)

use async_trait::async_trait;
use tracing::{debug, info};

use crate::tls::{CredentialProvider, TlsCredentials, TlsError};

const DEFAULT_SOCKET_PATH: &str = "/run/spire/agent/sockets/agent.sock";

#[derive(Debug)]
pub struct SPIREProvider {
    socket_path: String,
    trust_domain: String,
}

impl SPIREProvider {
    pub fn from_env() -> Result<Self, TlsError> {
        let socket_path = std::env::var("MCP_MESH_SPIRE_SOCKET")
            .ok()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| DEFAULT_SOCKET_PATH.to_string());

        let trust_domain = std::env::var("MCP_MESH_TRUST_DOMAIN")
            .ok()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "mcp-mesh.local".to_string());

        info!("SPIRE provider configured: socket={}, trust_domain={}", socket_path, trust_domain);

        Ok(Self {
            socket_path,
            trust_domain,
        })
    }
}

/// Convert DER-encoded bytes to PEM format with the given label.
/// Label should be "CERTIFICATE" or "PRIVATE KEY".
fn der_to_pem(der: &[u8], label: &str) -> String {
    use base64::Engine;
    let b64 = base64::engine::general_purpose::STANDARD.encode(der);
    let mut pem = format!("-----BEGIN {}-----\n", label);
    for chunk in b64.as_bytes().chunks(64) {
        pem.push_str(std::str::from_utf8(chunk).expect("base64 output is always valid ASCII/UTF-8"));
        pem.push('\n');
    }
    pem.push_str(&format!("-----END {}-----\n", label));
    pem
}

#[async_trait]
impl CredentialProvider for SPIREProvider {
    async fn get_credentials(&self, _agent_name: &str, _advertised_host: &str) -> Result<TlsCredentials, TlsError> {
        use spiffe::WorkloadApiClient;

        let endpoint = format!("unix://{}", self.socket_path);
        info!("Fetching X.509-SVID from SPIRE agent at {}", endpoint);

        // Connect to SPIRE Workload API
        let client = WorkloadApiClient::connect_to(&endpoint)
            .await
            .map_err(|e| TlsError::SpireError(format!("Failed to connect to SPIRE agent: {}", e)))?;

        // Fetch X.509-SVID
        let svid = client
            .fetch_x509_svid()
            .await
            .map_err(|e| TlsError::SpireError(format!("Failed to fetch X.509-SVID: {}", e)))?;

        let spiffe_id = svid.spiffe_id().to_string();
        info!("Obtained X.509-SVID: {}", spiffe_id);

        // Convert cert chain (DER) to PEM
        let mut cert_pem = String::new();
        for cert in svid.cert_chain() {
            cert_pem.push_str(&der_to_pem(cert.as_bytes(), "CERTIFICATE"));
        }

        // Convert private key (DER) to PEM
        let key_pem = der_to_pem(svid.private_key().as_bytes(), "PRIVATE KEY");

        // Fetch trust bundles for CA
        let bundles = client
            .fetch_x509_bundles()
            .await
            .map_err(|e| TlsError::SpireError(format!("Failed to fetch X.509 bundles: {}", e)))?;

        // Build CA PEM from trust bundles
        let mut ca_pem = String::new();
        for (_domain, bundle) in bundles.iter() {
            debug!("Trust bundle for domain: {}", _domain);
            for authority in bundle.authorities() {
                ca_pem.push_str(&der_to_pem(authority.as_bytes(), "CERTIFICATE"));
            }
        }

        info!("X.509-SVID obtained from SPIRE: id={}, trust_domain={}", spiffe_id, self.trust_domain);

        Ok(TlsCredentials {
            cert_pem: cert_pem.into_bytes(),
            key_pem: key_pem.into_bytes(),
            ca_pem: if ca_pem.is_empty() { None } else { Some(ca_pem.into_bytes()) },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static TEST_ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn test_spire_provider_default_socket_path() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        std::env::remove_var("MCP_MESH_SPIRE_SOCKET");
        std::env::remove_var("MCP_MESH_TRUST_DOMAIN");

        // from_env() succeeds even if socket doesn't exist yet
        // (socket availability is checked at connect time, not init time)
        let provider = SPIREProvider::from_env().unwrap();
        assert_eq!(provider.socket_path, "/run/spire/agent/sockets/agent.sock");
        assert_eq!(provider.trust_domain, "mcp-mesh.local");
    }

    #[test]
    fn test_spire_provider_custom_socket_path() {
        let _lock = TEST_ENV_LOCK.lock().unwrap();

        std::env::set_var("MCP_MESH_SPIRE_SOCKET", "/custom/spire.sock");
        std::env::remove_var("MCP_MESH_TRUST_DOMAIN");

        let provider = SPIREProvider::from_env().unwrap();
        assert_eq!(provider.socket_path, "/custom/spire.sock");

        std::env::remove_var("MCP_MESH_SPIRE_SOCKET");
    }

    #[test]
    fn test_der_to_pem_certificate() {
        let fake_der = b"fake-certificate-der-data";
        let pem = der_to_pem(fake_der, "CERTIFICATE");
        assert!(pem.starts_with("-----BEGIN CERTIFICATE-----\n"));
        assert!(pem.ends_with("-----END CERTIFICATE-----\n"));
        assert!(pem.contains("ZmFrZS1jZXJ0aWZpY2F0ZS1kZXItZGF0YQ=="));
    }

    #[test]
    fn test_der_to_pem_private_key() {
        let fake_der = b"fake-private-key-der-data";
        let pem = der_to_pem(fake_der, "PRIVATE KEY");
        assert!(pem.starts_with("-----BEGIN PRIVATE KEY-----\n"));
        assert!(pem.ends_with("-----END PRIVATE KEY-----\n"));
    }
}
