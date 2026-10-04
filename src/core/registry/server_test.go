package registry

import (
	"path/filepath"
	"strings"
	"testing"
)

// TestInitTrustChain_FailsFastOnBackendInitError pins the issue #989 fix:
// when a backend is explicitly configured (filestore + MCP_MESH_TRUST_DIR set)
// but its init fails (here: dir does not exist), initTrustChain must return
// an error so the registry refuses to boot. The pre-fix behavior silently
// dropped the backend, leaving a 0-backend chain that rejected every
// heartbeat with "no backends configured".
func TestInitTrustChain_FailsFastOnBackendInitError(t *testing.T) {
	cfg := &RegistryConfig{
		TlsMode:      "verify",
		TrustBackend: "filestore",
		TrustDir:     filepath.Join(t.TempDir(), "definitely-not-here"),
	}
	l := createTestLogger(nil)

	chain, err := initTrustChain(cfg, l)
	if err == nil {
		t.Fatal("expected initTrustChain to return an error when filestore dir is missing")
	}
	if chain != nil {
		t.Errorf("expected nil chain on error, got %v", chain)
	}
	if !strings.Contains(err.Error(), "filestore") {
		t.Errorf("expected error to mention filestore backend, got: %v", err)
	}
}

// TestInitTrustChain_UnknownBackendIsFatal pins that a typo in
// MCP_MESH_TRUST_BACKEND is a hard error rather than a silent skip — limping
// along with no backends would mask the operator's config bug (issue #989).
func TestInitTrustChain_UnknownBackendIsFatal(t *testing.T) {
	cfg := &RegistryConfig{
		TlsMode:      "verify",
		TrustBackend: "filestoer", // typo
		TrustDir:     t.TempDir(),
	}
	l := createTestLogger(nil)

	chain, err := initTrustChain(cfg, l)
	if err == nil {
		t.Fatal("expected initTrustChain to reject unknown backend names")
	}
	if chain != nil {
		t.Errorf("expected nil chain on error, got %v", chain)
	}
	if !strings.Contains(err.Error(), "unknown trust backend") {
		t.Errorf("expected error to mention unknown backend, got: %v", err)
	}
}

// TestInitTrustChain_SkippingEveryBackendIsFatal pins where the issue #989
// warn-and-skip for a missing prerequisite (filestore listed without
// MCP_MESH_TRUST_DIR) stops: skipping one backend is non-fatal, but when it
// leaves the chain empty the registry would reject every presented cert
// while admitting certless clients in auto mode (issue #1600), so it is fatal.
func TestInitTrustChain_SkippingEveryBackendIsFatal(t *testing.T) {
	cfg := &RegistryConfig{
		TlsMode:      "verify",
		TrustBackend: "filestore",
		TrustDir:     "", // prerequisite missing → skipped → nothing left
	}
	l := createTestLogger(nil)

	chain, err := initTrustChain(cfg, l)
	if err == nil {
		t.Fatalf("expected an error when every backend is skipped, got a chain with %d backend(s)", chain.Len())
	}
	if !strings.Contains(err.Error(), "skipped because MCP_MESH_TRUST_DIR is unset") {
		t.Errorf("expected the no-backend error, got: %v", err)
	}
}

// TestInitTrustChain_HappyPath verifies a real filestore directory produces
// a populated chain so the regression tests above don't accidentally pass
// because initTrustChain always fails.
func TestInitTrustChain_HappyPath(t *testing.T) {
	cfg := &RegistryConfig{
		TlsMode:      "verify",
		TrustBackend: "filestore",
		TrustDir:     t.TempDir(), // exists, just empty
	}
	l := createTestLogger(nil)

	chain, err := initTrustChain(cfg, l)
	if err != nil {
		t.Fatalf("happy path returned error: %v", err)
	}
	if chain == nil {
		t.Fatal("happy path returned nil chain")
	}
}
