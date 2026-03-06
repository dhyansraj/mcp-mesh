package trust

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// generateCA creates a self-signed CA certificate and key.
func generateCA(t *testing.T, org string) (*x509.Certificate, *ecdsa.PrivateKey) {
	t.Helper()

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	require.NoError(t, err)

	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	require.NoError(t, err)

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			Organization: []string{org},
			CommonName:   org + " CA",
		},
		NotBefore:             time.Now().Add(-1 * time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
		BasicConstraintsValid: true,
		IsCA:                  true,
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	require.NoError(t, err)

	cert, err := x509.ParseCertificate(certDER)
	require.NoError(t, err)

	return cert, key
}

// generateLeaf creates a leaf certificate signed by the given CA.
func generateLeaf(t *testing.T, ca *x509.Certificate, caKey *ecdsa.PrivateKey, cn string) (*x509.Certificate, *ecdsa.PrivateKey) {
	t.Helper()

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	require.NoError(t, err)

	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	require.NoError(t, err)

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName: cn,
		},
		NotBefore: time.Now().Add(-1 * time.Hour),
		NotAfter:  time.Now().Add(24 * time.Hour),
		KeyUsage:  x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, ca, &key.PublicKey, caKey)
	require.NoError(t, err)

	cert, err := x509.ParseCertificate(certDER)
	require.NoError(t, err)

	return cert, key
}

// generateExpiredLeaf creates an expired leaf certificate signed by the given CA.
func generateExpiredLeaf(t *testing.T, ca *x509.Certificate, caKey *ecdsa.PrivateKey, cn string) *x509.Certificate {
	t.Helper()

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	require.NoError(t, err)

	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	require.NoError(t, err)

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName: cn,
		},
		NotBefore: time.Now().Add(-48 * time.Hour),
		NotAfter:  time.Now().Add(-1 * time.Hour),
		KeyUsage:  x509.KeyUsageDigitalSignature,
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, ca, &key.PublicKey, caKey)
	require.NoError(t, err)

	cert, err := x509.ParseCertificate(certDER)
	require.NoError(t, err)

	return cert
}

// writePEM writes a certificate to a PEM file in the given directory.
func writePEM(t *testing.T, dir, filename string, certs ...*x509.Certificate) {
	t.Helper()

	path := filepath.Join(dir, filename)
	f, err := os.Create(path)
	require.NoError(t, err)
	defer f.Close()

	for _, cert := range certs {
		err = pem.Encode(f, &pem.Block{
			Type:  "CERTIFICATE",
			Bytes: cert.Raw,
		})
		require.NoError(t, err)
	}
}

func TestFileStore_LoadPEMFiles(t *testing.T) {
	dir := t.TempDir()

	ca1, _ := generateCA(t, "entity-alpha")
	ca2, _ := generateCA(t, "entity-beta")

	writePEM(t, dir, "alpha.pem", ca1)
	writePEM(t, dir, "beta.pem", ca2)

	fs, err := NewFileStore(dir, false)
	require.NoError(t, err)
	defer fs.Close()

	assert.Equal(t, "filestore", fs.Name())

	entities, err := fs.ListTrustedEntities()
	require.NoError(t, err)
	assert.Len(t, entities, 2)

	ids := map[string]bool{}
	for _, e := range entities {
		ids[e.ID] = true
		assert.NotEmpty(t, e.Fingerprint)
		assert.NotEmpty(t, e.Subject)
		assert.False(t, e.NotBefore.IsZero())
		assert.False(t, e.NotAfter.IsZero())
	}
	assert.True(t, ids["entity-alpha"])
	assert.True(t, ids["entity-beta"])
}

func TestFileStore_EntityIDFromFilename(t *testing.T) {
	dir := t.TempDir()

	// Create a CA with no Organization or OU.
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	require.NoError(t, err)

	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	require.NoError(t, err)

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName: "bare-cert",
		},
		NotBefore:             time.Now().Add(-1 * time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		KeyUsage:              x509.KeyUsageCertSign,
		BasicConstraintsValid: true,
		IsCA:                  true,
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	require.NoError(t, err)

	cert, err := x509.ParseCertificate(certDER)
	require.NoError(t, err)

	writePEM(t, dir, "my-service.pem", cert)

	fs, err := NewFileStore(dir, false)
	require.NoError(t, err)
	defer fs.Close()

	entities, err := fs.ListTrustedEntities()
	require.NoError(t, err)
	require.Len(t, entities, 1)
	assert.Equal(t, "my-service", entities[0].ID)
}

func TestFileStore_VerifyTrustedCert(t *testing.T) {
	dir := t.TempDir()

	ca, caKey := generateCA(t, "trusted-org")
	writePEM(t, dir, "trusted.pem", ca)

	leaf, _ := generateLeaf(t, ca, caKey, "agent-1")

	fs, err := NewFileStore(dir, false)
	require.NoError(t, err)
	defer fs.Close()

	result, err := fs.Verify([]*x509.Certificate{leaf})
	require.NoError(t, err)
	assert.Equal(t, "trusted-org", result.EntityID)
	assert.Equal(t, "filestore", result.BackendName)
	assert.Contains(t, result.CertSubject, "agent-1")
}

func TestFileStore_RejectUntrustedCert(t *testing.T) {
	dir := t.TempDir()

	ca, _ := generateCA(t, "known-org")
	writePEM(t, dir, "known.pem", ca)

	// Generate a leaf signed by a different (unknown) CA.
	unknownCA, unknownKey := generateCA(t, "unknown-org")
	_ = unknownCA
	leaf, _ := generateLeaf(t, unknownCA, unknownKey, "rogue-agent")

	fs, err := NewFileStore(dir, false)
	require.NoError(t, err)
	defer fs.Close()

	_, err = fs.Verify([]*x509.Certificate{leaf})
	assert.ErrorIs(t, err, ErrUntrustedCert)
}

func TestFileStore_RejectExpiredCert(t *testing.T) {
	dir := t.TempDir()

	ca, caKey := generateCA(t, "expiry-org")
	writePEM(t, dir, "expiry.pem", ca)

	expired := generateExpiredLeaf(t, ca, caKey, "expired-agent")

	fs, err := NewFileStore(dir, false)
	require.NoError(t, err)
	defer fs.Close()

	_, err = fs.Verify([]*x509.Certificate{expired})
	assert.ErrorIs(t, err, ErrExpiredCert)
}

func TestFileStore_RejectNoCert(t *testing.T) {
	dir := t.TempDir()
	fs, err := NewFileStore(dir, false)
	require.NoError(t, err)
	defer fs.Close()

	_, err = fs.Verify(nil)
	assert.ErrorIs(t, err, ErrNoCertPresented)

	_, err = fs.Verify([]*x509.Certificate{})
	assert.ErrorIs(t, err, ErrNoCertPresented)
}

func TestFileStore_HotReload(t *testing.T) {
	dir := t.TempDir()

	ca1, ca1Key := generateCA(t, "initial-org")
	writePEM(t, dir, "initial.pem", ca1)

	fs, err := NewFileStore(dir, true)
	require.NoError(t, err)
	defer fs.Close()

	// Verify initial state: only one entity.
	entities, err := fs.ListTrustedEntities()
	require.NoError(t, err)
	assert.Len(t, entities, 1)

	// Leaf signed by initial CA should verify.
	leaf1, _ := generateLeaf(t, ca1, ca1Key, "agent-initial")
	_, err = fs.Verify([]*x509.Certificate{leaf1})
	require.NoError(t, err)

	// Add a new CA PEM file.
	ca2, ca2Key := generateCA(t, "hotloaded-org")
	writePEM(t, dir, "hotloaded.pem", ca2)

	// Wait for fsnotify to trigger reload.
	require.Eventually(t, func() bool {
		entities, err := fs.ListTrustedEntities()
		if err != nil {
			return false
		}
		return len(entities) == 2
	}, 5*time.Second, 100*time.Millisecond, "expected 2 entities after hot reload")

	// Leaf signed by new CA should now verify.
	leaf2, _ := generateLeaf(t, ca2, ca2Key, "agent-hotloaded")
	result, err := fs.Verify([]*x509.Certificate{leaf2})
	require.NoError(t, err)
	assert.Equal(t, "hotloaded-org", result.EntityID)
}

func TestFileStore_MultipleCertsInPEM(t *testing.T) {
	dir := t.TempDir()

	ca1, _ := generateCA(t, "chain-org")
	ca2, _ := generateCA(t, "chain-org") // Second cert with same org

	// Write both certs into a single PEM file.
	writePEM(t, dir, "chain.pem", ca1, ca2)

	fs, err := NewFileStore(dir, false)
	require.NoError(t, err)
	defer fs.Close()

	entities, err := fs.ListTrustedEntities()
	require.NoError(t, err)
	// Both certs are listed but share the same entity ID.
	assert.Len(t, entities, 2)
	for _, e := range entities {
		assert.Equal(t, "chain-org", e.ID)
	}
}

func TestFileStore_InvalidDirectory(t *testing.T) {
	_, err := NewFileStore("/nonexistent/path", false)
	assert.Error(t, err)
}

func TestFileStore_SkipsNonPEMFiles(t *testing.T) {
	dir := t.TempDir()

	ca, _ := generateCA(t, "real-org")
	writePEM(t, dir, "valid.pem", ca)

	// Write a non-PEM file.
	err := os.WriteFile(filepath.Join(dir, "notes.txt"), []byte("not a cert"), 0644)
	require.NoError(t, err)

	fs, err := NewFileStore(dir, false)
	require.NoError(t, err)
	defer fs.Close()

	entities, err := fs.ListTrustedEntities()
	require.NoError(t, err)
	assert.Len(t, entities, 1)
	assert.Equal(t, "real-org", entities[0].ID)
}
