package cli

import (
	"fmt"
	"os"
	"path/filepath"

	"mcp-mesh/src/core/registry/trust"
)

// TLSAutoConfig holds paths to auto-generated certificates
type TLSAutoConfig struct {
	TLSDir        string // base TLS directory
	RootCAPEM     string // path to root CA cert
	EntityCertPEM string // path to entity CA cert
	EntityKeyPEM  string // path to entity CA key
	RegistryCert  string // path to registry server cert
	RegistryKey   string // path to registry server key
}

// SetupTLSAuto initializes the LocalCA and generates certificates for dev mode.
// Returns TLSAutoConfig with paths to generated certs.
func SetupTLSAuto(stateDir string) (*TLSAutoConfig, error) {
	tlsDir := filepath.Join(stateDir, "tls")
	if err := os.MkdirAll(tlsDir, 0700); err != nil {
		return nil, fmt.Errorf("creating TLS directory: %w", err)
	}

	// Initialize LocalCA (creates root CA if not exists)
	fmt.Println("🔒 Initializing local CA...")
	ca, err := trust.NewLocalCA(tlsDir)
	if err != nil {
		return nil, fmt.Errorf("initializing local CA: %w", err)
	}
	fmt.Println("🔒 Local CA ready (root CA persisted in", tlsDir, ")")

	// Generate entity CA for "local-dev"
	entityDir := filepath.Join(tlsDir, "local-dev")
	if err := os.MkdirAll(entityDir, 0700); err != nil {
		return nil, fmt.Errorf("creating entity directory: %w", err)
	}

	entityCertPath := filepath.Join(entityDir, "entity-cert.pem")
	entityKeyPath := filepath.Join(entityDir, "entity-key.pem")

	// Generate entity CA if not exists
	fmt.Println("🔒 Entity CA: local-dev")
	var entityCertPEM, entityKeyPEM []byte
	if _, err := os.Stat(entityCertPath); os.IsNotExist(err) {
		entityCertPEM, entityKeyPEM, err = ca.GenerateEntityCA("local-dev")
		if err != nil {
			return nil, fmt.Errorf("generating entity CA: %w", err)
		}
		if err := os.WriteFile(entityCertPath, entityCertPEM, 0644); err != nil {
			return nil, fmt.Errorf("writing entity cert: %w", err)
		}
		if err := os.WriteFile(entityKeyPath, entityKeyPEM, 0600); err != nil {
			return nil, fmt.Errorf("writing entity key: %w", err)
		}
	} else {
		entityCertPEM, err = os.ReadFile(entityCertPath)
		if err != nil {
			return nil, fmt.Errorf("reading entity cert: %w", err)
		}
		entityKeyPEM, err = os.ReadFile(entityKeyPath)
		if err != nil {
			return nil, fmt.Errorf("reading entity key: %w", err)
		}
	}

	// Generate registry server cert (always regenerate for freshness)
	registryCertPath := filepath.Join(entityDir, "registry-cert.pem")
	registryKeyPath := filepath.Join(entityDir, "registry-key.pem")

	certPEM, keyPEM, err := ca.GenerateAgentCert("mcp-mesh-registry", entityCertPEM, entityKeyPEM)
	if err != nil {
		return nil, fmt.Errorf("generating registry cert: %w", err)
	}
	fmt.Println("🔒 Registry server certificate generated")
	if err := os.WriteFile(registryCertPath, certPEM, 0644); err != nil {
		return nil, fmt.Errorf("writing registry cert: %w", err)
	}
	if err := os.WriteFile(registryKeyPath, keyPEM, 0600); err != nil {
		return nil, fmt.Errorf("writing registry key: %w", err)
	}

	rootCAPEM := filepath.Join(tlsDir, "ca.pem")

	return &TLSAutoConfig{
		TLSDir:        tlsDir,
		RootCAPEM:     rootCAPEM,
		EntityCertPEM: entityCertPath,
		EntityKeyPEM:  entityKeyPath,
		RegistryCert:  registryCertPath,
		RegistryKey:   registryKeyPath,
	}, nil
}

// GenerateAgentCert generates a certificate for a specific agent.
// Returns paths to the generated cert and key files.
func (tc *TLSAutoConfig) GenerateAgentCert(agentName string) (certPath string, keyPath string, err error) {
	ca, err := trust.NewLocalCA(tc.TLSDir)
	if err != nil {
		return "", "", fmt.Errorf("loading local CA: %w", err)
	}

	entityCertPEM, err := os.ReadFile(tc.EntityCertPEM)
	if err != nil {
		return "", "", fmt.Errorf("reading entity cert: %w", err)
	}
	entityKeyPEM, err := os.ReadFile(tc.EntityKeyPEM)
	if err != nil {
		return "", "", fmt.Errorf("reading entity key: %w", err)
	}

	certPEM, keyPEM, err := ca.GenerateAgentCert(agentName, entityCertPEM, entityKeyPEM)
	if err != nil {
		return "", "", fmt.Errorf("generating agent cert: %w", err)
	}
	fmt.Printf("🔒 Agent certificate generated: %s\n", agentName)

	agentDir := filepath.Join(tc.TLSDir, "local-dev", "agents")
	if err := os.MkdirAll(agentDir, 0700); err != nil {
		return "", "", fmt.Errorf("creating agents cert directory: %w", err)
	}

	certPath = filepath.Join(agentDir, agentName+"-cert.pem")
	keyPath = filepath.Join(agentDir, agentName+"-key.pem")

	if err := os.WriteFile(certPath, certPEM, 0644); err != nil {
		return "", "", fmt.Errorf("writing agent cert: %w", err)
	}
	if err := os.WriteFile(keyPath, keyPEM, 0600); err != nil {
		return "", "", fmt.Errorf("writing agent key: %w", err)
	}

	return certPath, keyPath, nil
}

// GetRegistryTLSEnv returns environment variables for the registry process when TLS auto is enabled.
func (tc *TLSAutoConfig) GetRegistryTLSEnv() []string {
	return []string{
		"MCP_MESH_TLS_MODE=auto",
		"MCP_MESH_TRUST_BACKEND=localca,filestore",
		fmt.Sprintf("MCP_MESH_TRUST_DIR=%s", tc.TLSDir),
		fmt.Sprintf("MCP_MESH_TLS_CERT=%s", tc.RegistryCert),
		fmt.Sprintf("MCP_MESH_TLS_KEY=%s", tc.RegistryKey),
		fmt.Sprintf("MCP_MESH_TLS_CA=%s", tc.RootCAPEM),
	}
}

// GetAgentTLSEnv returns environment variables for an agent process when TLS auto is enabled.
//
// Agents trust localca only — the filestore backend is registry-scoped (#805).
// Propagating filestore to agents would mean every agent implicitly trusts
// every entity an operator registers via `meshctl entity register`, which
// broadens the trust surface beyond what the #805 fix intended.
func (tc *TLSAutoConfig) GetAgentTLSEnv(agentCertPath, agentKeyPath string) []string {
	return []string{
		"MCP_MESH_TLS_MODE=auto",
		"MCP_MESH_TRUST_BACKEND=localca",
		fmt.Sprintf("MCP_MESH_TRUST_DIR=%s", tc.TLSDir),
		fmt.Sprintf("MCP_MESH_TLS_CERT=%s", agentCertPath),
		fmt.Sprintf("MCP_MESH_TLS_KEY=%s", agentKeyPath),
		fmt.Sprintf("MCP_MESH_TLS_CA=%s", tc.RootCAPEM),
	}
}
