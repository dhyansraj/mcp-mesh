// Package trust provides the trust backend abstraction for the mcp-mesh registry.
// It allows the registry to validate agent certificates against trusted entity CAs
// without coupling to a specific CA source (filesystem, Kubernetes secrets, etc.).
package trust

import (
	"crypto/x509"
	"errors"
	"strings"
	"time"
)

var (
	ErrUntrustedCert    = errors.New("certificate not trusted by any entity CA")
	ErrExpiredCert      = errors.New("certificate has expired")
	ErrNoCertPresented  = errors.New("no client certificate presented")
	ErrInvalidCertChain = errors.New("invalid certificate chain")
)

// TrustBackend defines the interface for certificate trust verification.
type TrustBackend interface {
	Verify(certChain []*x509.Certificate) (*VerifyResult, error)
	ListTrustedEntities() ([]TrustedEntity, error)
	Name() string
}

// VerifyResult contains the result of a successful certificate verification.
type VerifyResult struct {
	EntityID    string
	CertSubject string
	BackendName string
}

// TrustedEntity represents a trusted CA entity loaded from a backend.
type TrustedEntity struct {
	ID          string
	Subject     string
	NotBefore   time.Time
	NotAfter    time.Time
	Fingerprint string
	Metadata    map[string]string
}

// ParseBackendConfig parses the MCP_MESH_TRUST_BACKEND configuration string
// into a list of backend names. The input is a comma-separated list of backend
// identifiers (e.g., "filestore,k8s-secrets").
func ParseBackendConfig(config string) []string {
	config = strings.TrimSpace(config)
	if config == "" {
		return nil
	}

	parts := strings.Split(config, ",")
	names := make([]string, 0, len(parts))
	for _, p := range parts {
		name := strings.TrimSpace(p)
		if name != "" {
			names = append(names, name)
		}
	}
	return names
}
