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

func TestLocalCA_CreatesRootCAFiles(t *testing.T) {
	dir := t.TempDir()

	ca, err := NewLocalCA(dir)
	require.NoError(t, err)

	assert.FileExists(t, filepath.Join(dir, "ca.pem"))
	assert.FileExists(t, filepath.Join(dir, "ca-key.pem"))
	assert.Equal(t, "localca", ca.Name())
	assert.True(t, ca.rootCert.IsCA)
	assert.Equal(t, "MCP Mesh Dev Root CA", ca.rootCert.Subject.CommonName)
}

func TestLocalCA_LoadsExistingFiles(t *testing.T) {
	dir := t.TempDir()

	// Create first instance to generate files.
	ca1, err := NewLocalCA(dir)
	require.NoError(t, err)

	rootPEM1, err := ca1.RootCAPEM()
	require.NoError(t, err)

	// Create second instance from same directory.
	ca2, err := NewLocalCA(dir)
	require.NoError(t, err)

	rootPEM2, err := ca2.RootCAPEM()
	require.NoError(t, err)

	assert.Equal(t, rootPEM1, rootPEM2, "reloaded CA should have the same root cert")
}

func TestLocalCA_GenerateEntityCA(t *testing.T) {
	dir := t.TempDir()

	ca, err := NewLocalCA(dir)
	require.NoError(t, err)

	certPEM, keyPEM, err := ca.GenerateEntityCA("acme-corp")
	require.NoError(t, err)
	require.NotEmpty(t, certPEM)
	require.NotEmpty(t, keyPEM)

	// Parse the entity cert and verify properties.
	block, _ := pem.Decode(certPEM)
	require.NotNil(t, block)
	entityCert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)

	assert.True(t, entityCert.IsCA)
	assert.Equal(t, "acme-corp", entityCert.Subject.CommonName)
	assert.Equal(t, []string{"acme-corp"}, entityCert.Subject.Organization)

	// Verify entity cert is signed by root CA.
	pool := x509.NewCertPool()
	pool.AddCert(ca.rootCert)
	_, err = entityCert.Verify(x509.VerifyOptions{Roots: pool})
	assert.NoError(t, err)
}

func TestLocalCA_GenerateAgentCert(t *testing.T) {
	dir := t.TempDir()

	ca, err := NewLocalCA(dir)
	require.NoError(t, err)

	entityCertPEM, entityKeyPEM, err := ca.GenerateEntityCA("acme-corp")
	require.NoError(t, err)

	agentCertPEM, agentKeyPEM, err := ca.GenerateAgentCert("weather-agent", entityCertPEM, entityKeyPEM)
	require.NoError(t, err)
	require.NotEmpty(t, agentCertPEM)
	require.NotEmpty(t, agentKeyPEM)

	// Parse the agent cert and verify properties.
	block, _ := pem.Decode(agentCertPEM)
	require.NotNil(t, block)
	agentCert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)

	assert.False(t, agentCert.IsCA)
	assert.Equal(t, "weather-agent", agentCert.Subject.CommonName)
	assert.Equal(t, []string{"acme-corp"}, agentCert.Subject.Organization)

	// Verify agent cert chains through entity CA to root CA.
	block, _ = pem.Decode(entityCertPEM)
	require.NotNil(t, block)
	entityCert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)

	rootPool := x509.NewCertPool()
	rootPool.AddCert(ca.rootCert)
	intermediates := x509.NewCertPool()
	intermediates.AddCert(entityCert)

	_, err = agentCert.Verify(x509.VerifyOptions{
		Roots:         rootPool,
		Intermediates: intermediates,
	})
	assert.NoError(t, err)
}

func TestLocalCA_VerifyAcceptsAgentCert(t *testing.T) {
	dir := t.TempDir()

	ca, err := NewLocalCA(dir)
	require.NoError(t, err)

	entityCertPEM, entityKeyPEM, err := ca.GenerateEntityCA("acme-corp")
	require.NoError(t, err)

	agentCertPEM, _, err := ca.GenerateAgentCert("my-agent", entityCertPEM, entityKeyPEM)
	require.NoError(t, err)

	// Parse certs for the chain.
	block, _ := pem.Decode(agentCertPEM)
	require.NotNil(t, block)
	agentCert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)

	block, _ = pem.Decode(entityCertPEM)
	require.NotNil(t, block)
	entityCert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)

	result, err := ca.Verify([]*x509.Certificate{agentCert, entityCert})
	require.NoError(t, err)
	assert.Equal(t, "acme-corp", result.EntityID)
	assert.Equal(t, "localca", result.BackendName)
	assert.Contains(t, result.CertSubject, "my-agent")
}

func TestLocalCA_VerifyRejectsDifferentCA(t *testing.T) {
	dir1 := t.TempDir()
	dir2 := t.TempDir()

	ca1, err := NewLocalCA(dir1)
	require.NoError(t, err)

	ca2, err := NewLocalCA(dir2)
	require.NoError(t, err)

	// Generate certs from ca2.
	entityCertPEM, entityKeyPEM, err := ca2.GenerateEntityCA("other-org")
	require.NoError(t, err)

	agentCertPEM, _, err := ca2.GenerateAgentCert("rogue-agent", entityCertPEM, entityKeyPEM)
	require.NoError(t, err)

	block, _ := pem.Decode(agentCertPEM)
	require.NotNil(t, block)
	agentCert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)

	block, _ = pem.Decode(entityCertPEM)
	require.NotNil(t, block)
	entityCert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)

	// Verify against ca1 should fail.
	_, err = ca1.Verify([]*x509.Certificate{agentCert, entityCert})
	assert.ErrorIs(t, err, ErrUntrustedCert)
}

func TestLocalCA_RootCAPEM(t *testing.T) {
	dir := t.TempDir()

	ca, err := NewLocalCA(dir)
	require.NoError(t, err)

	rootPEM, err := ca.RootCAPEM()
	require.NoError(t, err)

	block, rest := pem.Decode(rootPEM)
	require.NotNil(t, block)
	assert.Equal(t, "CERTIFICATE", block.Type)
	assert.Empty(t, rest)

	cert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)
	assert.True(t, cert.IsCA)
	assert.Equal(t, "MCP Mesh Dev Root CA", cert.Subject.CommonName)
}

func TestLocalCA_ListTrustedEntities(t *testing.T) {
	dir := t.TempDir()

	ca, err := NewLocalCA(dir)
	require.NoError(t, err)

	entities, err := ca.ListTrustedEntities()
	require.NoError(t, err)
	require.Len(t, entities, 1)
	assert.Equal(t, "localca-root", entities[0].ID)
	assert.NotEmpty(t, entities[0].Fingerprint)
	assert.Equal(t, "localca", entities[0].Metadata["source"])
}

func TestLocalCA_VerifyRejectsNoCert(t *testing.T) {
	dir := t.TempDir()

	ca, err := NewLocalCA(dir)
	require.NoError(t, err)

	_, err = ca.Verify(nil)
	assert.ErrorIs(t, err, ErrNoCertPresented)

	_, err = ca.Verify([]*x509.Certificate{})
	assert.ErrorIs(t, err, ErrNoCertPresented)
}

func TestLocalCA_VerifyRejectsExpired(t *testing.T) {
	dir := t.TempDir()

	ca, err := NewLocalCA(dir)
	require.NoError(t, err)

	// Create an expired leaf cert signed by an entity CA from this LocalCA.
	entityCertPEM, entityKeyPEM, err := ca.GenerateEntityCA("expiry-org")
	require.NoError(t, err)

	block, _ := pem.Decode(entityCertPEM)
	require.NotNil(t, block)
	entityCert, err := x509.ParseCertificate(block.Bytes)
	require.NoError(t, err)

	keyBlock, _ := pem.Decode(entityKeyPEM)
	require.NotNil(t, keyBlock)
	entityKey, err := x509.ParseECPrivateKey(keyBlock.Bytes)
	require.NoError(t, err)

	// Generate expired leaf manually.
	leafKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	require.NoError(t, err)
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	require.NoError(t, err)

	leafTemplate := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName:   "expired-agent",
			Organization: []string{"expiry-org"},
		},
		NotBefore: time.Now().Add(-48 * time.Hour),
		NotAfter:  time.Now().Add(-1 * time.Hour),
		KeyUsage:  x509.KeyUsageDigitalSignature,
	}

	leafDER, err := x509.CreateCertificate(rand.Reader, leafTemplate, entityCert, &leafKey.PublicKey, entityKey)
	require.NoError(t, err)
	leafCert, err := x509.ParseCertificate(leafDER)
	require.NoError(t, err)

	_, err = ca.Verify([]*x509.Certificate{leafCert, entityCert})
	assert.ErrorIs(t, err, ErrExpiredCert)
}

func TestLocalCA_CreatesDirectory(t *testing.T) {
	parent := t.TempDir()
	nested := filepath.Join(parent, "sub", "dir")

	ca, err := NewLocalCA(nested)
	require.NoError(t, err)
	assert.FileExists(t, filepath.Join(nested, "ca.pem"))

	_ = ca
}

func TestLocalCA_InvalidExistingFiles(t *testing.T) {
	dir := t.TempDir()

	// Write invalid PEM data.
	require.NoError(t, os.WriteFile(filepath.Join(dir, "ca.pem"), []byte("not a cert"), 0600))
	require.NoError(t, os.WriteFile(filepath.Join(dir, "ca-key.pem"), []byte("not a key"), 0600))

	_, err := NewLocalCA(dir)
	assert.Error(t, err)
}
