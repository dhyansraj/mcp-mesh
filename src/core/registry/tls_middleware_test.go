package registry

import (
	"crypto/tls"
	"crypto/x509"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"mcp-mesh/src/core/registry/trust"
)

// stubBackend implements trust.TrustBackend for testing.
type stubBackend struct {
	result *trust.VerifyResult
	err    error
}

func (s *stubBackend) Verify(certChain []*x509.Certificate) (*trust.VerifyResult, error) {
	return s.result, s.err
}

func (s *stubBackend) ListTrustedEntities() ([]trust.TrustedEntity, error) {
	return nil, nil
}

func (s *stubBackend) Name() string { return "stub" }

func setupRouter(chain *trust.TrustChain, mode string) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(TLSVerifyMiddleware(chain, mode))
	r.GET("/test", func(c *gin.Context) {
		entityID, _ := c.Get("entity_id")
		c.JSON(200, gin.H{"entity_id": entityID})
	})
	return r
}

func TestTLSMiddleware_OffMode_SkipsValidation(t *testing.T) {
	chain := trust.NewTrustChain()
	r := setupRouter(chain, "off")

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
}

func TestTLSMiddleware_StrictMode_NoCert_Returns403(t *testing.T) {
	chain := trust.NewTrustChain()
	r := setupRouter(chain, "strict")

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	// No TLS at all
	r.ServeHTTP(w, req)

	assert.Equal(t, 403, w.Code)
	assert.Contains(t, w.Body.String(), "client certificate required")
}

func TestTLSMiddleware_StrictMode_EmptyPeerCerts_Returns403(t *testing.T) {
	chain := trust.NewTrustChain()
	r := setupRouter(chain, "strict")

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	req.TLS = &tls.ConnectionState{PeerCertificates: []*x509.Certificate{}}
	r.ServeHTTP(w, req)

	assert.Equal(t, 403, w.Code)
}

func TestTLSMiddleware_StrictMode_UntrustedCert_Returns403(t *testing.T) {
	backend := &stubBackend{result: nil, err: trust.ErrUntrustedCert}
	chain := trust.NewTrustChain(backend)
	r := setupRouter(chain, "strict")

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	req.TLS = &tls.ConnectionState{
		PeerCertificates: []*x509.Certificate{{}},
	}
	r.ServeHTTP(w, req)

	assert.Equal(t, 403, w.Code)
	assert.Contains(t, w.Body.String(), "untrusted certificate")
}

func TestTLSMiddleware_StrictMode_TrustedCert_SetsEntityID(t *testing.T) {
	backend := &stubBackend{
		result: &trust.VerifyResult{
			EntityID:    "entity-abc",
			CertSubject: "CN=test",
			BackendName: "stub",
		},
	}
	chain := trust.NewTrustChain(backend)
	r := setupRouter(chain, "strict")

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	req.TLS = &tls.ConnectionState{
		PeerCertificates: []*x509.Certificate{{}},
	}
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	assert.Contains(t, w.Body.String(), "entity-abc")
}

func TestTLSMiddleware_AutoMode_NoCert_Passes(t *testing.T) {
	chain := trust.NewTrustChain()
	r := setupRouter(chain, "auto")

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
}

func TestTLSMiddleware_AutoMode_UntrustedCert_Returns403(t *testing.T) {
	backend := &stubBackend{result: nil, err: trust.ErrUntrustedCert}
	chain := trust.NewTrustChain(backend)
	r := setupRouter(chain, "auto")

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	req.TLS = &tls.ConnectionState{
		PeerCertificates: []*x509.Certificate{{}},
	}
	r.ServeHTTP(w, req)

	assert.Equal(t, 403, w.Code)
	assert.Contains(t, w.Body.String(), "untrusted certificate")
}

func TestTLSMiddleware_AutoMode_TrustedCert_SetsEntityID(t *testing.T) {
	backend := &stubBackend{
		result: &trust.VerifyResult{
			EntityID:    "entity-xyz",
			CertSubject: "CN=auto-test",
			BackendName: "stub",
		},
	}
	chain := trust.NewTrustChain(backend)
	r := setupRouter(chain, "auto")

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test", nil)
	req.TLS = &tls.ConnectionState{
		PeerCertificates: []*x509.Certificate{{}},
	}
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	assert.Contains(t, w.Body.String(), "entity-xyz")
}
