package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// jobRecord mirrors the registry's generated.Job for the CLI side. Defined
// inline so the meshctl binary doesn't pull in the registry's generated
// package (same decoupling as AuditEvent). Only the fields meshctl renders
// are declared; unknown fields are ignored on decode.
type jobRecord struct {
	ID              string `json:"id"`
	Capability      string `json:"capability"`
	Status          string `json:"status"`
	OwnerInstanceID *string `json:"owner_instance_id"`
	ClaimEpoch      int64  `json:"claim_epoch"`
	AttemptCount    int    `json:"attempt_count"`
	MaxRetries      int    `json:"max_retries"`
	ProgressMessage *string `json:"progress_message"`
	Error           *string `json:"error"`
	LeaseExpiresAt  *int64 `json:"lease_expires_at"`
	LastHeartbeatAt *int64 `json:"last_heartbeat_at"`
	SubmittedAt     int64  `json:"submitted_at"`
	SubmittedBy     string `json:"submitted_by"`
}

// reclaimResult mirrors the registry's generated.ReclaimJobResponse.
type reclaimResult struct {
	Status                  string  `json:"status"`
	PreviousOwnerInstanceID *string `json:"previous_owner_instance_id"`
	ClaimEpoch              int64   `json:"claim_epoch"`
}

// NewJobCommand creates the job command group (MeshJob observability + admin).
func NewJobCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "job",
		Short: "Inspect and administer MeshJobs (long-running async tool calls)",
		Long: `Inspect and administer MeshJobs — the async substrate behind long-running tool calls.

Examples:
  meshctl job status 8f2b4e6a-1c3d-4e5f-9a0b-1c2d3e4f5a6b
  meshctl job reclaim 8f2b4e6a-1c3d-4e5f-9a0b-1c2d3e4f5a6b`,
	}
	cmd.AddCommand(newJobStatusCommand())
	cmd.AddCommand(newJobReclaimCommand())
	return cmd
}

// addRegistryFlags attaches the standard registry-connection flags shared by
// the job/registry commands (mirrors meshctl audit / trace / status).
func addRegistryFlags(cmd *cobra.Command) {
	cmd.Flags().String("registry-url", "", "Registry URL (overrides host/port)")
	cmd.Flags().String("registry-host", "", "Registry host (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port (default: 8000)")
	cmd.Flags().String("registry-scheme", "http", "Registry URL scheme (http/https)")
	cmd.Flags().Bool("insecure", false, "Skip TLS certificate verification")
	cmd.Flags().Int("timeout", 30, "Request timeout in seconds")
}

// resolveRegistry loads config + resolves the registry URL and HTTP client
// from the standard registry-connection flags.
func resolveRegistry(cmd *cobra.Command) (string, *http.Client, error) {
	config, err := LoadConfig()
	if err != nil {
		return "", nil, fmt.Errorf("failed to load configuration: %w", err)
	}
	registryURL, _ := cmd.Flags().GetString("registry-url")
	registryHost, _ := cmd.Flags().GetString("registry-host")
	registryPort, _ := cmd.Flags().GetInt("registry-port")
	registryScheme, _ := cmd.Flags().GetString("registry-scheme")
	insecure, _ := cmd.Flags().GetBool("insecure")
	timeout, _ := cmd.Flags().GetInt("timeout")

	finalURL := determineRegistryURL(config, registryURL, registryHost, registryPort, registryScheme)
	client := createHTTPClient(timeout, insecure)
	return finalURL, client, nil
}

func newJobStatusCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "status <job_id>",
		Short: "Show the current state of a MeshJob",
		Long: `Fetch the latest persisted state of a MeshJob from the registry, including
the fencing / lease fields (claim_epoch, owner, attempt_count, lease_expires_at)
used for post-incident forensics.

A claim_epoch greater than 1 means the job was re-claimed at least once
(owner change / fencing event) during its lifetime.

Examples:
  meshctl job status 8f2b4e6a-1c3d-4e5f-9a0b-1c2d3e4f5a6b
  meshctl job status 8f2b4e6a-... --json`,
		Args: cobra.ExactArgs(1),
		RunE: runJobStatus,
	}
	addRegistryFlags(cmd)
	cmd.Flags().Bool("json", false, "Output raw JSON from registry")
	return cmd
}

func runJobStatus(cmd *cobra.Command, args []string) error {
	jobID := args[0]
	registryURL, client, err := resolveRegistry(cmd)
	if err != nil {
		return err
	}
	jsonOut, _ := cmd.Flags().GetBool("json")

	endpoint := strings.TrimRight(registryURL, "/") + "/jobs/" + jobID
	resp, err := client.Get(endpoint)
	if err != nil {
		return fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode == http.StatusNotFound {
		return fmt.Errorf("job not found: %s", jobID)
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("registry returned status %d: %s", resp.StatusCode, string(body))
	}

	if jsonOut {
		fmt.Fprintln(cmd.OutOrStdout(), string(body))
		return nil
	}

	var j jobRecord
	if err := json.Unmarshal(body, &j); err != nil {
		return fmt.Errorf("failed to parse job response: %w", err)
	}
	printJob(cmd, &j)
	return nil
}

func printJob(cmd *cobra.Command, j *jobRecord) {
	out := cmd.OutOrStdout()
	fmt.Fprintf(out, "Job:          %s\n", j.ID)
	fmt.Fprintf(out, "Capability:   %s\n", j.Capability)
	fmt.Fprintf(out, "Status:       %s\n", j.Status)
	fmt.Fprintf(out, "Owner:        %s\n", derefOr(j.OwnerInstanceID, "(unclaimed)"))
	fmt.Fprintf(out, "Claim epoch:  %d\n", j.ClaimEpoch)
	fmt.Fprintf(out, "Attempts:     %d / %d (max_retries)\n", j.AttemptCount, j.MaxRetries)
	if j.ProgressMessage != nil && *j.ProgressMessage != "" {
		fmt.Fprintf(out, "Progress:     %s\n", *j.ProgressMessage)
	}
	fmt.Fprintf(out, "Lease expiry: %s\n", formatEpoch(j.LeaseExpiresAt))
	fmt.Fprintf(out, "Last beat:    %s\n", formatEpoch(j.LastHeartbeatAt))
	fmt.Fprintf(out, "Submitted:    %s by %s\n", formatEpoch(&j.SubmittedAt), j.SubmittedBy)
	if j.Error != nil && *j.Error != "" {
		fmt.Fprintf(out, "Error:        %s\n", *j.Error)
	}
}

func newJobReclaimCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "reclaim <job_id>",
		Short: "Force-reclaim a MeshJob (evict its current owner's lease)",
		Long: `Force the lease-expiry path for a single job: clears the owner and lease so
the job becomes claimable again, exactly as the registry's orphan sweep does.
claim_epoch is left unchanged — the NEXT claim mints the new generation, which
fences the superseded execution (claim_superseded).

Use it to deliberately exercise epoch fencing / supersession in staging and
incident drills (a healthy handler renews its lease every poll, so a natural
re-claim is otherwise nearly impossible to produce), or to evict a job from a
replica that must be drained.

Terminal jobs cannot be reclaimed.

Examples:
  meshctl job reclaim 8f2b4e6a-1c3d-4e5f-9a0b-1c2d3e4f5a6b`,
		Args: cobra.ExactArgs(1),
		RunE: runJobReclaim,
	}
	addRegistryFlags(cmd)
	return cmd
}

func runJobReclaim(cmd *cobra.Command, args []string) error {
	jobID := args[0]
	registryURL, client, err := resolveRegistry(cmd)
	if err != nil {
		return err
	}

	endpoint := strings.TrimRight(registryURL, "/") + "/jobs/" + jobID + "/reclaim"
	resp, err := client.Post(endpoint, "application/json", nil)
	if err != nil {
		return fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	switch resp.StatusCode {
	case http.StatusOK:
		// fallthrough to render below
	case http.StatusNotFound:
		return fmt.Errorf("job not found: %s", jobID)
	case http.StatusConflict:
		return fmt.Errorf("job %s is already in a terminal state — nothing to reclaim", jobID)
	default:
		return fmt.Errorf("registry returned status %d: %s", resp.StatusCode, string(body))
	}

	var r reclaimResult
	if err := json.Unmarshal(body, &r); err != nil {
		return fmt.Errorf("failed to parse reclaim response: %w", err)
	}

	out := cmd.OutOrStdout()
	fmt.Fprintf(out, "Job %s reclaimed\n", jobID)
	fmt.Fprintf(out, "  Evicted owner: %s\n", derefOr(r.PreviousOwnerInstanceID, "(none — was unclaimed)"))
	fmt.Fprintf(out, "  Status:        %s (claimable)\n", r.Status)
	fmt.Fprintf(out, "  Claim epoch:   %d (unchanged; next claim mints the next epoch)\n", r.ClaimEpoch)
	return nil
}

// derefOr returns the pointed-to string, or fallback when nil/empty.
func derefOr(s *string, fallback string) string {
	if s == nil || *s == "" {
		return fallback
	}
	return *s
}

// formatEpoch renders a nullable Unix-epoch-seconds field as RFC3339, or a
// dash when absent.
func formatEpoch(epoch *int64) string {
	if epoch == nil || *epoch == 0 {
		return "-"
	}
	return time.Unix(*epoch, 0).UTC().Format(time.RFC3339)
}
