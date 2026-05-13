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
	assert.NotEmpty(t, *w.SampleFunction, "sample_function set when providers exist")
	assert.Equal(t, "python", w.RuntimeOrigin)

	g := byHash["sha256:greet"]
	assert.Equal(t, 1, g.ProviderCount, "greet: say_hi output only")
	assert.Equal(t, 1, g.ConsumerCount, "greet: morning_routine consumes greet")
	require.NotNil(t, g.SampleFunction)
	assert.Equal(t, "say_hi", *g.SampleFunction)
	assert.Equal(t, "typescript", g.RuntimeOrigin)

	o := byHash["sha256:orphan"]
	assert.Equal(t, 0, o.ProviderCount, "orphan: zero providers")
	assert.Equal(t, 0, o.ConsumerCount, "orphan: zero consumers")
	assert.Nil(t, o.SampleFunction, "sample_function is null with no providers")
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
