package trust

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"fmt"
	"net/url"
	"strings"
	"sync"
	"time"
)

// SPIREBackend is a TrustBackend that validates agent certificates against
// SPIFFE trust bundles. Trust bundles contain CA certificates keyed by
// trust domain (e.g., "acme-corp" from spiffe://acme-corp/...).
//
// The core verification logic has no external dependencies. For live
// connection to a SPIRE Workload API, a future spire_connect.go file
// (behind a //go:build spire tag) will provide NewSPIRE(socketPath)
// using the go-spiffe/v2 SDK.
type SPIREBackend struct {
	mu          sync.RWMutex
	bundles     map[string]*x509.CertPool      // trust domain → CA pool
	bundleCerts map[string][]*x509.Certificate // trust domain → CA certs
}

// NewSPIREFromBundles creates a SPIREBackend from pre-loaded trust bundles.
// The bundles map is keyed by trust domain name, with values being the CA
// certificates for that domain. This constructor requires no external
// dependencies and is suitable for unit tests and environments where
// bundles are loaded from other sources (e.g., files or Kubernetes secrets).
func NewSPIREFromBundles(bundles map[string][]*x509.Certificate) *SPIREBackend {
	pools := make(map[string]*x509.CertPool, len(bundles))
	certsCopy := make(map[string][]*x509.Certificate, len(bundles))

	for domain, certs := range bundles {
		pool := x509.NewCertPool()
		for _, c := range certs {
			pool.AddCert(c)
		}
		pools[domain] = pool
		certsCopy[domain] = append([]*x509.Certificate(nil), certs...)
	}

	return &SPIREBackend{
		bundles:     pools,
		bundleCerts: certsCopy,
	}
}

// Name returns the backend name.
func (s *SPIREBackend) Name() string {
	return "spire"
}

// Verify checks whether the leaf certificate in certChain is trusted by any
// trust domain's CA bundle. If the leaf has a SPIFFE ID URI SAN, verification
// is attempted against the matching trust domain first. Otherwise, all trust
// domains are tried (similar to FileStore behavior).
func (s *SPIREBackend) Verify(certChain []*x509.Certificate) (*VerifyResult, error) {
	if len(certChain) == 0 {
		return nil, ErrNoCertPresented
	}

	leaf := certChain[0]

	now := time.Now()
	if now.After(leaf.NotAfter) {
		return nil, ErrExpiredCert
	}
	if now.Before(leaf.NotBefore) {
		return nil, ErrInvalidCertChain
	}

	// Build intermediate pool from remaining certs in the chain.
	intermediates := x509.NewCertPool()
	for _, c := range certChain[1:] {
		intermediates.AddCert(c)
	}

	s.mu.RLock()
	defer s.mu.RUnlock()

	// Try SPIFFE ID-based lookup first.
	if spiffeID := extractSPIFFEID(leaf); spiffeID != "" {
		domain, err := extractTrustDomain(spiffeID)
		if err == nil {
			if pool, ok := s.bundles[domain]; ok {
				opts := x509.VerifyOptions{
					Roots:         pool,
					Intermediates: intermediates,
					KeyUsages:     []x509.ExtKeyUsage{x509.ExtKeyUsageAny},
				}
				if _, err := leaf.Verify(opts); err == nil {
					return &VerifyResult{
						EntityID:    domain,
						CertSubject: leaf.Subject.String(),
						BackendName: s.Name(),
					}, nil
				}
			}
		}
	}

	// Fallback: try all trust domains.
	for domain, pool := range s.bundles {
		opts := x509.VerifyOptions{
			Roots:         pool,
			Intermediates: intermediates,
			KeyUsages:     []x509.ExtKeyUsage{x509.ExtKeyUsageAny},
		}
		if _, err := leaf.Verify(opts); err == nil {
			return &VerifyResult{
				EntityID:    domain,
				CertSubject: leaf.Subject.String(),
				BackendName: s.Name(),
			}, nil
		}
	}

	return nil, ErrUntrustedCert
}

// ListTrustedEntities returns metadata for all loaded trust domain CA certificates.
func (s *SPIREBackend) ListTrustedEntities() ([]TrustedEntity, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var result []TrustedEntity
	for domain, certs := range s.bundleCerts {
		for _, cert := range certs {
			fingerprint := sha256.Sum256(cert.Raw)
			result = append(result, TrustedEntity{
				ID:          domain,
				Subject:     cert.Subject.String(),
				NotBefore:   cert.NotBefore,
				NotAfter:    cert.NotAfter,
				Fingerprint: hex.EncodeToString(fingerprint[:]),
				Metadata: map[string]string{
					"source":       "spire",
					"trust_domain": domain,
				},
			})
		}
	}
	return result, nil
}

// extractSPIFFEID returns the first SPIFFE ID URI SAN from the certificate,
// or an empty string if none is found.
func extractSPIFFEID(cert *x509.Certificate) string {
	for _, uri := range cert.URIs {
		if strings.HasPrefix(uri.String(), "spiffe://") {
			return uri.String()
		}
	}
	return ""
}

// extractTrustDomain extracts the trust domain (host) from a SPIFFE ID.
// For example, "spiffe://acme-corp/agent/greeter" returns "acme-corp".
func extractTrustDomain(spiffeID string) (string, error) {
	u, err := url.Parse(spiffeID)
	if err != nil {
		return "", fmt.Errorf("parsing SPIFFE ID: %w", err)
	}
	if u.Scheme != "spiffe" {
		return "", fmt.Errorf("not a SPIFFE ID: %s", spiffeID)
	}
	if u.Host == "" {
		return "", fmt.Errorf("empty trust domain in SPIFFE ID: %s", spiffeID)
	}
	return u.Host, nil
}
