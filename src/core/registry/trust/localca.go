package trust

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// LocalCA is a TrustBackend that also generates certificates for dev use.
// It acts as a self-contained mini CA for meshctl start --tls-auto.
type LocalCA struct {
	dir      string
	rootCert *x509.Certificate
	rootKey  crypto.PrivateKey
	rootPool *x509.CertPool
	mu       sync.RWMutex
}

// NewLocalCA creates or loads a LocalCA from the given directory.
// If ca.pem and ca-key.pem exist, loads them. Otherwise generates new ones.
func NewLocalCA(dir string) (*LocalCA, error) {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, fmt.Errorf("creating localca directory: %w", err)
	}

	ca := &LocalCA{dir: dir}

	certPath := filepath.Join(dir, "ca.pem")
	keyPath := filepath.Join(dir, "ca-key.pem")

	certExists := fileExists(certPath)
	keyExists := fileExists(keyPath)

	if certExists && keyExists {
		if err := ca.load(certPath, keyPath); err != nil {
			return nil, fmt.Errorf("loading existing CA: %w", err)
		}
	} else {
		if err := ca.generate(certPath, keyPath); err != nil {
			return nil, fmt.Errorf("generating CA: %w", err)
		}
	}

	ca.rootPool = x509.NewCertPool()
	ca.rootPool.AddCert(ca.rootCert)

	return ca, nil
}

// Name returns the backend name.
func (ca *LocalCA) Name() string {
	return "localca"
}

// Verify checks whether the leaf certificate in certChain is trusted by the root CA.
func (ca *LocalCA) Verify(certChain []*x509.Certificate) (*VerifyResult, error) {
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

	intermediates := x509.NewCertPool()
	for _, c := range certChain[1:] {
		intermediates.AddCert(c)
	}

	ca.mu.RLock()
	defer ca.mu.RUnlock()

	opts := x509.VerifyOptions{
		Roots:         ca.rootPool,
		Intermediates: intermediates,
		KeyUsages:     []x509.ExtKeyUsage{x509.ExtKeyUsageAny},
	}
	if _, err := leaf.Verify(opts); err != nil {
		return nil, ErrUntrustedCert
	}

	entityID := ""
	if len(leaf.Subject.Organization) > 0 {
		entityID = leaf.Subject.Organization[0]
	}

	return &VerifyResult{
		EntityID:    entityID,
		CertSubject: leaf.Subject.String(),
		BackendName: ca.Name(),
	}, nil
}

// ListTrustedEntities returns metadata for the root CA certificate.
func (ca *LocalCA) ListTrustedEntities() ([]TrustedEntity, error) {
	ca.mu.RLock()
	defer ca.mu.RUnlock()

	fingerprint := sha256.Sum256(ca.rootCert.Raw)
	return []TrustedEntity{
		{
			ID:          "localca-root",
			Subject:     ca.rootCert.Subject.String(),
			NotBefore:   ca.rootCert.NotBefore,
			NotAfter:    ca.rootCert.NotAfter,
			Fingerprint: hex.EncodeToString(fingerprint[:]),
			Metadata: map[string]string{
				"source": "localca",
				"dir":    ca.dir,
			},
		},
	}, nil
}

// RootCAPEM returns the root CA certificate in PEM format.
func (ca *LocalCA) RootCAPEM() ([]byte, error) {
	ca.mu.RLock()
	defer ca.mu.RUnlock()

	return pem.EncodeToMemory(&pem.Block{
		Type:  "CERTIFICATE",
		Bytes: ca.rootCert.Raw,
	}), nil
}

// GenerateEntityCA creates a new entity intermediate CA certificate signed by the root CA.
// Returns cert PEM and key PEM bytes.
func (ca *LocalCA) GenerateEntityCA(entityID string) (certPEM []byte, keyPEM []byte, err error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, nil, fmt.Errorf("generating entity key: %w", err)
	}

	serial, err := randomSerial()
	if err != nil {
		return nil, nil, err
	}

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName:   entityID,
			Organization: []string{entityID},
		},
		NotBefore:             time.Now().Add(-5 * time.Minute),
		NotAfter:              time.Now().Add(365 * 24 * time.Hour),
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true,
		IsCA:                  true,
		MaxPathLen:            0,
		MaxPathLenZero:        true,
	}

	ca.mu.RLock()
	certDER, err := x509.CreateCertificate(rand.Reader, template, ca.rootCert, &key.PublicKey, ca.rootKey)
	ca.mu.RUnlock()
	if err != nil {
		return nil, nil, fmt.Errorf("creating entity certificate: %w", err)
	}

	certPEM = pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return nil, nil, fmt.Errorf("marshaling entity key: %w", err)
	}
	keyPEM = pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})

	return certPEM, keyPEM, nil
}

// GenerateAgentCert creates a leaf certificate for an agent, signed by the given entity CA.
// entityCertPEM and entityKeyPEM are the entity CA cert+key used for signing.
// Returns cert PEM and key PEM bytes.
func (ca *LocalCA) GenerateAgentCert(agentName string, entityCertPEM []byte, entityKeyPEM []byte) (certPEM []byte, keyPEM []byte, err error) {
	entityCert, entityKey, err := parseEntityCA(entityCertPEM, entityKeyPEM)
	if err != nil {
		return nil, nil, err
	}

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, nil, fmt.Errorf("generating agent key: %w", err)
	}

	serial, err := randomSerial()
	if err != nil {
		return nil, nil, err
	}

	entityID := ""
	if len(entityCert.Subject.Organization) > 0 {
		entityID = entityCert.Subject.Organization[0]
	}

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName:   agentName,
			Organization: []string{entityID},
		},
		NotBefore:   time.Now().Add(-5 * time.Minute),
		NotAfter:    time.Now().Add(365 * 24 * time.Hour),
		KeyUsage:    x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth},
		// SANs required by modern TLS (rustls, Go 1.15+)
		DNSNames:    []string{agentName, "localhost"},
		IPAddresses: []net.IP{net.IPv4(127, 0, 0, 1), net.IPv6loopback},
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, entityCert, &key.PublicKey, entityKey)
	if err != nil {
		return nil, nil, fmt.Errorf("creating agent certificate: %w", err)
	}

	// Build full cert chain: leaf + entity CA (so TLS peers can verify)
	leafPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	certPEM = append(leafPEM, entityCertPEM...)
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return nil, nil, fmt.Errorf("marshaling agent key: %w", err)
	}
	keyPEM = pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})

	return certPEM, keyPEM, nil
}

func (ca *LocalCA) load(certPath, keyPath string) error {
	certData, err := os.ReadFile(certPath)
	if err != nil {
		return fmt.Errorf("reading CA cert: %w", err)
	}

	block, _ := pem.Decode(certData)
	if block == nil || block.Type != "CERTIFICATE" {
		return fmt.Errorf("invalid CA cert PEM")
	}

	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return fmt.Errorf("parsing CA cert: %w", err)
	}

	keyData, err := os.ReadFile(keyPath)
	if err != nil {
		return fmt.Errorf("reading CA key: %w", err)
	}

	keyBlock, _ := pem.Decode(keyData)
	if keyBlock == nil || keyBlock.Type != "EC PRIVATE KEY" {
		return fmt.Errorf("invalid CA key PEM")
	}

	key, err := x509.ParseECPrivateKey(keyBlock.Bytes)
	if err != nil {
		return fmt.Errorf("parsing CA key: %w", err)
	}

	ca.rootCert = cert
	ca.rootKey = key
	return nil
}

func (ca *LocalCA) generate(certPath, keyPath string) error {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return fmt.Errorf("generating root key: %w", err)
	}

	serial, err := randomSerial()
	if err != nil {
		return err
	}

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName: "MCP Mesh Dev Root CA",
		},
		NotBefore:             time.Now().Add(-5 * time.Minute),
		NotAfter:              time.Now().Add(10 * 365 * 24 * time.Hour),
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true,
		IsCA:                  true,
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return fmt.Errorf("creating root certificate: %w", err)
	}

	cert, err := x509.ParseCertificate(certDER)
	if err != nil {
		return fmt.Errorf("parsing root certificate: %w", err)
	}

	// Persist cert
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	if err := os.WriteFile(certPath, certPEM, 0600); err != nil {
		return fmt.Errorf("writing CA cert: %w", err)
	}

	// Persist key
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return fmt.Errorf("marshaling root key: %w", err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	if err := os.WriteFile(keyPath, keyPEM, 0600); err != nil {
		return fmt.Errorf("writing CA key: %w", err)
	}

	ca.rootCert = cert
	ca.rootKey = key
	return nil
}

func parseEntityCA(certPEM, keyPEM []byte) (*x509.Certificate, *ecdsa.PrivateKey, error) {
	block, _ := pem.Decode(certPEM)
	if block == nil || block.Type != "CERTIFICATE" {
		return nil, nil, fmt.Errorf("invalid entity cert PEM")
	}

	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return nil, nil, fmt.Errorf("parsing entity cert: %w", err)
	}

	keyBlock, _ := pem.Decode(keyPEM)
	if keyBlock == nil || keyBlock.Type != "EC PRIVATE KEY" {
		return nil, nil, fmt.Errorf("invalid entity key PEM")
	}

	key, err := x509.ParseECPrivateKey(keyBlock.Bytes)
	if err != nil {
		return nil, nil, fmt.Errorf("parsing entity key: %w", err)
	}

	return cert, key, nil
}

func randomSerial() (*big.Int, error) {
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return nil, fmt.Errorf("generating serial number: %w", err)
	}
	return serial, nil
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
