package trust

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"math/big"
	"net/url"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// generateLeafWithSPIFFEID creates a leaf certificate with a SPIFFE ID URI SAN.
func generateLeafWithSPIFFEID(t *testing.T, ca *x509.Certificate, caKey *ecdsa.PrivateKey, spiffeID string) (*x509.Certificate, *ecdsa.PrivateKey) {
	t.Helper()

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	require.NoError(t, err)

	spiffeURI, err := url.Parse(spiffeID)
	require.NoError(t, err)

	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	require.NoError(t, err)

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: "spiffe-agent"},
		URIs:         []*url.URL{spiffeURI},
		NotBefore:    time.Now().Add(-1 * time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, ca, &key.PublicKey, caKey)
	require.NoError(t, err)

	cert, err := x509.ParseCertificate(certDER)
	require.NoError(t, err)

	return cert, key
}

func TestSPIRE_VerifyWithSPIFFEID(t *testing.T) {
	ca, caKey := generateCA(t, "acme-corp")

	backend := NewSPIREFromBundles(map[string][]*x509.Certificate{
		"acme-corp": {ca},
	})

	leaf, _ := generateLeafWithSPIFFEID(t, ca, caKey, "spiffe://acme-corp/agent/greeter")

	result, err := backend.Verify([]*x509.Certificate{leaf})
	require.NoError(t, err)
	assert.Equal(t, "acme-corp", result.EntityID)
	assert.Equal(t, "spire", result.BackendName)
	assert.Contains(t, result.CertSubject, "spiffe-agent")
}

func TestSPIRE_VerifyWithoutSPIFFEID(t *testing.T) {
	ca, caKey := generateCA(t, "fallback-org")

	backend := NewSPIREFromBundles(map[string][]*x509.Certificate{
		"fallback-org": {ca},
	})

	// Generate a regular leaf without SPIFFE ID URI SAN.
	leaf, _ := generateLeaf(t, ca, caKey, "regular-agent")

	result, err := backend.Verify([]*x509.Certificate{leaf})
	require.NoError(t, err)
	assert.Equal(t, "fallback-org", result.EntityID)
	assert.Equal(t, "spire", result.BackendName)
}

func TestSPIRE_RejectUntrustedDomain(t *testing.T) {
	ca, _ := generateCA(t, "known-domain")

	backend := NewSPIREFromBundles(map[string][]*x509.Certificate{
		"known-domain": {ca},
	})

	// Generate a leaf from a different (unknown) CA.
	unknownCA, unknownKey := generateCA(t, "unknown-domain")
	_ = unknownCA
	leaf, _ := generateLeafWithSPIFFEID(t, unknownCA, unknownKey, "spiffe://unknown-domain/agent/rogue")

	_, err := backend.Verify([]*x509.Certificate{leaf})
	assert.ErrorIs(t, err, ErrUntrustedCert)
}

func TestSPIRE_RejectExpiredCert(t *testing.T) {
	ca, caKey := generateCA(t, "expiry-domain")

	backend := NewSPIREFromBundles(map[string][]*x509.Certificate{
		"expiry-domain": {ca},
	})

	expired := generateExpiredLeaf(t, ca, caKey, "expired-agent")

	_, err := backend.Verify([]*x509.Certificate{expired})
	assert.ErrorIs(t, err, ErrExpiredCert)
}

func TestSPIRE_RejectNoCert(t *testing.T) {
	backend := NewSPIREFromBundles(map[string][]*x509.Certificate{})

	_, err := backend.Verify(nil)
	assert.ErrorIs(t, err, ErrNoCertPresented)

	_, err = backend.Verify([]*x509.Certificate{})
	assert.ErrorIs(t, err, ErrNoCertPresented)
}

func TestSPIRE_MultipleTrustDomains(t *testing.T) {
	ca1, ca1Key := generateCA(t, "domain-alpha")
	ca2, ca2Key := generateCA(t, "domain-beta")

	backend := NewSPIREFromBundles(map[string][]*x509.Certificate{
		"domain-alpha": {ca1},
		"domain-beta":  {ca2},
	})

	// Agent from domain-alpha.
	leaf1, _ := generateLeafWithSPIFFEID(t, ca1, ca1Key, "spiffe://domain-alpha/agent/one")
	result1, err := backend.Verify([]*x509.Certificate{leaf1})
	require.NoError(t, err)
	assert.Equal(t, "domain-alpha", result1.EntityID)

	// Agent from domain-beta.
	leaf2, _ := generateLeafWithSPIFFEID(t, ca2, ca2Key, "spiffe://domain-beta/agent/two")
	result2, err := backend.Verify([]*x509.Certificate{leaf2})
	require.NoError(t, err)
	assert.Equal(t, "domain-beta", result2.EntityID)
}

func TestSPIRE_ListTrustedEntities(t *testing.T) {
	ca1, _ := generateCA(t, "list-domain-a")
	ca2, _ := generateCA(t, "list-domain-b")

	backend := NewSPIREFromBundles(map[string][]*x509.Certificate{
		"list-domain-a": {ca1},
		"list-domain-b": {ca2},
	})

	entities, err := backend.ListTrustedEntities()
	require.NoError(t, err)
	assert.Len(t, entities, 2)

	ids := map[string]bool{}
	for _, e := range entities {
		ids[e.ID] = true
		assert.NotEmpty(t, e.Fingerprint)
		assert.NotEmpty(t, e.Subject)
		assert.False(t, e.NotBefore.IsZero())
		assert.False(t, e.NotAfter.IsZero())
		assert.Equal(t, "spire", e.Metadata["source"])
		assert.Equal(t, e.ID, e.Metadata["trust_domain"])
	}
	assert.True(t, ids["list-domain-a"])
	assert.True(t, ids["list-domain-b"])
}

func TestSPIRE_EntityIDFromSPIFFEID(t *testing.T) {
	tests := []struct {
		name     string
		spiffeID string
		want     string
		wantErr  bool
	}{
		{
			name:     "simple trust domain",
			spiffeID: "spiffe://acme-corp/agent/greeter",
			want:     "acme-corp",
		},
		{
			name:     "nested path",
			spiffeID: "spiffe://example.com/ns/production/sa/web",
			want:     "example.com",
		},
		{
			name:     "trust domain only",
			spiffeID: "spiffe://my-domain",
			want:     "my-domain",
		},
		{
			name:     "trust domain with trailing slash",
			spiffeID: "spiffe://my-domain/",
			want:     "my-domain",
		},
		{
			name:     "not a spiffe URI",
			spiffeID: "https://example.com/path",
			wantErr:  true,
		},
		{
			name:     "empty trust domain",
			spiffeID: "spiffe:///path/only",
			wantErr:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := extractTrustDomain(tt.spiffeID)
			if tt.wantErr {
				assert.Error(t, err)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.want, got)
			}
		})
	}
}

func TestSPIRE_Name(t *testing.T) {
	backend := NewSPIREFromBundles(map[string][]*x509.Certificate{})
	assert.Equal(t, "spire", backend.Name())
}
