package lifecycle

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRootDefault(t *testing.T) {
	// Clear any existing override and env var.
	defer WithRoot("")()
	prev := os.Getenv(envHome)
	os.Unsetenv(envHome)
	defer os.Setenv(envHome, prev)

	got := Root()
	home, err := os.UserHomeDir()
	if err != nil {
		t.Skipf("UserHomeDir unavailable: %v", err)
	}
	want := filepath.Join(home, ".mcp-mesh")
	if got != want {
		t.Errorf("Root() = %q, want %q", got, want)
	}
}

func TestRootEnvOverride(t *testing.T) {
	defer WithRoot("")()
	prev := os.Getenv(envHome)
	defer os.Setenv(envHome, prev)
	os.Setenv(envHome, "/tmp/custom-mesh-root")

	if got := Root(); got != "/tmp/custom-mesh-root" {
		t.Errorf("Root() with env = %q, want /tmp/custom-mesh-root", got)
	}
}

func TestWithRoot(t *testing.T) {
	tmp := t.TempDir()
	restore := WithRoot(tmp)
	if got := Root(); got != tmp {
		t.Errorf("Root() inside WithRoot = %q, want %q", got, tmp)
	}
	restore()
	// After restore the override is gone — root is back to env/home default.
	if got := Root(); got == tmp {
		t.Errorf("Root() after restore should not still equal %q", tmp)
	}
}

func TestPathHelpers(t *testing.T) {
	defer WithRoot("/tmp/lc-test")()

	cases := map[string]string{
		PIDFile("foo"):                                   "/tmp/lc-test/pids/foo.pid",
		GroupFile("foo"):                                 "/tmp/lc-test/pids/foo.group",
		WrapperPIDFile(GroupID("g1")):                    "/tmp/lc-test/pids/wrapper-g1.pid",
		RegistryDepsFile(GroupID("g1")):                  "/tmp/lc-test/registry/deps/g1",
		UIDepsFile(GroupID("g1")):                        "/tmp/lc-test/ui/deps/g1",
		LockFile():                                       "/tmp/lc-test/lifecycle.lock",
		RegistryStartLock():                              "/tmp/lc-test/registry/start.lock",
		UIStartLock():                                    "/tmp/lc-test/ui/start.lock",
		PIDsDir():                                        "/tmp/lc-test/pids",
		RegistryDepsDir():                                "/tmp/lc-test/registry/deps",
		UIDepsDir():                                      "/tmp/lc-test/ui/deps",
		filepath.Join(PIDsDir(), "wrapper-some.group.pid"): "/tmp/lc-test/pids/wrapper-some.group.pid",
	}
	for got, want := range cases {
		if got != want {
			t.Errorf("got %q, want %q", got, want)
		}
	}
}

func TestEnsureDirs(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	if err := EnsureDirs(); err != nil {
		t.Fatalf("EnsureDirs: %v", err)
	}
	for _, d := range []string{PIDsDir(), RegistryDepsDir(), UIDepsDir()} {
		st, err := os.Stat(d)
		if err != nil {
			t.Errorf("missing dir %s: %v", d, err)
			continue
		}
		if !st.IsDir() {
			t.Errorf("%s is not a directory", d)
		}
		if !strings.HasPrefix(d, tmp) {
			t.Errorf("dir %s not under tmp root %s", d, tmp)
		}
	}
}
