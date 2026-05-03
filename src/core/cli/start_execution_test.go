package cli

import (
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"sort"
	"testing"
	"time"

	"mcp-mesh/src/core/cli/lifecycle"
)

func TestDetermineExpectedPIDFiles(t *testing.T) {
	tmp := t.TempDir()
	defer lifecycle.WithRoot(tmp)()

	cases := []struct {
		name         string
		agents       []string
		registryOnly bool
		connectOnly  bool
		uiEnabled    bool
		want         []string
	}{
		{
			name:         "registry-only",
			registryOnly: true,
			want:         []string{lifecycle.PIDFile(lifecycle.ServiceRegistry)},
		},
		{
			name:   "single agent",
			agents: []string{"weather"},
			want:   []string{lifecycle.PIDFile("weather")},
		},
		{
			name:   "multiple agents",
			agents: []string{"a1", "a2", "a3"},
			want: []string{
				lifecycle.PIDFile("a1"),
				lifecycle.PIDFile("a2"),
				lifecycle.PIDFile("a3"),
			},
		},
		{
			name:        "connect-only with agent waits only on agent",
			agents:      []string{"weather"},
			connectOnly: true,
			want:        []string{lifecycle.PIDFile("weather")},
		},
		{
			name:        "connect-only with no agents has nothing to wait for",
			connectOnly: true,
			want:        nil,
		},
		{
			name:      "ui-only",
			uiEnabled: true,
			want:      []string{lifecycle.PIDFile(lifecycle.ServiceUI)},
		},
		{
			name: "no flags falls back to registry",
			want: []string{lifecycle.PIDFile(lifecycle.ServiceRegistry)},
		},
		{
			name:      "agents + ui still waits on agents only",
			agents:    []string{"weather"},
			uiEnabled: true,
			want:      []string{lifecycle.PIDFile("weather")},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := determineExpectedPIDFiles(tc.agents, tc.registryOnly, tc.connectOnly, tc.uiEnabled)
			sort.Strings(got)
			want := append([]string(nil), tc.want...)
			sort.Strings(want)
			if !reflect.DeepEqual(got, want) {
				t.Errorf("determineExpectedPIDFiles = %v, want %v", got, want)
			}
		})
	}
}

func TestWaitForChildPIDFiles_AllAppear(t *testing.T) {
	dir := t.TempDir()
	want := []string{filepath.Join(dir, "a.pid"), filepath.Join(dir, "b.pid")}

	// Long-running fake child that creates both files after a brief delay.
	cmd := exec.Command("sh", "-c", "sleep 0.2 && touch "+want[0]+" && touch "+want[1]+" && sleep 5")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start fake child: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}()

	if err := waitForChildPIDFiles(cmd, want, 5*time.Second); err != nil {
		t.Fatalf("waitForChildPIDFiles: %v", err)
	}
}

func TestWaitForChildPIDFiles_ChildExitsBeforeWriting(t *testing.T) {
	dir := t.TempDir()
	want := []string{filepath.Join(dir, "never.pid")}

	cmd := exec.Command("sh", "-c", "exit 0")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start fake child: %v", err)
	}
	defer func() { _, _ = cmd.Process.Wait() }()

	err := waitForChildPIDFiles(cmd, want, 2*time.Second)
	if err == nil {
		t.Fatal("expected error when child exits without writing PID files")
	}
}

func TestWaitForChildPIDFiles_Timeout(t *testing.T) {
	dir := t.TempDir()
	want := []string{filepath.Join(dir, "never.pid")}

	// Long-running child that NEVER creates the file.
	cmd := exec.Command("sleep", "10")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start fake child: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}()

	start := time.Now()
	err := waitForChildPIDFiles(cmd, want, 200*time.Millisecond)
	elapsed := time.Since(start)
	if err == nil {
		t.Fatal("expected timeout error")
	}
	// Sanity: should bail near the deadline, not wait forever.
	if elapsed > 2*time.Second {
		t.Errorf("elapsed = %v, expected ~200ms", elapsed)
	}
}

func TestWaitForChildPIDFiles_MultipleAgents(t *testing.T) {
	dir := t.TempDir()
	want := []string{
		filepath.Join(dir, "a1.pid"),
		filepath.Join(dir, "a2.pid"),
		filepath.Join(dir, "a3.pid"),
	}

	// Stagger the file creation so the helper has to keep polling after the
	// first file appears.
	cmd := exec.Command("sh", "-c",
		"touch "+want[0]+" && sleep 0.1 && touch "+want[1]+" && sleep 0.1 && touch "+want[2]+" && sleep 5")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start fake child: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}()

	if err := waitForChildPIDFiles(cmd, want, 5*time.Second); err != nil {
		t.Fatalf("waitForChildPIDFiles: %v", err)
	}
	for _, f := range want {
		if _, err := os.Stat(f); err != nil {
			t.Errorf("expected %s to exist: %v", f, err)
		}
	}
}

func TestWaitForChildPIDFiles_FilesAlreadyPresent(t *testing.T) {
	dir := t.TempDir()
	want := []string{filepath.Join(dir, "ready.pid")}
	if err := os.WriteFile(want[0], []byte("123"), 0644); err != nil {
		t.Fatalf("seed: %v", err)
	}

	cmd := exec.Command("sleep", "5")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}()

	start := time.Now()
	if err := waitForChildPIDFiles(cmd, want, 5*time.Second); err != nil {
		t.Fatalf("waitForChildPIDFiles: %v", err)
	}
	if elapsed := time.Since(start); elapsed > 50*time.Millisecond {
		t.Errorf("should return immediately when files exist, took %v", elapsed)
	}
}
