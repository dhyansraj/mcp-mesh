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

// TestInitTrustChain_MissingPrerequisiteIsNonFatal pins the deliberate
// asymmetry from issue #989: "user listed a backend but didn't supply its
// prerequisite config" (filestore listed without MCP_MESH_TRUST_DIR) is treated
// as "operator didn't actually want this backend" — warn and skip, not fatal.
// Only an *attempted* init that *fails* is fatal.
func TestInitTrustChain_MissingPrerequisiteIsNonFatal(t *testing.T) {
	cfg := &RegistryConfig{
		TlsMode:      "verify",
		TrustBackend: "filestore",
		TrustDir:     "", // prerequisite missing → skip, don't fail
	}
	l := createTestLogger(nil)

	chain, err := initTrustChain(cfg, l)
	if err != nil {
		t.Fatalf("missing prerequisite should warn-and-skip, got error: %v", err)
	}
	if chain == nil {
		t.Fatal("expected non-nil (empty) chain when backend skipped")
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
