package registry

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/registry/trust"
)

// newTrustTestDB returns an isolated in-memory database for tests that
// need to construct a full Server via NewServer.
func newTrustTestDB(t *testing.T) *database.EntDatabase {
	t.Helper()
	db, err := database.InitializeEnt(&database.Config{
		DatabaseURL:        ":memory:",
		MaxOpenConnections: 1,
		MaxIdleConnections: 1,
	}, false)
	if err != nil {
		t.Fatalf("init test database: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

// TestNewServer_TLSModeWithoutTrustBackendRefusesToStart pins issue #1600.
// With MCP_MESH_TLS_MODE=auto|strict and no trust backend, the registry used
// to build a zero-backend chain and install the middleware anyway, so a
// client presenting a valid certificate got 403 "no backends configured"
// while a certless client passed in auto: the security property inverted.
// TLS enforcement was requested and cannot be delivered, so NewServer must
// refuse to start, as it does for a configured-but-failed backend (#989).
func TestNewServer_TLSModeWithoutTrustBackendRefusesToStart(t *testing.T) {
	for _, mode := range []string{"auto", "strict"} {
		t.Run(mode, func(t *testing.T) {
			gin.SetMode(gin.TestMode)
			cfg := &RegistryConfig{
				TlsMode:      mode,
				TrustBackend: "",
				TlsCertFile:  "registry-cert.pem",
				TlsKeyFile:   "registry-key.pem",
			}
			s, err := NewServer(newTrustTestDB(t), cfg, createTestLogger(nil))
			if err == nil {
				defer s.shutdownCancel()
				// Describe what the booted registry does to both kinds of
				// client so a regression reports the inversion itself.
				withCert := httptest.NewRecorder()
				req, _ := http.NewRequest("GET", "/health", nil)
				req.TLS = &tls.ConnectionState{PeerCertificates: []*x509.Certificate{{}}}
				s.engine.ServeHTTP(withCert, req)

				certless := httptest.NewRecorder()
				req, _ = http.NewRequest("GET", "/health", nil)
				s.engine.ServeHTTP(certless, req)

				t.Fatalf("NewServer(TlsMode=%q, TrustBackend=\"\") started; want a startup error. "+
					"cert-presenting client -> %d %s; certless client -> %d",
					mode, withCert.Code, strings.TrimSpace(withCert.Body.String()), certless.Code)
			}
			if !strings.Contains(err.Error(), "MCP_MESH_TRUST_BACKEND") {
				t.Errorf("startup error should name MCP_MESH_TRUST_BACKEND so the operator knows what to set, got: %v", err)
			}
		})
	}
}

// TestNewServer_MissingCertReportedBeforeMissingBackend pins the error
// ordering the tc21 integration test relies on: a TLS mode with neither
// cert/key nor a trust backend reports the missing cert/key first.
func TestNewServer_MissingCertReportedBeforeMissingBackend(t *testing.T) {
	cfg := &RegistryConfig{TlsMode: "auto"}
	s, err := NewServer(newTrustTestDB(t), cfg, createTestLogger(nil))
	if err == nil {
		s.shutdownCancel()
		t.Fatal("NewServer(TlsMode=auto) with no cert, key or backend started; want a startup error")
	}
	if !strings.Contains(err.Error(), "requires MCP_MESH_TLS_CERT") {
		t.Errorf("expected the missing cert/key to be reported first, got: %v", err)
	}
}

// TestInitTrustChain_EmptyBackendConfigIsFatal is the unit-level half of
// #1600: an empty MCP_MESH_TRUST_BACKEND must not yield a chain.
func TestInitTrustChain_EmptyBackendConfigIsFatal(t *testing.T) {
	for _, backend := range []string{"", "  ", ","} {
		cfg := &RegistryConfig{TlsMode: "auto", TrustBackend: backend}
		chain, err := initTrustChain(cfg, createTestLogger(nil))
		if err == nil {
			t.Fatalf("TrustBackend=%q: expected an error, got a chain with %d backend(s)", backend, chain.Len())
		}
		if chain != nil {
			t.Errorf("TrustBackend=%q: expected nil chain on error", backend)
		}
		if !strings.Contains(err.Error(), "MCP_MESH_TRUST_BACKEND is empty") {
			t.Errorf("TrustBackend=%q: error should say the backend config is empty, got: %v", backend, err)
		}
	}
}

// cnEntityBackend is a trust backend that trusts every certificate and
// reports its Subject CN as the entity id, so one test can present
// certificates from several entities through the real middleware.
type cnEntityBackend struct{}

func (cnEntityBackend) Verify(chain []*x509.Certificate) (*trust.VerifyResult, error) {
	return &trust.VerifyResult{
		EntityID:    chain[0].Subject.CommonName,
		CertSubject: chain[0].Subject.String(),
		BackendName: "cn-stub",
	}, nil
}
func (cnEntityBackend) ListTrustedEntities() ([]trust.TrustedEntity, error) { return nil, nil }
func (cnEntityBackend) Name() string                                        { return "cn-stub" }

// unregisterTestEngine serves DELETE /agents/:agent_id behind the real
// TLSVerifyMiddleware in the given mode.
func unregisterTestEngine(service *EntService, mode string) *gin.Engine {
	gin.SetMode(gin.TestMode)
	h := NewEntBusinessLogicHandlers(service)
	r := gin.New()
	r.Use(TLSVerifyMiddleware(trust.NewTrustChain(cnEntityBackend{}), mode))
	r.DELETE("/agents/:agent_id", func(c *gin.Context) { h.UnregisterAgent(c, c.Param("agent_id")) })
	return r
}

func seedAgentOwnedBy(t *testing.T, service *EntService, id, entityID string) {
	t.Helper()
	create := service.entDB.Client.Agent.Create().
		SetID(id).
		SetName(id).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC())
	if entityID != "" {
		create = create.SetEntityID(entityID)
	}
	if _, err := create.Save(context.Background()); err != nil {
		t.Fatalf("seed agent %s: %v", id, err)
	}
}

func deleteAgentAs(r *gin.Engine, agentID, entityCN string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("DELETE", "/agents/"+agentID, nil)
	if entityCN != "" {
		req.TLS = &tls.ConnectionState{PeerCertificates: []*x509.Certificate{
			{Subject: pkix.Name{CommonName: entityCN}},
		}}
	}
	r.ServeHTTP(w, req)
	return w
}

func agentStatus(t *testing.T, service *EntService, id string) agent.Status {
	t.Helper()
	a, err := service.entDB.Client.Agent.Get(context.Background(), id)
	if err != nil {
		t.Fatalf("reload agent %s: %v", id, err)
	}
	return a.Status
}

// TestUnregisterAgent_EnforcesEntityOwnership pins issue #1601: DELETE
// /agents/{id} applies the same first-claim-wins rule as registration
// updates and heartbeats.
func TestUnregisterAgent_EnforcesEntityOwnership(t *testing.T) {
	tests := []struct {
		name            string
		mode            string
		owner           string // entity_id stored on the agent row ("" = unclaimed)
		caller          string // entity of the presented cert ("" = certless)
		wantStatus      int
		wantStatusAfter agent.Status
	}{
		{"other entity cannot delete (strict)", "strict", "entity-a", "entity-b", http.StatusForbidden, agent.StatusHealthy},
		{"other entity cannot delete (auto)", "auto", "entity-a", "entity-b", http.StatusForbidden, agent.StatusHealthy},
		{"certless caller cannot delete a claimed agent (auto)", "auto", "entity-a", "", http.StatusForbidden, agent.StatusHealthy},
		{"owner deletes its own agent (strict)", "strict", "entity-a", "entity-a", http.StatusNoContent, agent.StatusUnhealthy},
		{"owner deletes its own agent (auto)", "auto", "entity-a", "entity-a", http.StatusNoContent, agent.StatusUnhealthy},
		// Unclaimed rows match checkEntityOwnership on register/heartbeat:
		// no stored owner means no ownership to enforce. This is the
		// graceful-shutdown path of an agent that registered certless.
		{"certless caller deletes an unclaimed agent (auto)", "auto", "", "", http.StatusNoContent, agent.StatusUnhealthy},
		{"any entity deletes an unclaimed agent (auto)", "auto", "", "entity-b", http.StatusNoContent, agent.StatusUnhealthy},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			service := setupTestService(t)
			seedAgentOwnedBy(t, service, "victim", tc.owner)
			r := unregisterTestEngine(service, tc.mode)

			w := deleteAgentAs(r, "victim", tc.caller)
			if w.Code != tc.wantStatus {
				t.Fatalf("DELETE /agents/victim as %q on agent owned by %q = %d, want %d; body=%s",
					tc.caller, tc.owner, w.Code, tc.wantStatus, w.Body.String())
			}
			if tc.wantStatus == http.StatusForbidden && !strings.Contains(w.Body.String(), "entity_id mismatch") {
				t.Errorf("403 body should match the heartbeat/register shape, got %s", w.Body.String())
			}
			if got := agentStatus(t, service, "victim"); got != tc.wantStatusAfter {
				t.Errorf("agent status after DELETE = %s, want %s", got, tc.wantStatusAfter)
			}
		})
	}
}

// TestUnregisterAgent_UnknownAgentStaysIdempotent pins that the ownership
// check does not turn the idempotent "already gone" case into an error.
func TestUnregisterAgent_UnknownAgentStaysIdempotent(t *testing.T) {
	service := setupTestService(t)
	r := unregisterTestEngine(service, "auto")
	if w := deleteAgentAs(r, "never-registered", "entity-b"); w.Code != http.StatusNoContent {
		t.Fatalf("DELETE unknown agent = %d, want 204; body=%s", w.Code, w.Body.String())
	}
}
