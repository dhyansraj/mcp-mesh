package registry

// Coverage for issue #1606: a registry stop wakes parked job-event
// long-polls instead of letting them hold the HTTP drain open until its
// deadline, and the early return is indistinguishable from an expired
// wait — empty page, cursor echoed back, claim untouched.

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/registry/generated"
)

// startTestRegistry builds a real Server on db (TLS off) and runs it on a
// free loopback port. Returns the server and its base URL.
func startTestRegistry(t *testing.T, db *database.EntDatabase) (*Server, string, <-chan error) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	s, err := NewServer(db, &RegistryConfig{
		TlsMode:                  "off",
		DefaultTimeoutThreshold:  60,
		DefaultEvictionThreshold: 120,
		HealthCheckInterval:      30,
	}, createTestLogger(nil))
	require.NoError(t, err)

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	addr := ln.Addr().String()
	require.NoError(t, ln.Close())

	runErr := make(chan error, 1)
	go func() { runErr <- s.Run(addr) }()

	base := "http://" + addr
	require.Eventually(t, func() bool {
		resp, err := http.Get(base + "/health")
		if err != nil {
			return false
		}
		resp.Body.Close()
		return true
	}, 5*time.Second, 20*time.Millisecond, "registry never came up")
	return s, base, runErr
}

type pollResult struct {
	status int
	body   generated.JobEventListResponse
	err    error
	took   time.Duration
}

func longPoll(url string) <-chan pollResult {
	out := make(chan pollResult, 1)
	go func() {
		start := time.Now()
		resp, err := http.Get(url)
		if err != nil {
			out <- pollResult{err: err, took: time.Since(start)}
			return
		}
		defer resp.Body.Close()
		var body generated.JobEventListResponse
		if resp.StatusCode == http.StatusOK {
			err = json.NewDecoder(resp.Body).Decode(&body)
		}
		out <- pollResult{status: resp.StatusCode, body: body, err: err, took: time.Since(start)}
	}()
	return out
}

func TestStop_WakesParkedJobEventLongPolls(t *testing.T) {
	db := newTrustTestDB(t)
	s, base, runErr := startTestRegistry(t, db)
	ctx := context.Background()

	// The executor is a live agent, so a restarted registry's sweep does
	// not reroute its claim as orphaned.
	seedAgentOwnedBy(t, s.service, "replica-a", "")
	seed := seedJob(t, s.service, "job-drain", "render", nil)
	claimed := claimVia(t, s.service, "render", "replica-a")
	seq, _, err := s.service.PostJobEvent(ctx, seed.ID, "progress", map[string]interface{}{"n": 1}, nil, "test", false)
	require.NoError(t, err)
	require.Equal(t, int64(1), seq)

	before, err := s.service.GetJob(ctx, seed.ID)
	require.NoError(t, err)

	// One executor read (fenced, lease-crediting) and one observer read,
	// both caught up to the cursor and parked for the full 60s.
	executor := longPoll(fmt.Sprintf("%s/jobs/%s/events?after=1&wait=60&instance_id=replica-a&claim_epoch=%d",
		base, seed.ID, claimed.ClaimEpoch))
	observer := longPoll(fmt.Sprintf("%s/jobs/%s/events?after=1&wait=60", base, seed.ID))
	require.Eventually(t, func() bool { return s.service.parkedLongPolls.Load() == 2 },
		5*time.Second, 10*time.Millisecond, "both long-polls should be parked before Stop")

	stopStart := time.Now()
	require.NoError(t, s.Stop())
	stopTook := time.Since(stopStart)
	require.Less(t, stopTook, 2*time.Second,
		"Stop took %s; parked long-polls held the HTTP drain toward its %s deadline", stopTook, shutdownHTTPTimeout)

	for name, ch := range map[string]<-chan pollResult{"executor": executor, "observer": observer} {
		select {
		case r := <-ch:
			require.NoError(t, r.err, "%s long-poll", name)
			require.Equal(t, http.StatusOK, r.status, "%s long-poll should get a clean 200, not an error", name)
			require.Empty(t, r.body.Events, "%s long-poll", name)
			require.Equal(t, int64(1), r.body.NextAfter, "%s long-poll must echo its cursor back unchanged", name)
			require.Less(t, r.took, 10*time.Second, "%s long-poll waited out its wait", name)
		case <-time.After(5 * time.Second):
			t.Fatalf("%s long-poll still parked after Stop", name)
		}
	}
	select {
	case err := <-runErr:
		require.NoError(t, err)
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return after Stop")
	}
	require.Zero(t, s.service.parkedLongPolls.Load(), "a long-poll is still parked after Stop")

	// The wake is not a lease event: owner, claim epoch, status and
	// attempt count are untouched, so the claim is not treated as
	// abandoned.
	after, err := s.service.GetJob(ctx, seed.ID)
	require.NoError(t, err)
	require.Equal(t, before.Status, after.Status)
	require.Equal(t, before.ClaimEpoch, after.ClaimEpoch)
	require.Equal(t, before.AttemptCount, after.AttemptCount)
	require.Equal(t, before.OwnerInstanceID, after.OwnerInstanceID)

	// Resume: a registry restarted on the same store accepts the same
	// (instance, epoch) and serves the next event from the echoed cursor.
	s2, base2, _ := startTestRegistry(t, db)
	defer func() { _ = s2.Stop() }()
	_, _, err = s2.service.PostJobEvent(ctx, seed.ID, "progress", map[string]interface{}{"n": 2}, nil, "test", false)
	require.NoError(t, err)

	r := <-longPoll(fmt.Sprintf("%s/jobs/%s/events?after=1&wait=5&instance_id=replica-a&claim_epoch=%d",
		base2, seed.ID, claimed.ClaimEpoch))
	require.NoError(t, r.err)
	require.Equal(t, http.StatusOK, r.status, "resumed executor read must not be superseded")
	require.Len(t, r.body.Events, 1)
	require.Equal(t, int64(2), r.body.Events[0].Seq)
	require.Equal(t, int64(2), r.body.NextAfter)
}

// TestListJobEventsCore_ShutdownDoesNotPark pins that a long-poll arriving
// after BeginShutdown returns immediately instead of parking.
func TestListJobEventsCore_ShutdownDoesNotPark(t *testing.T) {
	service := setupTestService(t)
	seed := seedJob(t, service, "job-late", "render", nil)
	service.BeginShutdown()
	service.BeginShutdown() // idempotent

	start := time.Now()
	events, err := service.ListJobEvents(context.Background(), seed.ID, 0, nil, 30*time.Second, 100)
	require.NoError(t, err)
	require.Empty(t, events)
	require.Less(t, time.Since(start), 2*time.Second)
}
