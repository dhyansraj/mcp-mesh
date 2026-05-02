package registry

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/schemaentry"

	_ "github.com/mattn/go-sqlite3"
)

// seedProducerWithSchema mirrors seedProducer but also stamps an
// output_schema_hash on the capability row so the resolver's schema stage has
// something to compare against.
func seedProducerWithSchema(t *testing.T, client *ent.Client, id string, capabilityName, version string, tags []string, outputHash string) {
	t.Helper()
	ctx := context.Background()
	_, err := client.Agent.Create().
		SetID(id).
		SetName(id).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(time.Now().UTC()).
		Save(ctx)
	require.NoError(t, err, "create agent")

	create := client.Capability.Create().
		SetCapability(capabilityName).
		SetFunctionName("do_thing").
		SetVersion(version).
		SetTags(tags).
		SetAgentID(id)
	if outputHash != "" {
		create = create.SetOutputSchemaHash(outputHash)
	}
	_, err = create.Save(ctx)
	require.NoError(t, err, "create capability")
}

// seedSchemaEntry inserts a row in the schema_entries table so the resolver can
// load it for the subset diff.
func seedSchemaEntry(t *testing.T, client *ent.Client, hash string, canonical map[string]interface{}) {
	t.Helper()
	ctx := context.Background()
	_, err := client.SchemaEntry.Create().
		SetHash(hash).
		SetCanonical(canonical).
		SetRuntimeOrigin(schemaentry.RuntimeOriginPython).
		Save(ctx)
	require.NoError(t, err, "create schema entry")
}

// TestAudit_SchemaStage_HashEqualKeepsBoth: when consumer's expected hash
// matches a producer's output hash exactly, that producer is kept via the
// short-circuit (no canonical-diff load required). A second producer with a
// different hash but a compatible canonical schema also passes via the diff.
func TestAudit_SchemaStage_HashEqualKeepsBoth(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")

	// Consumer expects a {name: string, dept: string} schema.
	consumerSchema := objectSchema(map[string]interface{}{
		"name": primSchema("string"),
		"dept": primSchema("string"),
	}, "name", "dept")
	consumerHash := "sha256:consumer-abc"

	// Producer-A uses the identical schema (same hash) → hash short-circuit.
	seedProducerWithSchema(t, client, "prod-a", "employee", "1.0.0", []string{"api"}, consumerHash)
	seedSchemaEntry(t, client, consumerHash, consumerSchema)

	// Producer-B has an extra field — different hash, but subset-compatible.
	bHash := "sha256:b-extended"
	bSchema := objectSchema(map[string]interface{}{
		"name":   primSchema("string"),
		"dept":   primSchema("string"),
		"salary": primSchema("number"),
	}, "name", "dept", "salary")
	seedProducerWithSchema(t, client, "prod-b", "employee", "1.0.0", []string{"api"}, bHash)
	seedSchemaEntry(t, client, bHash, bSchema)

	meta := metadataForDep(map[string]interface{}{
		"capability":                "employee",
		"tags":                      []interface{}{"api"},
		"match_mode":                "subset",
		"expected_schema_hash":      consumerHash,
		"expected_schema_canonical": consumerSchema,
	})

	resolutions := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, resolutions, 1)
	require.NotNil(t, resolutions[0].Resolution, "expected a resolution")
	require.NotNil(t, resolutions[0].Trace)

	tr := resolutions[0].Trace
	assert.Equal(t, "subset", tr.Spec.SchemaMode)

	require.Len(t, tr.Stages, 6)
	schemaStage := tr.Stages[4]
	assert.Equal(t, StageSchema, schemaStage.Stage)
	assert.Empty(t, schemaStage.Evicted, "both producers should pass schema stage")
	assert.Len(t, schemaStage.Kept, 2)
}

// TestAudit_SchemaStage_SubsetEvictsIncompatible: producer-B is missing a
// required field — must be evicted with ReasonSchemaIncompatible and details
// listing the missing field path.
func TestAudit_SchemaStage_SubsetEvictsIncompatible(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")

	consumerSchema := objectSchema(map[string]interface{}{
		"name": primSchema("string"),
		"dept": primSchema("string"),
	}, "name", "dept")
	consumerHash := "sha256:consumer-abc"

	// Producer-A: hash matches → kept via short-circuit.
	seedProducerWithSchema(t, client, "prod-a", "employee", "1.0.0", []string{"api"}, consumerHash)
	seedSchemaEntry(t, client, consumerHash, consumerSchema)

	// Producer-B: only emits {name} — missing required dept.
	bHash := "sha256:b-narrow"
	bSchema := objectSchema(map[string]interface{}{
		"name": primSchema("string"),
	}, "name")
	seedProducerWithSchema(t, client, "prod-b", "employee", "1.0.0", []string{"api"}, bHash)
	seedSchemaEntry(t, client, bHash, bSchema)

	meta := metadataForDep(map[string]interface{}{
		"capability":                "employee",
		"tags":                      []interface{}{"api"},
		"match_mode":                "subset",
		"expected_schema_hash":      consumerHash,
		"expected_schema_canonical": consumerSchema,
	})

	resolutions := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, resolutions, 1)
	require.NotNil(t, resolutions[0].Resolution, "prod-a should resolve")
	assert.Equal(t, "prod-a", resolutions[0].Resolution.AgentID)

	tr := resolutions[0].Trace
	require.NotNil(t, tr)
	assert.Equal(t, "subset", tr.Spec.SchemaMode)

	schemaStage := tr.Stages[4]
	require.Equal(t, StageSchema, schemaStage.Stage)
	require.Len(t, schemaStage.Kept, 1)
	assert.Equal(t, "prod-a:do_thing", schemaStage.Kept[0])

	require.Len(t, schemaStage.Evicted, 1)
	ev := schemaStage.Evicted[0]
	assert.Equal(t, "prod-b:do_thing", ev.ID)
	assert.Equal(t, ReasonSchemaIncompatible, ev.Reason)
	assert.Equal(t, "subset", ev.Details["mode"])
	assert.Equal(t, consumerHash, ev.Details["consumer_hash"])
	assert.Equal(t, bHash, ev.Details["producer_hash"])
	reasons, ok := ev.Details["reasons"].([]map[string]interface{})
	require.True(t, ok, "reasons must carry typed payload")
	require.NotEmpty(t, reasons)
	assert.Equal(t, "missing_field", reasons[0]["kind"])
	assert.Equal(t, "dept", reasons[0]["field"])
}

// TestAudit_SchemaStage_StrictHashMismatchEvicts: in strict mode, any hash
// difference is grounds for eviction without consulting the canonical schema.
func TestAudit_SchemaStage_StrictHashMismatchEvicts(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")

	consumerHash := "sha256:consumer-abc"
	otherHash := "sha256:other-def"

	seedProducerWithSchema(t, client, "prod-a", "employee", "1.0.0", []string{"api"}, consumerHash)
	seedProducerWithSchema(t, client, "prod-b", "employee", "1.0.0", []string{"api"}, otherHash)

	meta := metadataForDep(map[string]interface{}{
		"capability":           "employee",
		"tags":                 []interface{}{"api"},
		"match_mode":           "strict",
		"expected_schema_hash": consumerHash,
	})

	resolutions := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, resolutions, 1)
	require.NotNil(t, resolutions[0].Resolution, "prod-a must win")
	assert.Equal(t, "prod-a", resolutions[0].Resolution.AgentID)

	tr := resolutions[0].Trace
	require.NotNil(t, tr)
	assert.Equal(t, "strict", tr.Spec.SchemaMode)

	schemaStage := tr.Stages[4]
	require.Len(t, schemaStage.Evicted, 1)
	ev := schemaStage.Evicted[0]
	assert.Equal(t, "prod-b:do_thing", ev.ID)
	assert.Equal(t, ReasonSchemaIncompatible, ev.Reason)
	assert.Equal(t, "strict", ev.Details["mode"])
}

// TestAudit_SchemaStage_LegacyProducerKept: a candidate without an
// output_schema_hash must NOT be evicted — we'd rather keep a working producer
// than blackhole the consumer during the schema-rollout window.
func TestAudit_SchemaStage_LegacyProducerKept(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")

	// Force two candidates so the trace IsInteresting and we can inspect kept.
	consumerHash := "sha256:consumer-abc"
	consumerSchema := objectSchema(map[string]interface{}{
		"name": primSchema("string"),
	}, "name")

	// Producer-A emits matching schema.
	seedProducerWithSchema(t, client, "prod-a", "employee", "1.0.0", []string{"api"}, consumerHash)
	seedSchemaEntry(t, client, consumerHash, consumerSchema)

	// Producer-B is legacy — no output_schema_hash on the capability.
	seedProducerWithSchema(t, client, "prod-legacy", "employee", "1.0.0", []string{"api"}, "")

	meta := metadataForDep(map[string]interface{}{
		"capability":                "employee",
		"tags":                      []interface{}{"api"},
		"match_mode":                "subset",
		"expected_schema_hash":      consumerHash,
		"expected_schema_canonical": consumerSchema,
	})

	resolutions := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, resolutions, 1)
	require.NotNil(t, resolutions[0].Resolution)

	tr := resolutions[0].Trace
	schemaStage := tr.Stages[4]
	assert.Equal(t, StageSchema, schemaStage.Stage)
	assert.Empty(t, schemaStage.Evicted, "legacy producer must not be evicted")
	assert.Len(t, schemaStage.Kept, 2)
}

// TestAudit_SchemaStage_NoMatchModeIsPassThrough: when the consumer didn't opt
// in, the schema stage is a pure pass-through and the trace records SchemaMode
// as "none" (preserves the v1 default behavior all existing audit tests rely
// on).
func TestAudit_SchemaStage_NoMatchModeIsPassThrough(t *testing.T) {
	client, service, cleanup := newAuditTestEnv(t)
	defer cleanup()

	seedConsumer(t, client, "consumer-1")
	seedProducerWithSchema(t, client, "p1", "ping", "1.0.0", []string{"api"}, "sha256:doesnt-matter")
	seedProducerWithSchema(t, client, "p2", "ping", "1.0.0", []string{"api"}, "sha256:also-irrelevant")

	meta := metadataForDep(map[string]interface{}{
		"capability": "ping",
		"tags":       []interface{}{"api"},
	})

	resolutions := service.ResolveAllDependenciesIndexed(meta)
	require.Len(t, resolutions, 1)
	require.NotNil(t, resolutions[0].Resolution)
	tr := resolutions[0].Trace
	require.NotNil(t, tr)

	assert.Equal(t, "none", tr.Spec.SchemaMode, "SchemaMode must default to 'none' when match_mode absent")
	schemaStage := tr.Stages[4]
	assert.Equal(t, StageSchema, schemaStage.Stage)
	assert.Empty(t, schemaStage.Evicted, "pass-through stage must not evict")
	assert.Len(t, schemaStage.Kept, 2, "all candidates pass through")
}
