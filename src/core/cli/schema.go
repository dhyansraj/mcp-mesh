package cli

// meshctl schema-registry visibility tooling (issue #547).
//
// Provides:
//   - `runSchemasListCommand`  → backs `meshctl list --schemas`
//   - `NewSchemaCommand`       → top-level `meshctl schema` with `diff` subcommand
//
// Both helpers talk to GET /schemas and GET /schemas/{hash} on the registry.

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// SchemaEntry mirrors generated.SchemaEntryInfo for the CLI side. Defined
// inline so the meshctl binary doesn't pull in the registry's generated
// package (matches the pattern used in audit.go).
type SchemaEntry struct {
	Hash          string                 `json:"hash"`
	Canonical     map[string]interface{} `json:"canonical"`
	RuntimeOrigin string                 `json:"runtime_origin"`
	CreatedAt     time.Time              `json:"created_at"`
}

// SchemasListResponse is the envelope returned by GET /schemas.
type SchemasListResponse struct {
	Schemas []SchemaEntry `json:"schemas"`
	Count   int           `json:"count"`
}

// runSchemasListCommand handles `meshctl list --schemas`. Renders a table by
// default; raw envelope when jsonOutput is true.
func runSchemasListCommand(registryURL string, timeoutSeconds int, insecure bool, limit int, jsonOutput bool) error {
	if limit < 1 {
		limit = 1
	}
	if limit > 1000 {
		limit = 1000
	}

	client := createHTTPClient(timeoutSeconds, insecure)
	envelope, err := fetchSchemasList(client, registryURL, limit)
	if err != nil {
		return err
	}

	if jsonOutput {
		out, err := json.MarshalIndent(envelope, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal JSON: %w", err)
		}
		fmt.Println(string(out))
		return nil
	}

	if len(envelope.Schemas) == 0 {
		fmt.Println("No canonical schemas registered.")
		fmt.Println()
		fmt.Println("Schemas are populated as agents register tools whose runtime emits")
		fmt.Println("inputSchemaCanonical / outputSchemaCanonical (issue #547).")
		return nil
	}

	printSchemasTable(envelope.Schemas)
	return nil
}

// NewSchemaCommand creates the top-level `meshctl schema` command with the
// `diff` subcommand. Issue #547 schema-registry diagnostics.
func NewSchemaCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "schema",
		Short: "Inspect canonical schemas registered with the mesh (issue #547)",
		Long: `Operator tooling for the registry's content-addressed schema store.

Schemas are produced by the Rust normalizer running inside each runtime SDK
(Python, TypeScript, Java) and uploaded to the registry on agent registration.
The registry deduplicates by sha256 hash of the canonical form, so identical
schemas across runtimes share a single row.

Subcommands:
  diff   Compare two canonical schemas by hash`,
	}

	cmd.AddCommand(newSchemaDiffCommand())
	return cmd
}

func newSchemaDiffCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "diff <hashA> <hashB>",
		Short: "Diff two canonical schemas by their content hash",
		Long: `Fetch two canonical schemas by hash and render a structural diff.

Diff focuses on the JSON Schema "properties" + "required" shape:
  -  fields present in A but not in B  (red)
  +  fields present in B but not in A  (green)
  ~  fields present in both with different types  (yellow)

Use --json for tsuite-friendly programmatic output (issue #547).

Examples:
  meshctl schema diff sha256:abc... sha256:def...
  meshctl schema diff sha256:abc... sha256:def... --json`,
		Args: cobra.ExactArgs(2),
		RunE: runSchemaDiffCommand,
	}

	cmd.Flags().String("registry-url", "", "Registry URL (overrides host/port)")
	cmd.Flags().String("registry-host", "", "Registry host (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port (default: 8000)")
	cmd.Flags().String("registry-scheme", "http", "Registry URL scheme (http/https)")
	cmd.Flags().Bool("insecure", false, "Skip TLS certificate verification")
	cmd.Flags().Int("timeout", 30, "Request timeout in seconds")
	cmd.Flags().Bool("json", false, "Output the diff as a structured JSON document")
	return cmd
}

func runSchemaDiffCommand(cmd *cobra.Command, args []string) error {
	hashA, hashB := args[0], args[1]

	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	registryURL, _ := cmd.Flags().GetString("registry-url")
	registryHost, _ := cmd.Flags().GetString("registry-host")
	registryPort, _ := cmd.Flags().GetInt("registry-port")
	registryScheme, _ := cmd.Flags().GetString("registry-scheme")
	insecure, _ := cmd.Flags().GetBool("insecure")
	timeout, _ := cmd.Flags().GetInt("timeout")
	jsonOut, _ := cmd.Flags().GetBool("json")

	finalRegistryURL := determineRegistryURL(config, registryURL, registryHost, registryPort, registryScheme)
	client := createHTTPClient(timeout, insecure)

	entryA, err := fetchSchemaByHash(client, finalRegistryURL, hashA)
	if err != nil {
		return err
	}
	entryB, err := fetchSchemaByHash(client, finalRegistryURL, hashB)
	if err != nil {
		return err
	}

	diff := diffSchemas(entryA.Canonical, entryB.Canonical)

	if jsonOut {
		envelope := map[string]interface{}{
			"a":    entryA,
			"b":    entryB,
			"diff": diff,
		}
		out, err := json.MarshalIndent(envelope, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal JSON: %w", err)
		}
		fmt.Println(string(out))
		return nil
	}

	printSchemaDiff(entryA, entryB, diff)
	return nil
}

// fetchSchemasList calls GET /schemas?limit=N.
func fetchSchemasList(client *http.Client, registryURL string, limit int) (*SchemasListResponse, error) {
	q := url.Values{}
	q.Set("limit", strconv.Itoa(limit))
	endpoint := strings.TrimRight(registryURL, "/") + "/schemas?" + q.Encode()

	resp, err := client.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("registry returned status %d: %s", resp.StatusCode, string(body))
	}

	var envelope SchemasListResponse
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		return nil, fmt.Errorf("failed to parse schemas response: %w", err)
	}
	return &envelope, nil
}

// fetchSchemaByHash calls GET /schemas/{hash}.
func fetchSchemaByHash(client *http.Client, registryURL, hash string) (*SchemaEntry, error) {
	endpoint := strings.TrimRight(registryURL, "/") + "/schemas/" + url.PathEscape(hash)

	resp, err := client.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil, fmt.Errorf("schema not found: %s", hash)
	}
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("registry returned status %d for %s: %s", resp.StatusCode, hash, string(body))
	}

	var entry SchemaEntry
	if err := json.NewDecoder(resp.Body).Decode(&entry); err != nil {
		return nil, fmt.Errorf("failed to parse schema response: %w", err)
	}
	return &entry, nil
}

// printSchemasTable renders a tabular listing of schema entries.
func printSchemasTable(entries []SchemaEntry) {
	fmt.Printf("Canonical schema entries (%d shown)\n", len(entries))
	fmt.Println(strings.Repeat("=", 100))
	fmt.Printf("%-20s %-12s %-20s %s\n", "HASH", "ORIGIN", "CREATED", "CANONICAL_PREVIEW")
	fmt.Println(strings.Repeat("-", 100))
	for _, e := range entries {
		fmt.Printf("%-20s %-12s %-20s %s\n",
			truncateHash(e.Hash),
			e.RuntimeOrigin,
			e.CreatedAt.UTC().Format("2006-01-02 15:04:05"),
			canonicalPreview(e.Canonical, 60),
		)
	}
}

// truncateHash renders a sha256:<hex> hash as "sha256:abcdef012345…7890a".
// Keeps prefix + last 5 chars so collisions in eyeballed listings are obvious.
func truncateHash(h string) string {
	const head = 12
	const tail = 5
	if !strings.HasPrefix(h, "sha256:") {
		if len(h) <= head+tail+1 {
			return h
		}
		return h[:head] + "…" + h[len(h)-tail:]
	}
	body := strings.TrimPrefix(h, "sha256:")
	if len(body) <= head+tail+1 {
		return h
	}
	return "sha256:" + body[:head-7] + "…" + body[len(body)-tail:]
}

// canonicalPreview renders a compact "{properties: {...}, required: [...]}"
// summary of a JSON Schema shape, truncated to maxLen.
func canonicalPreview(c map[string]interface{}, maxLen int) string {
	if len(c) == 0 {
		return "(empty)"
	}

	parts := []string{}
	if props, ok := c["properties"].(map[string]interface{}); ok {
		keys := sortedKeys(props)
		parts = append(parts, "properties: {"+strings.Join(keys, ",")+"}")
	}
	if req, ok := c["required"].([]interface{}); ok && len(req) > 0 {
		ss := make([]string, 0, len(req))
		for _, r := range req {
			if s, ok := r.(string); ok {
				ss = append(ss, s)
			}
		}
		parts = append(parts, "required: ["+strings.Join(ss, ",")+"]")
	}
	if t, ok := c["type"].(string); ok && len(parts) == 0 {
		parts = append(parts, "type: "+t)
	}
	if len(parts) == 0 {
		// Fall back to a short marshalled form so non-object shapes still render.
		raw, _ := json.Marshal(c)
		return truncateStringForList(string(raw), maxLen)
	}
	return truncateStringForList("{"+strings.Join(parts, ", ")+"}", maxLen)
}

func sortedKeys(m map[string]interface{}) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// SchemaDiff is the structural diff result. Mirrors the JSON envelope so
// `--json` output is stable and tsuite-friendly.
type SchemaDiff struct {
	OnlyInA     []SchemaDiffField  `json:"only_in_a"`
	OnlyInB     []SchemaDiffField  `json:"only_in_b"`
	TypeChanged []SchemaDiffChange `json:"type_changed"`
	RequiredA   []string           `json:"required_a,omitempty"`
	RequiredB   []string           `json:"required_b,omitempty"`
	HashEqual   bool               `json:"hash_equal"`
}

type SchemaDiffField struct {
	Name string `json:"name"`
	Type string `json:"type,omitempty"`
}

type SchemaDiffChange struct {
	Name  string `json:"name"`
	TypeA string `json:"type_a,omitempty"`
	TypeB string `json:"type_b,omitempty"`
}

// diffSchemas computes a focused diff over JSON Schema's `properties` map
// (deliberately not a generic JSON diff — the payloads we care about are
// always JSON Schemas).
func diffSchemas(a, b map[string]interface{}) SchemaDiff {
	propsA := propertiesOf(a)
	propsB := propertiesOf(b)

	diff := SchemaDiff{
		OnlyInA:     []SchemaDiffField{},
		OnlyInB:     []SchemaDiffField{},
		TypeChanged: []SchemaDiffChange{},
	}

	for _, k := range sortedKeys(propsA) {
		if _, ok := propsB[k]; !ok {
			diff.OnlyInA = append(diff.OnlyInA, SchemaDiffField{Name: k, Type: typeOfProp(propsA[k])})
		}
	}
	for _, k := range sortedKeys(propsB) {
		if _, ok := propsA[k]; !ok {
			diff.OnlyInB = append(diff.OnlyInB, SchemaDiffField{Name: k, Type: typeOfProp(propsB[k])})
		}
	}
	for _, k := range sortedKeys(propsA) {
		bv, ok := propsB[k]
		if !ok {
			continue
		}
		ta := typeOfProp(propsA[k])
		tb := typeOfProp(bv)
		if ta != tb {
			diff.TypeChanged = append(diff.TypeChanged, SchemaDiffChange{Name: k, TypeA: ta, TypeB: tb})
		}
	}

	diff.RequiredA = requiredOf(a)
	diff.RequiredB = requiredOf(b)
	return diff
}

func propertiesOf(c map[string]interface{}) map[string]interface{} {
	if c == nil {
		return map[string]interface{}{}
	}
	if p, ok := c["properties"].(map[string]interface{}); ok {
		return p
	}
	return map[string]interface{}{}
}

func typeOfProp(v interface{}) string {
	m, ok := v.(map[string]interface{})
	if !ok {
		return ""
	}
	if t, ok := m["type"].(string); ok {
		return t
	}
	// Some JSON schemas use $ref or nested oneOf — render a marker so the diff
	// at least flags the shape difference rather than swallowing it silently.
	if _, ok := m["$ref"]; ok {
		return "$ref"
	}
	if _, ok := m["oneOf"]; ok {
		return "oneOf"
	}
	if _, ok := m["anyOf"]; ok {
		return "anyOf"
	}
	return ""
}

func requiredOf(c map[string]interface{}) []string {
	if c == nil {
		return nil
	}
	raw, ok := c["required"].([]interface{})
	if !ok {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, v := range raw {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	sort.Strings(out)
	return out
}

// printSchemaDiff renders the diff as a colored, indented tree.
func printSchemaDiff(a, b *SchemaEntry, d SchemaDiff) {
	fmt.Printf("Schema diff\n")
	fmt.Println(strings.Repeat("=", 80))
	fmt.Printf("  A: %s  origin=%s  created=%s\n", a.Hash, a.RuntimeOrigin, a.CreatedAt.UTC().Format(time.RFC3339))
	fmt.Printf("  B: %s  origin=%s  created=%s\n", b.Hash, b.RuntimeOrigin, b.CreatedAt.UTC().Format(time.RFC3339))
	fmt.Println()

	if a.Hash == b.Hash {
		fmt.Println("(both hashes are identical — schemas are byte-for-byte equal)")
		return
	}

	if len(d.OnlyInA) == 0 && len(d.OnlyInB) == 0 && len(d.TypeChanged) == 0 && stringSliceEqual(d.RequiredA, d.RequiredB) {
		fmt.Println("(no structural differences in properties/required; check additionalProperties or other top-level keys)")
		return
	}

	if len(d.OnlyInA) > 0 {
		fmt.Println("Fields only in A:")
		for _, f := range d.OnlyInA {
			fmt.Printf("  %s- %s%s%s%s\n", colorRed, f.Name, dimType(f.Type), "", colorReset)
		}
	}
	if len(d.OnlyInB) > 0 {
		fmt.Println("Fields only in B:")
		for _, f := range d.OnlyInB {
			fmt.Printf("  %s+ %s%s%s\n", colorGreen, f.Name, dimType(f.Type), colorReset)
		}
	}
	if len(d.TypeChanged) > 0 {
		fmt.Println("Type changes:")
		for _, ch := range d.TypeChanged {
			fmt.Printf("  %s~ %s: %s → %s%s\n", colorYellow, ch.Name, ch.TypeA, ch.TypeB, colorReset)
		}
	}
	if !stringSliceEqual(d.RequiredA, d.RequiredB) {
		fmt.Println("Required fields:")
		fmt.Printf("  A: [%s]\n", strings.Join(d.RequiredA, ", "))
		fmt.Printf("  B: [%s]\n", strings.Join(d.RequiredB, ", "))
	}
}

func dimType(t string) string {
	if t == "" {
		return ""
	}
	return " (" + t + ")"
}

func stringSliceEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
