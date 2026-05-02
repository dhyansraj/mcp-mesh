package cli

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

// AuditEvent mirrors generated.RegistryEventInfo for the CLI side. Defined
// inline so the meshctl binary doesn't pull in the registry's generated
// package (and to keep the JSON shape decoupled from server-side codegen).
type AuditEvent struct {
	EventType    string                 `json:"event_type"`
	AgentID      string                 `json:"agent_id"`
	AgentName    string                 `json:"agent_name,omitempty"`
	FunctionName string                 `json:"function_name,omitempty"`
	Timestamp    time.Time              `json:"timestamp"`
	Data         map[string]interface{} `json:"data,omitempty"`
	// Trace is the parsed audit-trace shape (added for --json output so jq queries
	// can use `.events[].trace.chosen.agent_id` directly without diving through
	// the generic Data map). Only populated when serializing for --json; nil on
	// the wire from the registry.
	Trace        *auditTraceCLI         `json:"trace,omitempty"`
}

// AuditEventsResponse is the envelope returned by GET /events.
type AuditEventsResponse struct {
	Events []AuditEvent `json:"events"`
	Count  int          `json:"count"`
}

// auditTraceCLI is a CLI-side decode of the resolver's AuditTrace JSON. Keep
// this in sync with src/core/registry/audit_trace.go (consumer-only fields,
// no behavior). Using a dedicated type avoids a CLI -> registry dependency.
type auditTraceCLI struct {
	Consumer    string             `json:"consumer"`
	DepIndex    int                `json:"dep_index"`
	Spec        auditTraceSpecCLI  `json:"spec"`
	Stages      []auditTraceStage  `json:"stages"`
	Chosen      *auditTraceChosen  `json:"chosen,omitempty"`
	PriorChosen string             `json:"prior_chosen,omitempty"`
}

type auditTraceSpecCLI struct {
	Capability        string   `json:"capability"`
	Tags              []string `json:"tags,omitempty"`
	VersionConstraint string   `json:"version_constraint,omitempty"`
	SchemaMode        string   `json:"schema_mode"`
}

type auditTraceStage struct {
	Stage   string                 `json:"stage"`
	Kept    []string               `json:"kept"`
	Evicted []auditTraceEvicted    `json:"evicted,omitempty"`
	Chosen  string                 `json:"chosen,omitempty"`
	Reason  string                 `json:"reason,omitempty"`
}

type auditTraceEvicted struct {
	ID      string                 `json:"id"`
	Reason  string                 `json:"reason"`
	Details map[string]interface{} `json:"details,omitempty"`
}

type auditTraceChosen struct {
	AgentID      string `json:"agent_id"`
	Endpoint     string `json:"endpoint"`
	FunctionName string `json:"function_name"`
}

// NewAuditCommand creates the audit command.
func NewAuditCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "audit <agent-id-or-prefix>",
		Short: "Inspect dependency-resolution audit events for a consumer agent",
		Long: `Inspect persisted dependency-resolution events for a given consumer agent.

Each event records the stage-by-stage outcome of resolving one dependency,
including kept/evicted candidates, eviction reasons, and the chosen producer.

Examples:
  meshctl audit hello-world                       # tabular summary, last 20 events
  meshctl audit hello-world --dep 0               # filter to dep_index 0
  meshctl audit hello-world --explain             # pretty-print stage tree
  meshctl audit hello-world --explain --limit 5   # last 5 events, tree format
  meshctl audit hello-world --json                # raw JSON from registry`,
		Args: cobra.ExactArgs(1),
		RunE: runAuditCommand,
	}

	// Registry connection flags (mirrors meshctl trace / status).
	cmd.Flags().String("registry-url", "", "Registry URL (overrides host/port)")
	cmd.Flags().String("registry-host", "", "Registry host (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port (default: 8000)")
	cmd.Flags().String("registry-scheme", "http", "Registry URL scheme (http/https)")
	cmd.Flags().Bool("insecure", false, "Skip TLS certificate verification")
	cmd.Flags().Int("timeout", 30, "Request timeout in seconds")

	// Output / filtering flags.
	cmd.Flags().Int("limit", 20, "Maximum number of events to display (max 500)")
	cmd.Flags().Int("dep", -1, "Filter to a single dep_index (default: all)")
	cmd.Flags().Bool("explain", false, "Pretty-print each event as a stage tree")
	cmd.Flags().Bool("json", false, "Output raw JSON envelope from registry")
	cmd.Flags().String("function", "", "Filter to events for a specific consumer function")
	cmd.Flags().Bool("include-unresolved", true, "Include dependency_unresolved events (default: true)")

	return cmd
}

func runAuditCommand(cmd *cobra.Command, args []string) error {
	prefix := args[0]

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
	limit, _ := cmd.Flags().GetInt("limit")
	dep, _ := cmd.Flags().GetInt("dep")
	explain, _ := cmd.Flags().GetBool("explain")
	jsonOut, _ := cmd.Flags().GetBool("json")
	functionFilter, _ := cmd.Flags().GetString("function")
	includeUnresolved, _ := cmd.Flags().GetBool("include-unresolved")

	if limit < 1 {
		limit = 1
	}
	if limit > 500 {
		limit = 500
	}

	finalRegistryURL := determineRegistryURL(config, registryURL, registryHost, registryPort, registryScheme)
	httpClient := createHTTPClient(timeout, insecure)

	// Resolve agent prefix → concrete agent ID. Pull the full agent list and
	// reuse the same prefix-match helper as meshctl status / call so behavior
	// is consistent (e.g., `meshctl audit hello-world` resolves to
	// hello-world-9d2fa22a when only one agent matches).
	agents, err := getEnhancedAgents(finalRegistryURL)
	if err != nil {
		return fmt.Errorf("failed to fetch agents from registry: %w", err)
	}
	matchResult := ResolveAgentByPrefix(agents, prefix, false /* allow unhealthy */)
	if err := matchResult.FormattedError(); err != nil {
		return err
	}
	agentID := matchResult.Agent.ID

	// Fetch events. We always ask for both dependency_resolved and
	// dependency_unresolved by NOT setting type, then post-filter on the client
	// (the /events endpoint accepts only one type at a time).
	events, err := fetchAuditEvents(httpClient, finalRegistryURL, agentID, functionFilter, limit*2)
	if err != nil {
		return fmt.Errorf("failed to fetch events: %w", err)
	}

	// Client-side filter: only dependency-resolution events; optionally dep_index.
	filtered := make([]AuditEvent, 0, len(events))
	for _, e := range events {
		if e.EventType != "dependency_resolved" && e.EventType != "dependency_unresolved" {
			continue
		}
		if !includeUnresolved && e.EventType == "dependency_unresolved" {
			continue
		}
		if dep >= 0 {
			di, ok := extractDepIndex(e.Data)
			if !ok || di != dep {
				continue
			}
		}
		filtered = append(filtered, e)
		if len(filtered) >= limit {
			break
		}
	}

	if jsonOut {
		// Promote each event's Data into a typed Trace field so jq queries
		// can use `.events[].trace.<field>` directly (issue #547 testing).
		// Failures to decode just leave Trace nil; Data is preserved either way.
		for i := range filtered {
			if t, err := decodeTrace(filtered[i].Data); err == nil {
				filtered[i].Trace = t
			}
		}
		envelope := AuditEventsResponse{Events: filtered, Count: len(filtered)}
		out, err := json.MarshalIndent(envelope, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal JSON: %w", err)
		}
		fmt.Println(string(out))
		return nil
	}

	if len(filtered) == 0 {
		fmt.Printf("No dependency-resolution audit events for %s\n", agentID)
		fmt.Println()
		fmt.Println("Notes:")
		fmt.Println("  - Events are only emitted for multi-candidate decisions or when the chosen producer flips.")
		fmt.Println("  - Single-candidate forced choices are deliberately suppressed to reduce noise.")
		return nil
	}

	if explain {
		printAuditTree(agentID, filtered)
	} else {
		printAuditTable(agentID, filtered)
	}
	return nil
}

// fetchAuditEvents calls GET /events on the registry and decodes the response.
// Filters: agent_id (consumer) and optional function_name. limit is server-side.
func fetchAuditEvents(client *http.Client, registryURL, agentID, functionName string, limit int) ([]AuditEvent, error) {
	q := url.Values{}
	q.Set("agent_id", agentID)
	q.Set("limit", strconv.Itoa(limit))
	if functionName != "" {
		q.Set("function_name", functionName)
	}

	endpoint := strings.TrimRight(registryURL, "/") + "/events?" + q.Encode()
	resp, err := client.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("registry returned status %d: %s", resp.StatusCode, string(body))
	}

	var envelope AuditEventsResponse
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		return nil, fmt.Errorf("failed to parse events response: %w", err)
	}
	return envelope.Events, nil
}

// extractDepIndex pulls dep_index from an event's Data payload. JSON-decoded
// numbers come through as float64; tolerate int as well.
func extractDepIndex(data map[string]interface{}) (int, bool) {
	if data == nil {
		return 0, false
	}
	switch v := data["dep_index"].(type) {
	case float64:
		return int(v), true
	case int:
		return v, true
	case int64:
		return int(v), true
	}
	return 0, false
}

// decodeTrace converts an event's Data payload into the strongly-typed CLI
// audit trace. Returns nil + error for malformed payloads.
func decodeTrace(data map[string]interface{}) (*auditTraceCLI, error) {
	if data == nil {
		return nil, fmt.Errorf("event has empty data payload")
	}
	raw, err := json.Marshal(data)
	if err != nil {
		return nil, err
	}
	var t auditTraceCLI
	if err := json.Unmarshal(raw, &t); err != nil {
		return nil, err
	}
	return &t, nil
}

// stageCounts walks the stages and returns (entry-count to first stage,
// kept-count of last stage). Used to show "X → Y" candidate funneling.
func stageCounts(t *auditTraceCLI) (int, int) {
	if len(t.Stages) == 0 {
		return 0, 0
	}
	first := t.Stages[0]
	entry := len(first.Kept) + len(first.Evicted)
	final := len(t.Stages[len(t.Stages)-1].Kept)
	return entry, final
}

// printAuditTable renders the default tabular output.
//
// Columns: TIMESTAMP DEP FUNCTION CHOSEN CANDIDATES CHANGE
func printAuditTable(agentID string, events []AuditEvent) {
	fmt.Printf("Audit events for %s\n", agentID)
	fmt.Println(strings.Repeat("=", 80))
	fmt.Printf("%-22s %-5s %-22s %-22s %-12s %s\n",
		"TIMESTAMP", "DEP", "FUNCTION", "CHOSEN", "CANDIDATES", "CHANGE")
	fmt.Println(strings.Repeat("-", 100))

	for _, e := range events {
		ts := e.Timestamp.UTC().Format(time.RFC3339)
		dep := "?"
		chosen := "(unresolved)"
		candidates := "-"
		change := ""
		fn := e.FunctionName
		if fn == "" {
			fn = "-"
		}

		t, err := decodeTrace(e.Data)
		if err == nil {
			dep = fmt.Sprintf("[%d]", t.DepIndex)
			if t.Chosen != nil {
				chosen = t.Chosen.AgentID
			}
			entry, final := stageCounts(t)
			candidates = fmt.Sprintf("%d → %d", entry, final)
			if t.PriorChosen != "" && t.Chosen != nil && t.PriorChosen != t.Chosen.AgentID {
				change = fmt.Sprintf("(was %s)", t.PriorChosen)
			} else if t.PriorChosen != "" && t.Chosen == nil {
				change = fmt.Sprintf("(lost: %s)", t.PriorChosen)
			}
		}

		fmt.Printf("%-22s %-5s %-22s %-22s %-12s %s\n",
			truncate(ts, 22), dep, truncate(fn, 22), truncate(chosen, 22), candidates, change)
	}
}

// printAuditTree renders one event per block as a stage-by-stage tree.
func printAuditTree(agentID string, events []AuditEvent) {
	fmt.Printf("Audit events for %s (%d shown)\n", agentID, len(events))
	fmt.Println(strings.Repeat("=", 80))

	for i, e := range events {
		if i > 0 {
			fmt.Println()
		}
		printAuditTreeOne(e)
	}
}

func printAuditTreeOne(e AuditEvent) {
	ts := e.Timestamp.UTC().Format(time.RFC3339)
	t, err := decodeTrace(e.Data)
	if err != nil {
		fmt.Printf("%s  %s  (failed to decode trace: %v)\n", ts, e.EventType, err)
		return
	}

	header := fmt.Sprintf("%s  dep[%d]  capability=%s", ts, t.DepIndex, t.Spec.Capability)
	if e.FunctionName != "" {
		header += fmt.Sprintf("  function=%s", e.FunctionName)
	}
	fmt.Println(header)

	specBits := []string{}
	if len(t.Spec.Tags) > 0 {
		specBits = append(specBits, "tags="+strings.Join(t.Spec.Tags, ","))
	}
	if t.Spec.VersionConstraint != "" {
		specBits = append(specBits, "version="+t.Spec.VersionConstraint)
	}
	if len(specBits) > 0 {
		fmt.Printf("  spec: %s\n", strings.Join(specBits, "  "))
	}

	for _, s := range t.Stages {
		kept := s.Kept
		// Sort kept lexicographically for stable output.
		sortedKept := append([]string(nil), kept...)
		sort.Strings(sortedKept)

		summary := fmt.Sprintf("[kept %d]", len(kept))
		if len(s.Evicted) > 0 {
			summary = fmt.Sprintf("[kept %d, evicted %d]", len(kept), len(s.Evicted))
		}
		fmt.Printf("  ├─ %s  %s\n", s.Stage, summary)

		// On the tiebreaker stage we already print "chosen:" below, so omit
		// the redundant "kept:" line. Mirrors registry.StageTiebreaker.
		if len(sortedKept) > 0 && s.Stage != "tiebreaker" {
			fmt.Printf("  │    kept: %s\n", strings.Join(sortedKept, ", "))
		}
		for _, ev := range s.Evicted {
			fmt.Printf("  │    ✗ %s — %s", ev.ID, ev.Reason)
			if len(ev.Details) > 0 {
				fmt.Printf(" %s", formatDetails(ev.Details))
			}
			fmt.Println()
		}
		if s.Chosen != "" {
			fmt.Printf("  │    chosen: %s (%s)\n", s.Chosen, s.Reason)
		}
	}

	if t.Chosen != nil {
		fmt.Printf("  └─ ✓ chosen: %s  endpoint=%s  function=%s\n",
			t.Chosen.AgentID, t.Chosen.Endpoint, t.Chosen.FunctionName)
	} else {
		fmt.Println("  └─ ✗ no resolution")
	}

	if t.PriorChosen != "" {
		if t.Chosen != nil && t.PriorChosen != t.Chosen.AgentID {
			fmt.Printf("     prior_chosen: %s  (chosen flipped)\n", t.PriorChosen)
		} else if t.Chosen == nil {
			fmt.Printf("     prior_chosen: %s  (was previously resolved)\n", t.PriorChosen)
		} else {
			fmt.Printf("     prior_chosen: %s\n", t.PriorChosen)
		}
	}
}

// formatDetails renders an evicted candidate's details map compactly.
func formatDetails(d map[string]interface{}) string {
	if len(d) == 0 {
		return ""
	}
	keys := make([]string, 0, len(d))
	for k := range d {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, fmt.Sprintf("%s=%v", k, d[k]))
	}
	return "{" + strings.Join(parts, ", ") + "}"
}

// truncate caps a string to width with an ellipsis when needed. Used for
// tabular output where wide IDs would blow up column alignment.
func truncate(s string, width int) string {
	if len(s) <= width {
		return s
	}
	if width <= 1 {
		return s[:width]
	}
	return s[:width-1] + "…"
}
