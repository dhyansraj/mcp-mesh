package registry

// Coverage for issue #1583's listener work: graceful shutdown of every
// listener the registry starts, and the admin listener inheriting the
// main listener's limits, TLS and client-certificate policy.

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/registry/trust"
)

// freePort returns a port that was free a moment ago. Used where the
// code under test binds the port itself and gives no way to ask which
// one it got.
func freePort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserving a port: %v", err)
	}
	port := l.Addr().(*net.TCPAddr).Port
	if err := l.Close(); err != nil {
		t.Fatalf("closing reservation listener: %v", err)
	}
	return port
}

// waitForListener polls until the address accepts a connection.
func waitForListener(t *testing.T, addr string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		conn, err := net.DialTimeout("tcp", addr, 200*time.Millisecond)
		if err == nil {
			_ = conn.Close()
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("listener at %s never came up", addr)
}

// writeSelfSignedCert writes a throwaway server cert/key pair and
// returns their paths.
func writeSelfSignedCert(t *testing.T) (certPath, keyPath string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generating key: %v", err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "registry-test"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(time.Hour),
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		IPAddresses:           []net.IP{net.ParseIP("127.0.0.1"), net.ParseIP("::1")},
		DNSNames:              []string{"localhost"},
		IsCA:                  true,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("creating certificate: %v", err)
	}
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatalf("marshalling key: %v", err)
	}

	dir := t.TempDir()
	certPath = filepath.Join(dir, "tls.crt")
	keyPath = filepath.Join(dir, "tls.key")
	if err := os.WriteFile(certPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0o600); err != nil {
		t.Fatalf("writing cert: %v", err)
	}
	if err := os.WriteFile(keyPath, pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER}), 0o600); err != nil {
		t.Fatalf("writing key: %v", err)
	}
	return certPath, keyPath
}

// newListenerTestServer builds the minimum Server needed to exercise the
// listener paths: an engine, a config and a logger.
func newListenerTestServer(t *testing.T, cfg *RegistryConfig) *Server {
	t.Helper()
	gin.SetMode(gin.TestMode)
	service := setupTestService(t)

	engine := gin.New()
	engine.GET("/ping", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"ok": true}) })
	engine.GET("/slow", func(c *gin.Context) {
		time.Sleep(300 * time.Millisecond)
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})

	return &Server{
		engine:       engine,
		service:      service,
		config:       cfg,
		logger:       service.logger,
		maxBodyBytes: defaultMaxRequestBodyBytes,
	}
}

func TestRunPlaintext_ShutdownStopsTheListener(t *testing.T) {
	s := newListenerTestServer(t, &RegistryConfig{TlsMode: "off"})
	addr := fmt.Sprintf("127.0.0.1:%d", freePort(t))

	runErr := make(chan error, 1)
	go func() { runErr <- s.runPlaintext(addr) }()
	waitForListener(t, addr)

	// The listener the plaintext path built must carry the limits — the
	// bug was that gin's Run built one we never got to configure.
	s.httpMu.Lock()
	if len(s.httpServers) != 1 {
		s.httpMu.Unlock()
		t.Fatalf("registered %d listeners, want 1", len(s.httpServers))
	}
	srv := s.httpServers[0]
	s.httpMu.Unlock()
	if srv.ReadHeaderTimeout != defaultReadHeaderTimeout || srv.IdleTimeout != defaultIdleTimeout ||
		srv.MaxHeaderBytes != defaultMaxHeaderBytes {
		t.Errorf("plaintext listener not hardened: readHeader=%v idle=%v maxHeader=%d",
			srv.ReadHeaderTimeout, srv.IdleTimeout, srv.MaxHeaderBytes)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := s.Shutdown(ctx); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}

	select {
	case err := <-runErr:
		if err != nil {
			t.Fatalf("runPlaintext returned %v, want nil after a graceful shutdown", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("runPlaintext did not return after Shutdown")
	}

	if conn, err := net.DialTimeout("tcp", addr, 500*time.Millisecond); err == nil {
		_ = conn.Close()
		t.Fatal("listener still accepting connections after Shutdown")
	}
}

func TestShutdown_WaitsForInFlightRequest(t *testing.T) {
	s := newListenerTestServer(t, &RegistryConfig{TlsMode: "off"})
	addr := fmt.Sprintf("127.0.0.1:%d", freePort(t))

	go func() { _ = s.runPlaintext(addr) }()
	waitForListener(t, addr)

	type result struct {
		status int
		err    error
	}
	done := make(chan result, 1)
	go func() {
		resp, err := http.Get("http://" + addr + "/slow")
		if err != nil {
			done <- result{err: err}
			return
		}
		defer resp.Body.Close()
		done <- result{status: resp.StatusCode}
	}()

	// Give the request time to arrive at the handler, then shut down
	// underneath it. The in-flight call must still complete.
	time.Sleep(100 * time.Millisecond)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := s.Shutdown(ctx); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}

	select {
	case r := <-done:
		if r.err != nil {
			t.Fatalf("in-flight request was cut by shutdown: %v", r.err)
		}
		if r.status != http.StatusOK {
			t.Fatalf("in-flight request returned %d, want 200", r.status)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("in-flight request never completed")
	}
}

// TestShutdownBeforeRun_DoesNotStartListening closes the window where a
// signal arrives before Run reaches the listener: without the stopping
// flag the listener would come up after Shutdown had already walked the
// (empty) list and returned.
func TestShutdownBeforeRun_DoesNotStartListening(t *testing.T) {
	s := newListenerTestServer(t, &RegistryConfig{TlsMode: "off"})
	addr := fmt.Sprintf("127.0.0.1:%d", freePort(t))

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := s.Shutdown(ctx); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}

	if err := s.runPlaintext(addr); err != nil {
		t.Fatalf("runPlaintext after Shutdown returned %v, want nil", err)
	}
	if conn, err := net.DialTimeout("tcp", addr, 300*time.Millisecond); err == nil {
		_ = conn.Close()
		t.Fatal("runPlaintext started listening after Shutdown")
	}
}

func TestStartAdminServer_HardenedAndShutdownAware(t *testing.T) {
	port := freePort(t)
	s := newListenerTestServer(t, &RegistryConfig{TlsMode: "off", AdminPort: port})

	s.startAdminServer(port)
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	waitForListener(t, addr)

	s.httpMu.Lock()
	if len(s.httpServers) != 1 {
		s.httpMu.Unlock()
		t.Fatalf("admin listener not registered for shutdown (%d registered)", len(s.httpServers))
	}
	srv := s.httpServers[0]
	s.httpMu.Unlock()

	if srv.ReadHeaderTimeout != defaultReadHeaderTimeout || srv.IdleTimeout != defaultIdleTimeout ||
		srv.MaxHeaderBytes != defaultMaxHeaderBytes {
		t.Errorf("admin listener not hardened: readHeader=%v idle=%v maxHeader=%d",
			srv.ReadHeaderTimeout, srv.IdleTimeout, srv.MaxHeaderBytes)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := s.Shutdown(ctx); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}
	if conn, err := net.DialTimeout("tcp", addr, 500*time.Millisecond); err == nil {
		_ = conn.Close()
		t.Fatal("admin listener still accepting connections after Shutdown")
	}
}

// TestStartAdminServer_PlaintextByDefaultOnATLSRegistry is the
// compatibility case, and it is the shape the tc11 integration test
// exercises: TLS configured on the main port, MCP_MESH_ADMIN_PORT set,
// MCP_MESH_ADMIN_TLS unset. The admin port must stay plain http, because
// every existing admin client (curl in tc11, meshctl registry drain)
// addresses it as http:// and meshctl cannot present a client cert.
func TestStartAdminServer_PlaintextByDefaultOnATLSRegistry(t *testing.T) {
	certPath, keyPath := writeSelfSignedCert(t)
	port := freePort(t)
	s := newListenerTestServer(t, &RegistryConfig{
		TlsMode:     "auto",
		TlsCertFile: certPath,
		TlsKeyFile:  keyPath,
		AdminPort:   port,
		// AdminTLS deliberately unset.
	})
	s.trustChain = trust.NewTrustChain()

	s.startAdminServer(port)
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	waitForListener(t, addr)
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = s.Shutdown(ctx)
	}()

	resp, err := http.Post("http://"+addr+"/admin/rotate", "application/json", nil)
	if err != nil {
		t.Fatalf("plaintext POST to the admin port failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("admin rotate over plain http = %d, want 200 (tc11 asserts this); body=%s",
			resp.StatusCode, body)
	}
}

// TestStartAdminServer_ServesTLSWhenAdminTLSOptIn is the opt-in
// transport-parity case: with MCP_MESH_ADMIN_TLS set, the admin port
// speaks TLS with the registry's certificate rather than cleartext.
func TestStartAdminServer_ServesTLSWhenAdminTLSOptIn(t *testing.T) {
	certPath, keyPath := writeSelfSignedCert(t)
	port := freePort(t)
	s := newListenerTestServer(t, &RegistryConfig{
		TlsMode:     "auto",
		TlsCertFile: certPath,
		TlsKeyFile:  keyPath,
		AdminPort:   port,
		AdminTLS:    true,
	})

	s.startAdminServer(port)
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	waitForListener(t, addr)
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = s.Shutdown(ctx)
	}()

	// A plaintext request must NOT be served: before #1583 that was the
	// only thing the admin port spoke. Go's TLS server answers a cleartext
	// request with a 400 and a fixed message rather than closing, so the
	// assertion is "not the handler's response".
	if resp, err := http.Get("http://" + addr + "/admin/drain"); err == nil {
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode != http.StatusBadRequest || !strings.Contains(string(body), "HTTP request to an HTTPS server") {
			t.Fatalf("admin port served plaintext HTTP: status=%d body=%s", resp.StatusCode, body)
		}
	}

	client := &http.Client{Transport: &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}}
	resp, err := client.Get("https://" + addr + "/admin/drain")
	if err != nil {
		t.Fatalf("HTTPS request to the admin port failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("admin drain status over TLS = %d, want 200", resp.StatusCode)
	}
}

// TestAdminEngine_TrustMiddlewareIsOptIn covers both halves of the
// MCP_MESH_ADMIN_TLS switch. Default OFF is the compatibility contract:
// even in strict mode a certless caller reaches /admin/*, because
// meshctl has no way to present a client certificate and
// 'meshctl registry drain' is the documented pre-upgrade step. Opted
// in, the admin engine follows MCP_MESH_TLS_MODE exactly like the main
// engine.
func TestAdminEngine_TrustMiddlewareIsOptIn(t *testing.T) {
	tests := []struct {
		name       string
		mode       string
		adminTLS   bool
		trustChain *trust.TrustChain
		wantStatus int
	}{
		{
			name:       "default off: strict still admits a certless admin caller",
			mode:       "strict",
			adminTLS:   false,
			trustChain: trust.NewTrustChain(),
			wantStatus: http.StatusOK,
		},
		{
			name:       "opt-in: strict rejects a certless admin caller",
			mode:       "strict",
			adminTLS:   true,
			trustChain: trust.NewTrustChain(),
			wantStatus: http.StatusForbidden,
		},
		{
			name:       "opt-in: auto still admits a certless admin caller",
			mode:       "auto",
			adminTLS:   true,
			trustChain: trust.NewTrustChain(),
			wantStatus: http.StatusOK,
		},
		{
			name:       "opt-in without a trust chain leaves the engine unchanged",
			mode:       "off",
			adminTLS:   true,
			trustChain: nil,
			wantStatus: http.StatusOK,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			certPath, keyPath := writeSelfSignedCert(t)
			s := newListenerTestServer(t, &RegistryConfig{
				TlsMode:     tc.mode,
				TlsCertFile: certPath,
				TlsKeyFile:  keyPath,
				AdminTLS:    tc.adminTLS,
			})
			s.trustChain = tc.trustChain

			srv := httptest.NewServer(s.newAdminEngine())
			defer srv.Close()

			resp, err := http.Get(srv.URL + "/admin/drain")
			if err != nil {
				t.Fatalf("GET /admin/drain: %v", err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != tc.wantStatus {
				t.Fatalf("status = %d, want %d", resp.StatusCode, tc.wantStatus)
			}
		})
	}
}

// TestAdminEngine_CapsRequestBodies pins the second piece of engine
// parity: the admin engine is constructed separately, so the body cap
// has to be repeated on it or /admin/* is uncapped.
func TestAdminEngine_CapsRequestBodies(t *testing.T) {
	s := newListenerTestServer(t, &RegistryConfig{TlsMode: "off"})
	s.maxBodyBytes = 1024

	srv := httptest.NewServer(s.newAdminEngine())
	defer srv.Close()

	resp, err := http.Post(srv.URL+"/admin/drain", "application/json",
		strings.NewReader(oversizedJSON(4096)))
	if err != nil {
		t.Fatalf("POST /admin/drain: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want 413", resp.StatusCode)
	}
}
