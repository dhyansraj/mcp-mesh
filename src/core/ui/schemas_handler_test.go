package ui

// Tests for the Schema Registry Browser handlers (issue #971).
//
// The handlers join SchemaEntry rows with a live in-memory inverse index of
// capabilities. These tests exercise the join end-to-end against an enttest
// SQLite client so any drift in the ent schema (renamed fields, dependency
// JSON shape changes, runtime_origin enum tweaks) surfaces here first.

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"entgo.io/ent/dialect/sql"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	_ "github.com/mattn/go-sqlite3"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/schemaentry"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry"
)

// newSchemasTestEnv builds an in-memory ent client + EntService wired into a
// fresh Server with a minimal gin engine. Status-change hooks are disabled so
// agent seeds don't fire side-effect events that aren't relevant here.
//
// Pattern mirrors newAuditTestEnv in src/core/registry — same DSN tweaks for
// SQLite, same MaxOpenConns=1 single-writer to keep the harness deterministic.
func newSchemasTestEnv(t *testing.T) (*ent.Client, *Server, *gin.Engine, func()) {
	t.Helper()

	dsn := "file:schemas_" + t.Name() + "?mode=memory&cache=shared&_fk=1&_busy_timeout=5000"
	drv, err := sql.Open("sqlite3", dsn)
	require.NoError(t, err, "open test sqlite driver")
	db := drv.DB()
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)

	client := enttest.NewClient(t, enttest.WithOptions(ent.Driver(drv)))
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	entDB := &database.EntDatabase{Client: client}
	svc := registry.NewEntService(entDB, nil, testLogger)
	svc.DisableStatusChangeHooks()

	gin.SetMode(gin.TestMode)
	engine := gin.New()
	srv := &Server{entService: svc}
	api := engine.Group("/api")
	api.GET("/schemas", srv.ListSchemasUsage)
	api.GET("/schemas/:hash/usage", srv.GetSchemaUsage)

	cleanup := func() { client.Close() }
	return client, srv, engine, cleanup
}

// seedSchemaEntry inserts one canonical row. We use Hash as the unique key —
// no fixture randomness, so assertions can refer to hashes by literal value.
func seedSchemaEntry(t *testing.T, client *ent.Client, hash string, origin schemaentry.RuntimeOrigin) {
	t.Helper()
	_, err := client.SchemaEntry.Create().
		SetHash(hash).
		SetCanonical(map[string]interface{}{"type": "object", "_marker": hash}).
		SetRuntimeOrigin(origin).
		SetCreatedAt(time.Now().UTC()).
		Save(context.Background())
	require.NoError(t, err, "seed schema_entry %s", hash)
}

func seedAgent(t *testing.T, client *ent.Client, id, name string) {
	t.Helper()
	seedAgentWithRuntime(t, client, id, name, agent.RuntimePython)
}

// seedAgentWithRuntime is the explicit-runtime variant used by tests that
// exercise the cross-runtime banner story (issue #971 follow-up). Default
// seedAgent stays Python so the existing aggregation test remains stable.
func seedAgentWithRuntime(t *testing.T, client *ent.Client, id, name string, rt agent.Runtime) {
	t.Helper()
	_, err := client.Agent.Create().
		SetID(id).
		SetName(name).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetRuntime(rt).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(context.Background())
	require.NoError(t, err, "seed agent %s", id)
}

// seedAgentWithStatus seeds an agent with an explicit status. Used by the
// healthy-only filter test to drop a stale agent into the DB and confirm it
// stays out of the providers/consumers buckets.
func seedAgentWithStatus(t *testing.T, client *ent.Client, id, name string, status agent.Status) {
	t.Helper()
	_, err := client.Agent.Create().
		SetID(id).
		SetName(name).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetRuntime(agent.RuntimePython).
		SetStatus(status).
		SetUpdatedAt(time.Now().UTC()).
		Save(context.Background())
	require.NoError(t, err, "seed agent %s", id)
}

type capSeed struct {
	agentID      string
	functionName string
	capability   string
	inputHash    *string
	outputHash   *string
	deps         []map[string]interface{}
}

func seedCapability(t *testing.T, client *ent.Client, c capSeed) {
	t.Helper()
	q := client.Capability.Create().
		SetAgentID(c.agentID).
		SetFunctionName(c.functionName).
		SetCapability(c.capability).
		SetVersion("1.0.0")
	if c.inputHash != nil {
		q = q.SetInputSchemaHash(*c.inputHash)
	}
	if c.outputHash != nil {
		q = q.SetOutputSchemaHash(*c.outputHash)
	}
	if c.deps != nil {
		q = q.SetDependencies(c.deps)
	}
	_, err := q.Save(context.Background())
	require.NoError(t, err, "seed capability %s/%s", c.agentID, c.functionName)
}

func strPtr(s string) *string { return &s }

// TestListSchemasUsage_AggregatesCounts seeds 3 schemas + 3 agents + 5
// capabilities + 2 declarative dep entries and asserts the list endpoint's
// provider/consumer counts and sample_function for each hash.
//
//   - hash_w: 2 providers (weather input/output split across two agents), 1 consumer.
//   - hash_g: 1 provider (greeting output only), 1 consumer.
//   - hash_orphan: 0 providers, 0 consumers (sweep mid-state) — must still
//     appear in the list (acceptance criterion #4 of the spec).
func TestListSchemasUsage_AggregatesCounts(t *testing.T) {
	client, _, engine, cleanup := newSchemasTestEnv(t)
	defer cleanup()

	seedSchemaEntry(t, client, "sha256:weather", schemaentry.RuntimeOriginPython)
	seedSchemaEntry(t, client, "sha256:greet", schemaentry.RuntimeOriginTypescript)
	seedSchemaEntry(t, client, "sha256:orphan", schemaentry.RuntimeOriginJava)

	seedAgent(t, client, "weather-svc-py", "weather-svc")
	seedAgent(t, client, "weather-svc-ts", "weather-svc-ts")
	seedAgent(t, client, "greeter", "greeter")

	// python weather: input + output both reference sha256:weather
	seedCapability(t, client, capSeed{
		agentID:      "weather-svc-py",
		functionName: "get_weather",
		capability:   "weather_report",
		inputHash:    strPtr("sha256:weather"),
		outputHash:   strPtr("sha256:weather"),
	})
	// typescript weather: output only — same hash, different agent
	seedCapability(t, client, capSeed{
		agentID:      "weather-svc-ts",
		functionName: "fetchWeather",
		capability:   "weather_report",
		outputHash:   strPtr("sha256:weather"),
	})
	// greeter: output references sha256:greet
	seedCapability(t, client, capSeed{
		agentID:      "greeter",
		functionName: "say_hi",
		capability:   "personalized_greeting",
		outputHash:   strPtr("sha256:greet"),
	})
	// greeter has a second capability that consumes sha256:weather AND sha256:greet
	seedCapability(t, client, capSeed{
		agentID:      "greeter",
		functionName: "morning_routine",
		capability:   "routine",
		deps: []map[string]interface{}{
			{"capability": "weather_report", "expected_schema_hash": "sha256:weather"},
			{"capability": "personalized_greeting", "expected_schema_hash": "sha256:greet"},
		},
	})
	// trailing capability with NO schema fields — must not appear in any bucket
	seedCapability(t, client, capSeed{
		agentID:      "greeter",
		functionName: "no_schema",
		capability:   "noop",
	})

	req := httptest.NewRequest(http.MethodGet, "/api/schemas", nil)
	rec := httptest.NewRecorder()
	engine.ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code, "body=%s", rec.Body.String())

	var resp struct {
		Schemas []schemaListItem `json:"schemas"`
		Count   int              `json:"count"`
	}
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))

	assert.Equal(t, 3, resp.Count, "all schema_entries listed")
	byHash := map[string]schemaListItem{}
	for _, s := range resp.Schemas {
		byHash[s.Hash] = s
	}

	w := byHash["sha256:weather"]
	assert.Equal(t, 3, w.ProviderCount, "weather: python input + python output + ts output")
	assert.Equal(t, 1, w.ConsumerCount, "weather: morning_routine depends on weather_report")
	require.NotNil(t, w.SampleFunction)
	// Deterministic sort: provider function_names for weather are
	// {get_weather, get_weather, fetchWeather} — alphabetical pick is
	// "fetchWeather". Asserting the exact name guarantees the sort fires.
	assert.Equal(t, "fetchWeather", *w.SampleFunction,
		"sample_function is the alphabetically-first provider function_name")
	assert.Equal(t, "python", w.RuntimeOrigin)
	assert.Equal(t, []string{"weather-svc", "weather-svc-ts"}, w.ProviderAgentNames,
		"provider_agent_names is deduped + sorted")

	g := byHash["sha256:greet"]
	assert.Equal(t, 1, g.ProviderCount, "greet: say_hi output only")
	assert.Equal(t, 1, g.ConsumerCount, "greet: morning_routine consumes greet")
	require.NotNil(t, g.SampleFunction)
	assert.Equal(t, "say_hi", *g.SampleFunction)
	assert.Equal(t, "typescript", g.RuntimeOrigin)
	assert.Equal(t, []string{"greeter"}, g.ProviderAgentNames)

	o := byHash["sha256:orphan"]
	assert.Equal(t, 0, o.ProviderCount, "orphan: zero providers")
	assert.Equal(t, 0, o.ConsumerCount, "orphan: zero consumers")
	assert.Nil(t, o.SampleFunction, "sample_function is null with no providers")
	assert.Equal(t, []string{}, o.ProviderAgentNames,
		"provider_agent_names is an empty slice (not nil) when there are no providers")
}

// TestListSchemasUsage_SampleFunctionStable confirms sample_function is
// deterministic across repeated invocations even when the underlying agent /
// capability seeds produce providers in a different Go-map iteration order
// each scan. Regression guard for the non-determinism CodeRabbit flagged on
// PR #979 — without the sort in ListSchemasUsage, `provs[0]` could flicker
// between equivalent providers on every refresh.
func TestListSchemasUsage_SampleFunctionStable(t *testing.T) {
	client, _, engine, cleanup := newSchemasTestEnv(t)
	defer cleanup()

	seedSchemaEntry(t, client, "sha256:shared", schemaentry.RuntimeOriginPython)

	// Three agents all provide the same schema hash with distinct function
	// names. The handler's underlying buildInverseIndex bucket order depends
	// on Agent.Query() iteration, which is unordered — only the in-handler
	// sort guarantees a stable pick.
	seedAgent(t, client, "agent-a", "alpha")
	seedAgent(t, client, "agent-b", "bravo")
	seedAgent(t, client, "agent-c", "charlie")
	seedCapability(t, client, capSeed{
		agentID:      "agent-a",
		functionName: "zebra_fn",
		capability:   "shared_cap",
		outputHash:   strPtr("sha256:shared"),
	})
	seedCapability(t, client, capSeed{
		agentID:      "agent-b",
		functionName: "apple_fn",
		capability:   "shared_cap",
		outputHash:   strPtr("sha256:shared"),
	})
	seedCapability(t, client, capSeed{
		agentID:      "agent-c",
		functionName: "mango_fn",
		capability:   "shared_cap",
		outputHash:   strPtr("sha256:shared"),
	})

	hit := func() schemaListItem {
		req := httptest.NewRequest(http.MethodGet, "/api/schemas", nil)
		rec := httptest.NewRecorder()
		engine.ServeHTTP(rec, req)
		require.Equal(t, http.StatusOK, rec.Code, "body=%s", rec.Body.String())
		var resp struct {
			Schemas []schemaListItem `json:"schemas"`
		}
		require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))
		require.Len(t, resp.Schemas, 1)
		return resp.Schemas[0]
	}

	first := hit()
	require.NotNil(t, first.SampleFunction)
	assert.Equal(t, "apple_fn", *first.SampleFunction,
		"alphabetically first provider function_name wins")
	assert.Equal(t, []string{"alpha", "bravo", "charlie"}, first.ProviderAgentNames)

	// Repeat invocations must return the same sample_function value — even
	// though the underlying scan ordering is non-deterministic, the sort in
	// the handler nails it down.
	for i := 0; i < 5; i++ {
		next := hit()
		require.NotNil(t, next.SampleFunction)
		assert.Equal(t, *first.SampleFunction, *next.SampleFunction,
			"sample_function stable across invocation %d", i)
		assert.Equal(t, first.ProviderAgentNames, next.ProviderAgentNames,
			"provider_agent_names stable across invocation %d", i)
	}
}

// TestGetSchemaUsage_DetailSplitsRoles asserts /usage returns providers split
// into input/output roles and consumers tagged with depends_on_capability.
// Also asserts each provider/consumer row carries the owning agent's runtime
// (issue #971 cross-runtime banner follow-up): a Java provider + Python
// consumer of the same canonical hash is exactly the polyglot dedup story
// the SPA renders.
func TestGetSchemaUsage_DetailSplitsRoles(t *testing.T) {
	client, _, engine, cleanup := newSchemasTestEnv(t)
	defer cleanup()

	seedSchemaEntry(t, client, "sha256:weather", schemaentry.RuntimeOriginPython)
	seedAgentWithRuntime(t, client, "weather-svc-py", "weather-svc", agent.RuntimeJava)
	seedAgentWithRuntime(t, client, "consumer-bot", "consumer-bot", agent.RuntimePython)

	// One agent provides on both input and output sides:
	seedCapability(t, client, capSeed{
		agentID:      "weather-svc-py",
		functionName: "get_weather",
		capability:   "weather_report",
		inputHash:    strPtr("sha256:weather"),
		outputHash:   strPtr("sha256:weather"),
	})
	// Another agent declares a dependency expecting this hash:
	seedCapability(t, client, capSeed{
		agentID:      "consumer-bot",
		functionName: "plan_picnic",
		capability:   "picnic_plan",
		deps: []map[string]interface{}{
			{"capability": "weather_report", "expected_schema_hash": "sha256:weather"},
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/schemas/sha256:weather/usage", nil)
	rec := httptest.NewRecorder()
	engine.ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code, "body=%s", rec.Body.String())

	var resp schemaUsageResponse
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))

	assert.Equal(t, "sha256:weather", resp.Schema.Hash)
	assert.Equal(t, "python", resp.Schema.RuntimeOrigin)
	assert.NotNil(t, resp.Schema.Canonical, "canonical body included")

	require.Len(t, resp.Providers, 2, "input + output sides both surface")
	roles := map[string]bool{}
	for _, p := range resp.Providers {
		roles[p.Role] = true
		assert.Equal(t, "weather-svc-py", p.AgentID)
		assert.Equal(t, "get_weather", p.FunctionName)
		assert.Equal(t, "weather_report", p.Capability)
		assert.Equal(t, "java", p.Runtime, "provider runtime denormalized from owning agent")
	}
	assert.True(t, roles["input"], "input role present")
	assert.True(t, roles["output"], "output role present")

	require.Len(t, resp.Consumers, 1, "exactly one declarative consumer")
	c := resp.Consumers[0]
	assert.Equal(t, "consumer-bot", c.AgentID)
	assert.Equal(t, "plan_picnic", c.FunctionName)
	assert.Equal(t, "picnic_plan", c.Capability)
	assert.Equal(t, "dependency", c.Via)
	assert.Equal(t, "weather_report", c.DependsOnCapability)
	assert.Equal(t, "python", c.Runtime, "consumer runtime denormalized from owning agent")
}

// TestGetSchemaUsage_404 — unknown hash returns 404, never a partial body.
func TestGetSchemaUsage_404(t *testing.T) {
	_, _, engine, cleanup := newSchemasTestEnv(t)
	defer cleanup()

	req := httptest.NewRequest(http.MethodGet, "/api/schemas/sha256:nonexistent/usage", nil)
	rec := httptest.NewRecorder()
	engine.ServeHTTP(rec, req)
	require.Equal(t, http.StatusNotFound, rec.Code)
}

// TestSchemas_FiltersUnhealthyAgents — agents whose status is not "healthy"
// must not surface in the providers / consumers buckets. The schema browser
// follows the "healthy only" convention used elsewhere in the dashboard:
// stale or unknown-status agents are effectively offline and shouldn't be
// shown as live producers/consumers of a canonical schema. Cascades into
// provider_count / consumer_count on the list view as well.
func TestSchemas_FiltersUnhealthyAgents(t *testing.T) {
	client, _, engine, cleanup := newSchemasTestEnv(t)
	defer cleanup()

	seedSchemaEntry(t, client, "sha256:weather", schemaentry.RuntimeOriginPython)

	// Two agents provide the same schema hash; one is healthy, the other has
	// gone unhealthy (e.g. failed heartbeat). Only the healthy one should be
	// counted / surfaced.
	seedAgentWithStatus(t, client, "weather-healthy", "weather-healthy", agent.StatusHealthy)
	seedAgentWithStatus(t, client, "weather-stale", "weather-stale", agent.StatusUnhealthy)

	seedCapability(t, client, capSeed{
		agentID:      "weather-healthy",
		functionName: "get_weather",
		capability:   "weather_report",
		outputHash:   strPtr("sha256:weather"),
	})
	seedCapability(t, client, capSeed{
		agentID:      "weather-stale",
		functionName: "get_weather_stale",
		capability:   "weather_report",
		outputHash:   strPtr("sha256:weather"),
	})

	// List endpoint: provider_count reflects only healthy providers.
	listReq := httptest.NewRequest(http.MethodGet, "/api/schemas", nil)
	listRec := httptest.NewRecorder()
	engine.ServeHTTP(listRec, listReq)
	require.Equal(t, http.StatusOK, listRec.Code, "body=%s", listRec.Body.String())

	var listResp struct {
		Schemas []schemaListItem `json:"schemas"`
		Count   int              `json:"count"`
	}
	require.NoError(t, json.Unmarshal(listRec.Body.Bytes(), &listResp))
	require.Len(t, listResp.Schemas, 1)
	assert.Equal(t, 1, listResp.Schemas[0].ProviderCount,
		"provider_count excludes unhealthy agents")

	// Detail endpoint: providers slice contains only the healthy agent.
	detailReq := httptest.NewRequest(http.MethodGet, "/api/schemas/sha256:weather/usage", nil)
	detailRec := httptest.NewRecorder()
	engine.ServeHTTP(detailRec, detailReq)
	require.Equal(t, http.StatusOK, detailRec.Code, "body=%s", detailRec.Body.String())

	var detailResp schemaUsageResponse
	require.NoError(t, json.Unmarshal(detailRec.Body.Bytes(), &detailResp))
	require.Len(t, detailResp.Providers, 1, "providers slice excludes unhealthy agents")
	assert.Equal(t, "weather-healthy", detailResp.Providers[0].AgentID,
		"only the healthy provider is returned")
	assert.Len(t, detailResp.Consumers, 0, "no declared consumers in this fixture")
}

// TestGetSchemaUsage_EmptyArraysNotNull — a freshly-seeded schema with zero
// referencing agents must return providers=[] and consumers=[] (not null) so
// the SPA can render the empty-state row without a nil guard.
func TestGetSchemaUsage_EmptyArraysNotNull(t *testing.T) {
	client, _, engine, cleanup := newSchemasTestEnv(t)
	defer cleanup()

	seedSchemaEntry(t, client, "sha256:lonely", schemaentry.RuntimeOriginUnknown)

	req := httptest.NewRequest(http.MethodGet, "/api/schemas/sha256:lonely/usage", nil)
	rec := httptest.NewRecorder()
	engine.ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code, "body=%s", rec.Body.String())

	// Marshal-then-string compare so we can prove the JSON literal "[]"
	// shows up rather than a null. Unmarshal alone would lose that signal.
	body := rec.Body.String()
	assert.Contains(t, body, `"providers":[]`, "providers serialized as empty array, not null")
	assert.Contains(t, body, `"consumers":[]`, "consumers serialized as empty array, not null")
}
