package ui

// Schema Registry Browser handlers (issue #971).
//
// The canonical schema store lives in the registry (PR #841 added the read-only
// GET /schemas and GET /schemas/{hash} endpoints). The dashboard needs more:
// for each canonical hash, surface *which agents/capabilities use it* split
// into providers (declare the hash as input/output) and consumers (declare a
// dependency expecting the hash). That join lives here in the meshui server
// layer rather than the registry because it is purely a presentation concern —
// the registry's job is to identify schemas by hash, not to denormalize the
// inverse index for browsing.
//
// Strategy is "rebuild per request, no cache". Live meshes are O(hundreds) of
// capabilities; the in-memory scan is sub-millisecond. A cache layer is a
// future optimization once we have evidence it matters.
//
// Read-only by design. Mirrors the Jobs dashboard's posture (issue #973):
// the UI never mutates schemas. The only way to add or remove a SchemaEntry
// is via agent registration / sweep, both of which flow through the registry.

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/schemaentry"
)

// schemaProvider is one (agent, capability) pair that declares this schema
// either on its input or output side. JSON shape matches what
// src/ui/lib/types.ts:SchemaProvider expects.
//
// Runtime is denormalized from the owning Agent row (python/typescript/java)
// so the SPA can render the cross-runtime banner without a second join: when
// providers span >1 distinct runtimes we know PR #841's canonical-hash dedup
// is paying off.
type schemaProvider struct {
	AgentID      string `json:"agent_id"`
	AgentName    string `json:"agent_name"`
	Runtime      string `json:"runtime"`
	FunctionName string `json:"function_name"`
	Capability   string `json:"capability"`
	Role         string `json:"role"` // "input" | "output"
}

// schemaConsumer is one (agent, capability) pair that *expects* this schema
// from a dependency declaration (capability.dependencies[i].expected_schema_hash).
// We intentionally walk the declarative dependency JSON rather than the
// DependencyResolution rows: declared intent is stable across rotations and
// matches operator mental model of "who asked for this shape?".
//
// Runtime mirrors the provider field — useful for the same reason in the
// other direction (e.g. a Python consumer depending on a Java provider's
// output schema is the polyglot story we want to highlight).
type schemaConsumer struct {
	AgentID               string `json:"agent_id"`
	AgentName             string `json:"agent_name"`
	Runtime               string `json:"runtime"`
	FunctionName          string `json:"function_name"`
	Capability            string `json:"capability"`
	Via                   string `json:"via"`                     // always "dependency" for v1
	DependsOnCapability   string `json:"depends_on_capability"`   // the dep entry's `capability` value
}

// schemaListItem is one row in GET /api/schemas. The shape is intentionally
// flat (no nested providers/consumers) so the list view can render hundreds
// of rows without paying the join cost for ones the operator never opens.
type schemaListItem struct {
	Hash           string    `json:"hash"`
	RuntimeOrigin  string    `json:"runtime_origin"`
	CreatedAt      time.Time `json:"created_at"`
	ProviderCount  int       `json:"provider_count"`
	ConsumerCount  int       `json:"consumer_count"`
	SampleFunction *string   `json:"sample_function"` // first provider's function_name, or null
}

type schemasListResponse struct {
	Schemas []schemaListItem `json:"schemas"`
	Count   int              `json:"count"`
}

type schemaDetail struct {
	Hash          string                 `json:"hash"`
	Canonical     map[string]interface{} `json:"canonical"`
	RuntimeOrigin string                 `json:"runtime_origin"`
	CreatedAt     time.Time              `json:"created_at"`
}

type schemaUsageResponse struct {
	Schema    schemaDetail     `json:"schema"`
	Providers []schemaProvider `json:"providers"`
	Consumers []schemaConsumer `json:"consumers"`
}

// inverseIndex holds the result of walking every capability once and bucketing
// the (agent, function, capability) tuples into providers / consumers keyed by
// the schema hash they reference. Built fresh per request.
type inverseIndex struct {
	providers map[string][]schemaProvider
	consumers map[string][]schemaConsumer
}

// buildInverseIndex scans live agents + their eager-loaded capabilities and
// emits the providers/consumers map keyed by schema hash.
//
// A capability contributes:
//   - one provider entry per non-nil InputSchemaHash  (role="input")
//   - one provider entry per non-nil OutputSchemaHash (role="output")
//   - one consumer entry per dep with `expected_schema_hash` set
//
// Notes:
//   - Capabilities with NO schema fields at all simply don't contribute
//     anywhere — that's fine, the hash list still includes them by virtue of
//     scanning schema_entries separately.
//   - Schema rows with zero references on either side are deliberately
//     preserved in the list view (counts 0 / 0) so operators can see mid-sweep
//     state — a row that just lost its last referencing agent is interesting
//     to surface, not hide.
func buildInverseIndex(agents []*ent.Agent) *inverseIndex {
	idx := &inverseIndex{
		providers: make(map[string][]schemaProvider),
		consumers: make(map[string][]schemaConsumer),
	}

	for _, a := range agents {
		// agent.Runtime is the ent enum; String() yields "python"/"typescript"/
		// "java" or "" when never set (older rows or test seeds). The SPA
		// already tolerates an empty string in getRuntimeLabel.
		runtime := a.Runtime.String()
		for _, cap := range a.Edges.Capabilities {
			if cap.InputSchemaHash != nil && *cap.InputSchemaHash != "" {
				h := *cap.InputSchemaHash
				idx.providers[h] = append(idx.providers[h], schemaProvider{
					AgentID:      a.ID,
					AgentName:    a.Name,
					Runtime:      runtime,
					FunctionName: cap.FunctionName,
					Capability:   cap.Capability,
					Role:         "input",
				})
			}
			if cap.OutputSchemaHash != nil && *cap.OutputSchemaHash != "" {
				h := *cap.OutputSchemaHash
				idx.providers[h] = append(idx.providers[h], schemaProvider{
					AgentID:      a.ID,
					AgentName:    a.Name,
					Runtime:      runtime,
					FunctionName: cap.FunctionName,
					Capability:   cap.Capability,
					Role:         "output",
				})
			}
			for _, dep := range cap.Dependencies {
				rawHash, ok := dep["expected_schema_hash"]
				if !ok {
					continue
				}
				hashStr, ok := rawHash.(string)
				if !ok || hashStr == "" {
					continue
				}
				depCap, _ := dep["capability"].(string)
				idx.consumers[hashStr] = append(idx.consumers[hashStr], schemaConsumer{
					AgentID:             a.ID,
					AgentName:           a.Name,
					Runtime:             runtime,
					FunctionName:        cap.FunctionName,
					Capability:          cap.Capability,
					Via:                 "dependency",
					DependsOnCapability: depCap,
				})
			}
		}
	}
	return idx
}

// ListSchemasUsage implements GET /api/schemas. Joins the schema_entries table
// with the in-memory inverse index so the dashboard can render counts without
// drilling in per-row.
func (s *Server) ListSchemasUsage(c *gin.Context) {
	ctx := c.Request.Context()
	entDB := s.entService.EntDB()

	entries, err := entDB.SchemaEntry.Query().
		Order(ent.Desc(schemaentry.FieldCreatedAt)).
		All(ctx)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":     fmt.Sprintf("failed to query schemas: %v", err),
			"timestamp": time.Now().UTC(),
		})
		return
	}

	agents, err := entDB.Agent.Query().
		WithCapabilities().
		All(ctx)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":     fmt.Sprintf("failed to query agents: %v", err),
			"timestamp": time.Now().UTC(),
		})
		return
	}

	idx := buildInverseIndex(agents)

	items := make([]schemaListItem, 0, len(entries))
	for _, e := range entries {
		provs := idx.providers[e.Hash]
		cons := idx.consumers[e.Hash]
		var sample *string
		if len(provs) > 0 {
			fn := provs[0].FunctionName
			sample = &fn
		}
		items = append(items, schemaListItem{
			Hash:           e.Hash,
			RuntimeOrigin:  e.RuntimeOrigin.String(),
			CreatedAt:      e.CreatedAt,
			ProviderCount:  len(provs),
			ConsumerCount:  len(cons),
			SampleFunction: sample,
		})
	}

	c.JSON(http.StatusOK, schemasListResponse{
		Schemas: items,
		Count:   len(items),
	})
}

// GetSchemaUsage implements GET /api/schemas/:hash/usage. Returns 404 when the
// hash is not in the canonical store. Always returns provider/consumer arrays
// (possibly empty) — never null — so the SPA can render an "empty state" row
// without nil-guarding.
func (s *Server) GetSchemaUsage(c *gin.Context) {
	hash := c.Param("hash")
	ctx := c.Request.Context()
	entDB := s.entService.EntDB()

	entry, err := entDB.SchemaEntry.Query().
		Where(schemaentry.HashEQ(hash)).
		First(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			c.JSON(http.StatusNotFound, gin.H{
				"error":     fmt.Sprintf("schema not found: %s", hash),
				"timestamp": time.Now().UTC(),
			})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":     fmt.Sprintf("failed to fetch schema: %v", err),
			"timestamp": time.Now().UTC(),
		})
		return
	}

	agents, err := entDB.Agent.Query().
		WithCapabilities().
		All(ctx)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":     fmt.Sprintf("failed to query agents: %v", err),
			"timestamp": time.Now().UTC(),
		})
		return
	}

	idx := buildInverseIndex(agents)

	provs := idx.providers[hash]
	if provs == nil {
		provs = []schemaProvider{}
	}
	cons := idx.consumers[hash]
	if cons == nil {
		cons = []schemaConsumer{}
	}

	c.JSON(http.StatusOK, schemaUsageResponse{
		Schema: schemaDetail{
			Hash:          entry.Hash,
			Canonical:     entry.Canonical,
			RuntimeOrigin: entry.RuntimeOrigin.String(),
			CreatedAt:     entry.CreatedAt,
		},
		Providers: provs,
		Consumers: cons,
	})
}
