package lifecycle

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRootDefault(t *testing.T) {
	// Clear any existing override and env var. We use t.Setenv to register the
	// auto-restore (via t.Cleanup), then immediately Unsetenv so Root() falls
	// through to the home-dir default. Cleanup restores the original value.
	defer WithRoot("")()
	t.Setenv(envHome, "")
	os.Unsetenv(envHome)

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
	override := filepath.Join(t.TempDir(), "custom-mesh-root")
	t.Setenv(envHome, override)

	if got := Root(); got != override {
		t.Errorf("Root() with env = %q, want %q", got, override)
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
	root := t.TempDir()
	defer WithRoot(root)()

	cases := map[string]string{
		PIDFile("foo"):                  filepath.Join(root, "pids", "foo.pid"),
		GroupFile("foo"):                filepath.Join(root, "pids", "foo.group"),
		WrapperPIDFile(GroupID("g1")):   filepath.Join(root, "pids", "wrapper-g1.pid"),
		RegistryDepsFile(GroupID("g1")): filepath.Join(root, "registry", "deps", "g1"),
		UIDepsFile(GroupID("g1")):       filepath.Join(root, "ui", "deps", "g1"),
		LockFile():                      filepath.Join(root, "lifecycle.lock"),
		RegistryStartLock():             filepath.Join(root, "registry", "start.lock"),
		UIStartLock():                   filepath.Join(root, "ui", "start.lock"),
		PIDsDir():                       filepath.Join(root, "pids"),
		RegistryDepsDir():               filepath.Join(root, "registry", "deps"),
		UIDepsDir():                     filepath.Join(root, "ui", "deps"),
		filepath.Join(PIDsDir(), "wrapper-some.group.pid"): filepath.Join(root, "pids", "wrapper-some.group.pid"),
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
