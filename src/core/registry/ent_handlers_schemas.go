package registry

// Handlers for the canonical schema registry endpoints (issue #547).
// Backs `meshctl list --schemas` and `meshctl schema diff` for operator
// visibility into the content-addressed schema store.

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/schemaentry"
	"mcp-mesh/src/core/registry/generated"
)

// ListSchemas implements GET /schemas. Returns the most recent canonical
// schema entries (newest-first), bounded by `limit` (default 100, max 1000).
func (h *EntBusinessLogicHandlers) ListSchemas(c *gin.Context, params generated.ListSchemasParams) {
	limit := 100
	if params.Limit != nil {
		limit = *params.Limit
		if limit < 1 {
			limit = 1
		}
		if limit > 1000 {
			limit = 1000
		}
	}

	entries, err := h.entService.entDB.SchemaEntry.Query().
		Order(ent.Desc(schemaentry.FieldCreatedAt)).
		Limit(limit).
		All(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to query schemas: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	items := make([]generated.SchemaEntryInfo, 0, len(entries))
	for _, e := range entries {
		items = append(items, generated.SchemaEntryInfo{
			Hash:          e.Hash,
			Canonical:     e.Canonical,
			RuntimeOrigin: generated.SchemaEntryInfoRuntimeOrigin(e.RuntimeOrigin.String()),
			CreatedAt:     e.CreatedAt,
		})
	}

	c.JSON(http.StatusOK, generated.SchemaEntriesResponse{
		Schemas: items,
		Count:   len(items),
	})
}

// GetSchema implements GET /schemas/{hash}. Returns 404 when no row matches.
func (h *EntBusinessLogicHandlers) GetSchema(c *gin.Context, hash string) {
	entry, err := h.entService.entDB.SchemaEntry.Query().
		Where(schemaentry.HashEQ(hash)).
		First(c.Request.Context())
	if err != nil {
		if ent.IsNotFound(err) {
			c.JSON(http.StatusNotFound, generated.ErrorResponse{
				Error:     fmt.Sprintf("schema not found: %s", hash),
				Timestamp: time.Now().UTC(),
			})
			return
		}
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to fetch schema: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	c.JSON(http.StatusOK, generated.SchemaEntryInfo{
		Hash:          entry.Hash,
		Canonical:     entry.Canonical,
		RuntimeOrigin: generated.SchemaEntryInfoRuntimeOrigin(entry.RuntimeOrigin.String()),
		CreatedAt:     entry.CreatedAt,
	})
}
