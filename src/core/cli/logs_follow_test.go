package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// syncBuffer is a goroutine-safe bytes.Buffer for capturing follower output.
type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// TestFollowLogSurvivesRotation verifies tail -F semantics: `logs -f` must
// keep streaming after RotateLogs renames the file and a fresh one is created
// at the same path. Pre-fix, followLog only handled fsnotify.Write and
// blocked forever on the renamed inode.
//
// Writes are nudged in a poll loop rather than written once: fsnotify watch
// arming races with the test's first write, and a lost first write would be
// a test-harness flake, not the regression under test. The nudges cannot mask
// a real rotation bug — with the old code the watch stays on the renamed
// inode, so no amount of writes to the NEW file produces events.
func TestFollowLogSurvivesRotation(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "agent.log")
	if err := os.WriteFile(logPath, nil, 0644); err != nil {
		t.Fatal(err)
	}

	file, err := os.Open(logPath)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()

	out := &syncBuffer{}
	done := make(chan struct{})
	errCh := make(chan error, 1)
	go func() {
		errCh <- followLogTo(out, file, logPath, 0, nil, nil, done)
	}()

	appendLine := func(line string) {
		f, err := os.OpenFile(logPath, os.O_APPEND|os.O_WRONLY, 0644)
		if err != nil {
			t.Fatalf("append to %s: %v", logPath, err)
		}
		if _, err := f.WriteString(line + "\n"); err != nil {
			t.Fatalf("write line: %v", err)
		}
		f.Close()
	}

	waitContains := func(needle string, nudge func()) bool {
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			if strings.Contains(out.String(), needle) {
				return true
			}
			if nudge != nil {
				nudge()
			}
			time.Sleep(100 * time.Millisecond)
		}
		return strings.Contains(out.String(), needle)
	}

	// First half: confirm the follower is streaming pre-rotation.
	if !waitContains("first-half", func() { appendLine("first-half") }) {
		close(done)
		t.Fatal("follower never streamed pre-rotation content")
	}

	// Rotate: rename away + create a fresh file at the same path (this is
	// what RotateLogs + CreateLogFile do on agent restart).
	if err := os.Rename(logPath, logPath+".1"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(logPath, nil, 0644); err != nil {
		t.Fatal(err)
	}

	// Second half: the follower must pick up the NEW file.
	if !waitContains("second-half", func() { appendLine("second-half") }) {
		close(done)
		t.Fatal("follower did not stream content from the new file after rotation")
	}

	close(done)
	select {
	case err := <-errCh:
		if err != nil {
			t.Errorf("followLogTo returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Error("follower did not stop after done was closed")
	}
}
