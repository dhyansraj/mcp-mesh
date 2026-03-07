package trust

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"errors"
	"math/big"
	"testing"
	"time"
)

// mockBackend implements TrustBackend for testing.
type mockBackend struct {
	name     string
	result   *VerifyResult
	err      error
	entities []TrustedEntity
	listErr  error
}

func (m *mockBackend) Verify(certChain []*x509.Certificate) (*VerifyResult, error) {
	if m.err != nil {
		return nil, m.err
	}
	return m.result, nil
}

func (m *mockBackend) ListTrustedEntities() ([]TrustedEntity, error) {
	if m.listErr != nil {
		return nil, m.listErr
	}
	return m.entities, nil
}

func (m *mockBackend) Name() string {
	return m.name
}

// newTestCert generates a self-signed certificate for testing.
func newTestCert(t *testing.T) *x509.Certificate {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("failed to generate key: %v", err)
	}

	template := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "test-agent", OrganizationalUnit: []string{"test-entity"}},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("failed to create certificate: %v", err)
	}

	cert, err := x509.ParseCertificate(certDER)
	if err != nil {
		t.Fatalf("failed to parse certificate: %v", err)
	}
	return cert
}

func TestTrustChain_VerifyNoCerts(t *testing.T) {
	chain := NewTrustChain()
	_, err := chain.Verify(nil)
	if !errors.Is(err, ErrNoCertPresented) {
		t.Errorf("expected ErrNoCertPresented, got %v", err)
	}

	_, err = chain.Verify([]*x509.Certificate{})
	if !errors.Is(err, ErrNoCertPresented) {
		t.Errorf("expected ErrNoCertPresented for empty chain, got %v", err)
	}
}

func TestTrustChain_VerifyNoBackends(t *testing.T) {
	chain := NewTrustChain()
	cert := newTestCert(t)

	_, err := chain.Verify([]*x509.Certificate{cert})
	if !errors.Is(err, ErrUntrustedCert) {
		t.Errorf("expected ErrUntrustedCert, got %v", err)
	}
}

func TestTrustChain_VerifyFirstBackendSucceeds(t *testing.T) {
	cert := newTestCert(t)
	expected := &VerifyResult{
		EntityID:    "entity-a",
		CertSubject: "CN=test-agent",
		BackendName: "backend-a",
	}

	chain := NewTrustChain(
		&mockBackend{name: "backend-a", result: expected},
		&mockBackend{name: "backend-b", err: ErrUntrustedCert},
	)

	result, err := chain.Verify([]*x509.Certificate{cert})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.EntityID != "entity-a" {
		t.Errorf("expected entity-a, got %s", result.EntityID)
	}
	if result.BackendName != "backend-a" {
		t.Errorf("expected backend-a, got %s", result.BackendName)
	}
}

func TestTrustChain_VerifySecondBackendSucceeds(t *testing.T) {
	cert := newTestCert(t)
	expected := &VerifyResult{
		EntityID:    "entity-b",
		CertSubject: "CN=test-agent",
		BackendName: "backend-b",
	}

	chain := NewTrustChain(
		&mockBackend{name: "backend-a", err: ErrUntrustedCert},
		&mockBackend{name: "backend-b", result: expected},
	)

	result, err := chain.Verify([]*x509.Certificate{cert})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.EntityID != "entity-b" {
		t.Errorf("expected entity-b, got %s", result.EntityID)
	}
}

func TestTrustChain_VerifyAllBackendsFail(t *testing.T) {
	cert := newTestCert(t)

	chain := NewTrustChain(
		&mockBackend{name: "backend-a", err: ErrUntrustedCert},
		&mockBackend{name: "backend-b", err: ErrUntrustedCert},
	)

	_, err := chain.Verify([]*x509.Certificate{cert})
	if !errors.Is(err, ErrUntrustedCert) {
		t.Errorf("expected ErrUntrustedCert, got %v", err)
	}
}

func TestTrustChain_Add(t *testing.T) {
	chain := NewTrustChain()
	if chain.Len() != 0 {
		t.Fatalf("expected 0 backends, got %d", chain.Len())
	}

	chain.Add(&mockBackend{name: "added"})
	if chain.Len() != 1 {
		t.Fatalf("expected 1 backend, got %d", chain.Len())
	}
}

func TestTrustChain_ListTrustedEntities(t *testing.T) {
	chain := NewTrustChain(
		&mockBackend{
			name: "backend-a",
			entities: []TrustedEntity{
				{ID: "entity-a", Fingerprint: "AA:BB"},
			},
		},
		&mockBackend{
			name: "backend-b",
			entities: []TrustedEntity{
				{ID: "entity-b", Fingerprint: "CC:DD"},
				{ID: "entity-c", Fingerprint: "EE:FF"},
			},
		},
	)

	entities, err := chain.ListTrustedEntities()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(entities) != 3 {
		t.Fatalf("expected 3 entities, got %d", len(entities))
	}
}

func TestTrustChain_ListTrustedEntitiesSkipsErrors(t *testing.T) {
	chain := NewTrustChain(
		&mockBackend{
			name:    "failing-backend",
			listErr: errors.New("connection refused"),
		},
		&mockBackend{
			name: "working-backend",
			entities: []TrustedEntity{
				{ID: "entity-ok"},
			},
		},
	)

	entities, err := chain.ListTrustedEntities()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(entities) != 1 {
		t.Fatalf("expected 1 entity, got %d", len(entities))
	}
	if entities[0].ID != "entity-ok" {
		t.Errorf("expected entity-ok, got %s", entities[0].ID)
	}
}
