package trust

import (
	"crypto/x509"
	"encoding/pem"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

const testNamespace = "test-ns"

func createTestSecret(name, namespace, entityName string, caCert *x509.Certificate) *corev1.Secret {
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: caCert.Raw})
	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			Labels:    map[string]string{"mcp-mesh.io/trust": "entity-ca"},
		},
		Data: map[string][]byte{
			"ca.crt": certPEM,
		},
	}
	if entityName != "" {
		secret.Annotations = map[string]string{"mcp-mesh.io/entity-name": entityName}
	}
	return secret
}

func TestK8sSecrets_LoadFromSecrets(t *testing.T) {
	ca1, _ := generateCA(t, "entity-alpha")
	ca2, _ := generateCA(t, "entity-beta")

	s1 := createTestSecret("alpha-secret", testNamespace, "entity-alpha", ca1)
	s2 := createTestSecret("beta-secret", testNamespace, "entity-beta", ca2)

	client := fake.NewSimpleClientset(s1, s2)

	ks, err := NewK8sSecrets(client, testNamespace, "")
	require.NoError(t, err)
	defer ks.Close()

	assert.Equal(t, "k8s-secrets", ks.Name())

	entities, err := ks.ListTrustedEntities()
	require.NoError(t, err)
	assert.Len(t, entities, 2)

	ids := map[string]bool{}
	for _, e := range entities {
		ids[e.ID] = true
		assert.NotEmpty(t, e.Fingerprint)
		assert.NotEmpty(t, e.Subject)
		assert.False(t, e.NotBefore.IsZero())
		assert.False(t, e.NotAfter.IsZero())
		assert.Equal(t, "k8s-secrets", e.Metadata["source"])
	}
	assert.True(t, ids["entity-alpha"])
	assert.True(t, ids["entity-beta"])
}

func TestK8sSecrets_VerifyTrustedCert(t *testing.T) {
	ca, caKey := generateCA(t, "trusted-org")
	secret := createTestSecret("trusted-secret", testNamespace, "trusted-org", ca)

	client := fake.NewSimpleClientset(secret)

	ks, err := NewK8sSecrets(client, testNamespace, "")
	require.NoError(t, err)
	defer ks.Close()

	leaf, _ := generateLeaf(t, ca, caKey, "agent-1")

	result, err := ks.Verify([]*x509.Certificate{leaf})
	require.NoError(t, err)
	assert.Equal(t, "trusted-org", result.EntityID)
	assert.Equal(t, "k8s-secrets", result.BackendName)
	assert.Contains(t, result.CertSubject, "agent-1")
}

func TestK8sSecrets_RejectUntrustedCert(t *testing.T) {
	ca, _ := generateCA(t, "known-org")
	secret := createTestSecret("known-secret", testNamespace, "known-org", ca)

	client := fake.NewSimpleClientset(secret)

	ks, err := NewK8sSecrets(client, testNamespace, "")
	require.NoError(t, err)
	defer ks.Close()

	unknownCA, unknownKey := generateCA(t, "unknown-org")
	_ = unknownCA
	leaf, _ := generateLeaf(t, unknownCA, unknownKey, "rogue-agent")

	_, err = ks.Verify([]*x509.Certificate{leaf})
	assert.ErrorIs(t, err, ErrUntrustedCert)
}

func TestK8sSecrets_RejectExpiredCert(t *testing.T) {
	ca, caKey := generateCA(t, "expiry-org")
	secret := createTestSecret("expiry-secret", testNamespace, "expiry-org", ca)

	client := fake.NewSimpleClientset(secret)

	ks, err := NewK8sSecrets(client, testNamespace, "")
	require.NoError(t, err)
	defer ks.Close()

	expired := generateExpiredLeaf(t, ca, caKey, "expired-agent")

	_, err = ks.Verify([]*x509.Certificate{expired})
	assert.ErrorIs(t, err, ErrExpiredCert)
}

func TestK8sSecrets_RejectNoCert(t *testing.T) {
	client := fake.NewSimpleClientset()

	ks, err := NewK8sSecrets(client, testNamespace, "")
	require.NoError(t, err)
	defer ks.Close()

	_, err = ks.Verify(nil)
	assert.ErrorIs(t, err, ErrNoCertPresented)

	_, err = ks.Verify([]*x509.Certificate{})
	assert.ErrorIs(t, err, ErrNoCertPresented)
}

func TestK8sSecrets_EntityIDFromAnnotation(t *testing.T) {
	ca, _ := generateCA(t, "cert-org")
	secret := createTestSecret("my-secret", testNamespace, "custom-entity-name", ca)

	client := fake.NewSimpleClientset(secret)

	ks, err := NewK8sSecrets(client, testNamespace, "")
	require.NoError(t, err)
	defer ks.Close()

	entities, err := ks.ListTrustedEntities()
	require.NoError(t, err)
	require.Len(t, entities, 1)
	assert.Equal(t, "custom-entity-name", entities[0].ID)
}

func TestK8sSecrets_EntityIDFallbackToSecretName(t *testing.T) {
	ca, _ := generateCA(t, "cert-org")
	// No entity name annotation — pass empty string.
	secret := createTestSecret("fallback-secret", testNamespace, "", ca)

	client := fake.NewSimpleClientset(secret)

	ks, err := NewK8sSecrets(client, testNamespace, "")
	require.NoError(t, err)
	defer ks.Close()

	entities, err := ks.ListTrustedEntities()
	require.NoError(t, err)
	require.Len(t, entities, 1)
	assert.Equal(t, "fallback-secret", entities[0].ID)
}

func TestK8sSecrets_SkipsSecretsWithoutCACrt(t *testing.T) {
	ca, _ := generateCA(t, "good-org")
	goodSecret := createTestSecret("good-secret", testNamespace, "good-org", ca)

	// Create a secret without ca.crt key.
	badSecret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "bad-secret",
			Namespace: testNamespace,
			Labels:    map[string]string{"mcp-mesh.io/trust": "entity-ca"},
		},
		Data: map[string][]byte{
			"tls.crt": []byte("not-a-ca"),
		},
	}

	client := fake.NewSimpleClientset(goodSecret, badSecret)

	ks, err := NewK8sSecrets(client, testNamespace, "")
	require.NoError(t, err)
	defer ks.Close()

	entities, err := ks.ListTrustedEntities()
	require.NoError(t, err)
	assert.Len(t, entities, 1)
	assert.Equal(t, "good-org", entities[0].ID)
}

func TestK8sSecrets_EmptyNamespace(t *testing.T) {
	client := fake.NewSimpleClientset()

	ks, err := NewK8sSecrets(client, "empty-ns", "")
	require.NoError(t, err)
	defer ks.Close()

	entities, err := ks.ListTrustedEntities()
	require.NoError(t, err)
	assert.Empty(t, entities)
}
