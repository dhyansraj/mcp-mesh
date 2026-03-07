package trust

import (
	"crypto/x509"
	"fmt"
	"log/slog"
)

// TrustChain is an ordered list of trust backends. During verification it tries
// each backend in order and returns the result from the first one that trusts
// the presented certificate chain.
type TrustChain struct {
	backends []TrustBackend
}

// NewTrustChain creates a TrustChain from the given backends. Backends are
// evaluated in the order they are provided.
func NewTrustChain(backends ...TrustBackend) *TrustChain {
	return &TrustChain{
		backends: backends,
	}
}

// Add appends a backend to the end of the chain.
func (tc *TrustChain) Add(backend TrustBackend) {
	tc.backends = append(tc.backends, backend)
}

// Verify iterates through all backends in order and returns the result from the
// first backend that successfully verifies the certificate chain. If no backend
// trusts the chain, ErrUntrustedCert is returned.
func (tc *TrustChain) Verify(certChain []*x509.Certificate) (*VerifyResult, error) {
	if len(certChain) == 0 {
		return nil, ErrNoCertPresented
	}

	if len(tc.backends) == 0 {
		return nil, fmt.Errorf("%w: no backends configured", ErrUntrustedCert)
	}

	for _, backend := range tc.backends {
		result, err := backend.Verify(certChain)
		if err == nil && result != nil {
			slog.Debug("certificate verified by backend",
				"backend", backend.Name(),
				"entity_id", result.EntityID,
				"cert_subject", result.CertSubject,
			)
			return result, nil
		}
		slog.Debug("backend did not verify certificate",
			"backend", backend.Name(),
			"error", err,
		)
	}

	return nil, ErrUntrustedCert
}

// ListTrustedEntities aggregates trusted entities from all backends in the chain.
// If a backend returns an error, it is skipped and the error is logged.
func (tc *TrustChain) ListTrustedEntities() ([]TrustedEntity, error) {
	var all []TrustedEntity

	for _, backend := range tc.backends {
		entities, err := backend.ListTrustedEntities()
		if err != nil {
			slog.Warn("failed to list trusted entities from backend",
				"backend", backend.Name(),
				"error", err,
			)
			continue
		}
		all = append(all, entities...)
	}

	return all, nil
}

// Len returns the number of backends in the chain.
func (tc *TrustChain) Len() int {
	return len(tc.backends)
}
