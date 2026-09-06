package registry

// Coverage for #1580 — the HEAD /heartbeat/{agent_id} fast path.
//
// Two separate defects on the same path:
//
//  1. `if err != nil || agentEntity == nil { 410 }` reported ANY GetAgent
//     failure as "unknown agent". Clients map 410 to AGENT_UNKNOWN and
//     immediately POST a full re-registration, so a transient database fault
//     made the whole fleet re-register at once — the worst possible load while
//     the database is already struggling. Only a genuine not-found may answer
//     410; everything else is 503, which every client already backs off from.
//
//  2. The handler loaded the agent row three times per HEAD (GetAgent, then
//     again inside UpdateAgentHeartbeatTimestamp, then again inside the
//     pending-jobs count — four SELECTs in total, since ent re-selects after
//     UpdateOneID). It now loads it once and passes what it needs down.
//
// Plus the POST-side half of the same issue: a full heartbeat from an
// already-healthy agent used to carry `status` in its mutation, waking the
// status-change hook, which re-read the agent row only to discover nothing
// changed.

import (
	"context"
	"database/sql"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	entgo "entgo.io/ent"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry/generated"
)

// stmtRecorder collects the SQL ent executes, so a test can assert how many
// times a given table is touched on one request. Populated through ent's own
// debug logger, which sees every statement including those issued inside
// transactions.
type stmtRecorder struct {
	mu    sync.Mutex
	on    bool
	stmts []string
}

func (r *stmtRecorder) log(args ...any) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if !r.on {
		return
	}
	r.stmts = append(r.stmts, fmt.Sprint(args...))
}

func (r *stmtRecorder) start() {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.on = true
	r.stmts = nil
}

func (r *stmtRecorder) stop() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.on = false
	out := make([]string, len(r.stmts))
	copy(out, r.stmts)
	return out
}

// countMatching returns the statements containing every one of `parts`.
func countMatching(stmts []string, parts ...string) []string {
	var hits []string
	for _, s := range stmts {
		ok := true
		for _, p := range parts {
			if !strings.Contains(s, p) {
				ok = false
				break
			}
		}
		if ok {
			hits = append(hits, s)
		}
	}
	return hits
}

// newInstrumentedHeartbeatEnv mirrors newAuditTestEnv but also hands back the
// raw *sql.DB (so a test can simulate a database fault) and a statement
// recorder.
func newInstrumentedHeartbeatEnv(t *testing.T) (*httptest.Server, *ent.Client, *sql.DB, *stmtRecorder, func()) {
	t.Helper()

	dsn := "file:hbpath_" + t.Name() + "?mode=memory&cache=shared&_fk=1&_busy_timeout=5000"
	drv, err := entsql.Open("sqlite3", dsn)
	require.NoError(t, err, "open test sqlite driver")
	db := drv.DB()
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)

	rec := &stmtRecorder{}
	client := enttest.NewClient(t, enttest.WithOptions(
		ent.Driver(drv),
		ent.Log(rec.log),
		ent.Debug(),
	))
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	service := NewEntService(&database.EntDatabase{Client: client}, nil, testLogger)
	service.DisableStatusChangeHooks()

	gin.SetMode(gin.TestMode)
	router := gin.New()
	generated.RegisterHandlers(router, NewEntBusinessLogicHandlers(service))
	srv := httptest.NewServer(router)

	return srv, client, db, rec, func() {
		srv.Close()
		client.Close()
	}
}

func headHeartbeat(t *testing.T, srv *httptest.Server, agentID string) *http.Response {
	t.Helper()
	req, err := http.NewRequest("HEAD", srv.URL+"/heartbeat/"+agentID, nil)
	require.NoError(t, err)
	resp, err := (&http.Client{}).Do(req)
	require.NoError(t, err)
	resp.Body.Close()
	return resp
}

// TestFastHeartbeat_TransientDBErrorReturns503 is the primary #1580
// regression: the agent EXISTS as far as the registry is concerned, but the
// lookup fails. That must not be reported as "unknown agent".
func TestFastHeartbeat_TransientDBErrorReturns503(t *testing.T) {
	srv, client, db, _, cleanup := newInstrumentedHeartbeatEnv(t)
	defer cleanup()

	ctx := context.Background()
	agentID := "hb-agent-1"
	_, err := client.Agent.Create().
		SetID(agentID).
		SetName(agentID).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err, "seed healthy agent")

	// Sanity: the happy path answers 200 before we break anything.
	require.Equal(t, http.StatusOK, headHeartbeat(t, srv, agentID).StatusCode)

	// Simulate a database-side fault on the agent lookup. Any non-not-found
	// error stands in for the production cases (connection reset, pool
	// exhaustion, statement timeout) that #1580 was answering 410 for.
	_, err = db.ExecContext(ctx, "DROP TABLE agents")
	require.NoError(t, err, "drop agents table to simulate a DB fault")

	resp := headHeartbeat(t, srv, agentID)
	assert.Equal(t, http.StatusServiceUnavailable, resp.StatusCode,
		"a transient DB failure on HEAD heartbeat must answer 503 (back off), "+
			"never 410 (which stampedes the fleet into re-registering) — #1580")
}

// TestFastHeartbeat_UnknownAgentStillReturns410 is the control: the 410
// contract for a genuinely absent row is unchanged.
func TestFastHeartbeat_UnknownAgentStillReturns410(t *testing.T) {
	srv, _, _, _, cleanup := newInstrumentedHeartbeatEnv(t)
	defer cleanup()

	resp := headHeartbeat(t, srv, "never-registered")
	assert.Equal(t, http.StatusGone, resp.StatusCode,
		"an agent with no row must still get 410 Gone so it re-registers")
}

// TestFastHeartbeat_LoadsAgentRowOnce pins the query-count half of #1580: the
// HEAD path used to SELECT the agent row three times per beat (once per
// helper). It now reads it once and threads the loaded row through.
func TestFastHeartbeat_LoadsAgentRowOnce(t *testing.T) {
	srv, client, _, rec, cleanup := newInstrumentedHeartbeatEnv(t)
	defer cleanup()

	ctx := context.Background()
	agentID := "hb-agent-1"
	_, err := client.Agent.Create().
		SetID(agentID).
		SetName("hb-agent").
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err, "seed healthy agent")
	_, err = client.Capability.Create().
		SetCapability("render_report").
		SetFunctionName("do_thing").
		SetVersion("1.0.0").
		SetTags([]string{}).
		SetAgentID(agentID).
		Save(ctx)
	require.NoError(t, err, "seed capability")

	rec.start()
	require.Equal(t, http.StatusOK, headHeartbeat(t, srv, agentID).StatusCode)
	stmts := rec.stop()

	// "load one agent row by id", in both the qualified (client) and
	// unqualified (in-transaction) forms ent emits. The capability query's
	// EXISTS sub-select on `agents` deliberately matches neither.
	selects := countMatching(stmts, "FROM `agents` WHERE `agents`.`agent_id` = ?")
	selects = append(selects, countMatching(stmts, "FROM `agents` WHERE `agent_id` = ?")...)
	assert.Len(t, selects, 1,
		"HEAD heartbeat must read the agent row exactly once (#1580); got:\n%s",
		strings.Join(selects, "\n"))

	// Whole-path budget: the fast path is fleet-wide every ~5s, so keep a
	// ceiling on it. One agent SELECT, one timestamp UPDATE, one topology
	// query, one capability query, one pending-jobs query.
	assert.LessOrEqualf(t, len(stmts), 5,
		"HEAD heartbeat issued %d statements, expected at most 5 (#1580):\n%s",
		len(stmts), strings.Join(stmts, "\n"))
}

// TestFullHeartbeat_UnchangedStatusSkipsStatusMutation covers the POST half of
// #1580: an already-healthy agent's full heartbeat must not carry `status` in
// its mutation, because that wakes the status-change hook into an extra read
// that can only ever conclude "nothing changed".
func TestFullHeartbeat_UnchangedStatusSkipsStatusMutation(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	// Record whether any agent update mutation carried the status field.
	var (
		mu             sync.Mutex
		statusMutation []agent.Status
	)
	client.Agent.Use(func(next entgo.Mutator) entgo.Mutator {
		return entgo.MutateFunc(func(ctx context.Context, m entgo.Mutation) (entgo.Value, error) {
			am, ok := m.(*ent.AgentMutation)
			if ok && (am.Op() == ent.OpUpdate || am.Op() == ent.OpUpdateOne) {
				if st, exists := am.Status(); exists {
					mu.Lock()
					statusMutation = append(statusMutation, st)
					mu.Unlock()
				}
			}
			return next.Mutate(ctx, m)
		})
	})

	ctx := context.Background()
	agentID := "steady-agent-1"
	_, err := client.Agent.Create().
		SetID(agentID).
		SetName(agentID).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err, "seed healthy agent")

	hb := &HeartbeatRequest{
		AgentID: agentID,
		Status:  "healthy",
		Metadata: map[string]interface{}{
			"agent_id":  agentID,
			"name":      agentID,
			"version":   "1.0.0",
			"namespace": "default",
			"endpoint":  "http://127.0.0.1:9999",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "do_thing",
					"capability":    "thing",
					"version":       "1.0.0",
				},
			},
		},
	}
	_, err = service.UpdateHeartbeat(hb)
	require.NoError(t, err, "steady-state full heartbeat must succeed")

	mu.Lock()
	got := append([]agent.Status(nil), statusMutation...)
	mu.Unlock()
	assert.Empty(t, got,
		"a full heartbeat from an already-healthy agent must not mutate status (#1580); got %v", got)

	// The row is untouched status-wise and still healthy.
	row, err := client.Agent.Get(ctx, agentID)
	require.NoError(t, err)
	assert.Equal(t, agent.StatusHealthy, row.Status)
}

// TestFullHeartbeat_UnhealthyStillTransitions guards the recovery path the
// optimisation above must not break: when the stored status actually differs,
// the mutation still carries it (and the hook still gets its chance to emit
// the recovery event).
func TestFullHeartbeat_UnhealthyStillTransitions(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	var (
		mu             sync.Mutex
		statusMutation []agent.Status
	)
	client.Agent.Use(func(next entgo.Mutator) entgo.Mutator {
		return entgo.MutateFunc(func(ctx context.Context, m entgo.Mutation) (entgo.Value, error) {
			am, ok := m.(*ent.AgentMutation)
			if ok && (am.Op() == ent.OpUpdate || am.Op() == ent.OpUpdateOne) {
				if st, exists := am.Status(); exists {
					mu.Lock()
					statusMutation = append(statusMutation, st)
					mu.Unlock()
				}
			}
			return next.Mutate(ctx, m)
		})
	})

	ctx := context.Background()
	agentID := "recovering-agent-1"
	_, err := client.Agent.Create().
		SetID(agentID).
		SetName(agentID).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusUnhealthy).
		SetUpdatedAt(time.Now().UTC().Add(-time.Hour)).
		Save(ctx)
	require.NoError(t, err, "seed unhealthy agent")

	hb := &HeartbeatRequest{
		AgentID: agentID,
		Status:  "healthy",
		Metadata: map[string]interface{}{
			"agent_id":  agentID,
			"name":      agentID,
			"version":   "1.0.0",
			"namespace": "default",
			"endpoint":  "http://127.0.0.1:9999",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "do_thing",
					"capability":    "thing",
					"version":       "1.0.0",
				},
			},
		},
	}
	_, err = service.UpdateHeartbeat(hb)
	require.NoError(t, err, "recovery heartbeat must succeed")

	mu.Lock()
	got := append([]agent.Status(nil), statusMutation...)
	mu.Unlock()
	assert.Contains(t, got, agent.StatusHealthy,
		"unhealthy → healthy recovery must still be written through the status field")

	row, err := client.Agent.Get(ctx, agentID)
	require.NoError(t, err)
	assert.Equal(t, agent.StatusHealthy, row.Status, "agent must recover to healthy")
}

// TestFullHeartbeat_StatusRestoredWhenMonitorFlipsUnderUs guards the window
// the status skip could have opened. `existingAgent` is read BEFORE the
// heartbeat's transaction; if the health monitor marks the row unhealthy in
// between, a skip decided on that stale copy would leave a demonstrably-live
// agent unwired (consumers stop resolving unhealthy providers) until the next
// round trip. The decision therefore has to come from a read taken inside the
// transaction.
//
// The interceptor below flips the row to unhealthy immediately AFTER the
// pre-transaction read returns — i.e. exactly in the window — and the
// heartbeat must still restore it.
func TestFullHeartbeat_StatusRestoredWhenMonitorFlipsUnderUs(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()
	ctx := context.Background()

	agentID := "raced-agent-1"
	_, err := client.Agent.Create().
		SetID(agentID).
		SetName(agentID).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err, "seed healthy agent")

	// Fire once, on the first agent query of the heartbeat — the
	// pre-transaction read. Flipping AFTER next.Query returns models the
	// monitor's UPDATE committing the instant our read finished.
	var (
		mu      sync.Mutex
		flipped bool
	)
	client.Agent.Intercept(ent.InterceptFunc(func(next ent.Querier) ent.Querier {
		return ent.QuerierFunc(func(ctx context.Context, q ent.Query) (ent.Value, error) {
			v, qerr := next.Query(ctx, q)
			mu.Lock()
			run := qerr == nil && !flipped
			if run {
				flipped = true
			}
			mu.Unlock()
			if run {
				if uerr := client.Agent.UpdateOneID(agentID).
					SetStatus(agent.StatusUnhealthy).
					Exec(ctx); uerr != nil {
					return nil, uerr
				}
			}
			return v, qerr
		})
	}))

	hb := &HeartbeatRequest{
		AgentID: agentID,
		Status:  "healthy",
		Metadata: map[string]interface{}{
			"agent_id":  agentID,
			"name":      agentID,
			"version":   "1.0.0",
			"namespace": "default",
			"endpoint":  "http://127.0.0.1:9999",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "do_thing",
					"capability":    "thing",
					"version":       "1.0.0",
				},
			},
		},
	}
	_, err = service.UpdateHeartbeat(hb)
	require.NoError(t, err, "heartbeat must succeed")

	mu.Lock()
	ran := flipped
	mu.Unlock()
	require.True(t, ran, "test bug: the injected status flip never ran")

	row, err := client.Agent.Get(ctx, agentID)
	require.NoError(t, err)
	assert.Equal(t, agent.StatusHealthy, row.Status,
		"a full heartbeat must restore a row the monitor flipped to unhealthy in the "+
			"pre-transaction window — the status decision has to be made on a read "+
			"taken inside the transaction (#1580)")
}
