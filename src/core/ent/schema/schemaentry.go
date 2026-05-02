package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// SchemaEntry holds canonical normalized JSON schemas, content-addressed by hash.
// Many Capability rows reference the same SchemaEntry when their canonical
// schema is identical — i.e. dedup by structural equivalence after normalization.
type SchemaEntry struct {
	ent.Schema
}

// Fields of the SchemaEntry.
func (SchemaEntry) Fields() []ent.Field {
	return []ent.Field{
		field.String("hash").
			Unique().
			NotEmpty().
			Comment("Content hash like 'sha256:abc...'. Primary identity."),
		field.JSON("canonical", map[string]interface{}{}).
			Comment("Canonical normalized JSON Schema (post-normalizer output)."),
		field.Enum("runtime_origin").
			Values("python", "typescript", "java", "unknown").
			Default("unknown").
			Comment("Runtime that originally produced the raw schema. Informational."),
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("First time this canonical schema was seen by the registry."),
	}
}

// No edges intentionally — Capabilities reference SchemaEntries by raw hash
// string, not via FK. Keeps the content-addressed store free of cascade-delete
// entanglement and lets multiple capabilities (or future consumers) share rows
// without ownership semantics.

// Indexes of the SchemaEntry.
func (SchemaEntry) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("hash").Unique(),
	}
}
