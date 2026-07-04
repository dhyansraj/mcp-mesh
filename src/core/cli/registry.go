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

// drainState mirrors the registry's /admin/drain JSON response.
type drainState struct {
	Draining   bool `json:"draining"`
	LiveClaims int  `json:"live_claims"`
}

// NewRegistryCommand creates the registry admin command group.
func NewRegistryCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "registry",
		Short: "Administer a running registry (drain, resume, status)",
		Long: `Administer a running MCP Mesh registry.

Drain mode lets in-flight jobs finish while pausing new job dispatch, turning
the manual "quiet window" before an upgrade/restart into a supported operation.

These commands call the registry's admin endpoints (/admin/drain). If the
registry is hardened with a separate admin port (MCP_MESH_ADMIN_PORT), those
endpoints live ONLY on the admin port — point --registry-url at it:
  meshctl registry status --registry-url http://localhost:<admin-port>

Drain state is per-replica and in-memory. In a multi-replica (HA) topology a
load balancer may route each command to a different replica, so status can
flap and a single drain does not pause the whole fleet — drain EVERY replica
(target each replica's address directly) before an upgrade, and remember a
restart of any replica clears its drain.

Examples:
  meshctl registry status
  meshctl registry drain --wait
  meshctl registry resume`,
	}
	cmd.AddCommand(newRegistryDrainCommand())
	cmd.AddCommand(newRegistryResumeCommand())
	cmd.AddCommand(newRegistryStatusCommand())
	return cmd
}

func newRegistryDrainCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "drain",
		Short: "Enter drain mode — pause new job claims, let running jobs finish",
		Long: `Put the registry into drain mode. While draining:
  - new job claims return no work (queued jobs stay queued, no attempt burn)
  - running jobs keep renewing their leases and complete normally
  - job submissions are still accepted (queued for after resume)

Drain state is per-replica and in-memory only — a registry restart clears it.
In a multi-replica (HA) topology this pauses only the replica that served the
request; drain EVERY replica (target each address directly) before upgrading.

With --wait, blocks until zero live claims remain (every non-terminal job has
released its owner), then returns so you can safely upgrade/restart. --wait
aborts with an error if the registry stops draining mid-wait (a concurrent
resume or restart), since new claims would have resumed.

If the registry runs a separate admin port, pass its address:
  meshctl registry drain --registry-url http://localhost:<admin-port>

Examples:
  meshctl registry drain
  meshctl registry drain --wait
  meshctl registry drain --wait --wait-timeout 300`,
		Args: cobra.NoArgs,
		RunE: runRegistryDrain,
	}
	addRegistryFlags(cmd)
	cmd.Flags().Bool("wait", false, "Block until zero live claims remain")
	cmd.Flags().Int("wait-timeout", 0, "Max seconds to wait with --wait (0 = no timeout)")
	cmd.Flags().Int("poll-interval", 2, "Seconds between live-claim polls with --wait")
	return cmd
}

func runRegistryDrain(cmd *cobra.Command, args []string) error {
	registryURL, client, err := resolveRegistry(cmd)
	if err != nil {
		return err
	}
	wait, _ := cmd.Flags().GetBool("wait")
	waitTimeout, _ := cmd.Flags().GetInt("wait-timeout")
	pollInterval, _ := cmd.Flags().GetInt("poll-interval")
	if pollInterval < 1 {
		pollInterval = 1
	}

	st, err := postDrain(client, registryURL, http.MethodPost)
	if err != nil {
		return err
	}

	out := cmd.OutOrStdout()
	fmt.Fprintf(out, "Registry draining — new job claims paused\n")
	fmt.Fprintf(out, "  Live claims: %d\n", st.LiveClaims)

	if !wait {
		if st.LiveClaims > 0 {
			fmt.Fprintf(out, "Note: %d job(s) still running; poll `meshctl registry status` or re-run with --wait\n", st.LiveClaims)
		}
		return nil
	}

	deadline := time.Time{}
	if waitTimeout > 0 {
		deadline = time.Now().Add(time.Duration(waitTimeout) * time.Second)
	}
	for st.LiveClaims > 0 {
		if !deadline.IsZero() && time.Now().After(deadline) {
			return fmt.Errorf("timed out after %ds with %d live claim(s) still running", waitTimeout, st.LiveClaims)
		}
		time.Sleep(time.Duration(pollInterval) * time.Second)
		st, err = getDrain(client, registryURL)
		if err != nil {
			return err
		}
		// Drain is in-memory per-replica: a concurrent `registry resume` or a
		// registry restart clears the flag. If that happens, new claims have
		// resumed and any remaining live_claims count is no longer a safe
		// "quiet window" — fail loudly instead of reporting "safe to restart".
		if !st.Draining {
			return fmt.Errorf("registry is no longer draining (concurrent resume or restart?) — aborting wait; re-run `meshctl registry drain --wait` if you still intend to drain")
		}
		fmt.Fprintf(out, "  Live claims: %d\n", st.LiveClaims)
	}
	fmt.Fprintln(out, "All jobs drained — safe to upgrade/restart")
	return nil
}

func newRegistryResumeCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "resume",
		Short: "Exit drain mode — resume normal job dispatch",
		Long: `Take the registry out of drain mode. Queued jobs become claimable again in
FIFO order as usual.

Examples:
  meshctl registry resume`,
		Args: cobra.NoArgs,
		RunE: runRegistryResume,
	}
	addRegistryFlags(cmd)
	return cmd
}

func runRegistryResume(cmd *cobra.Command, args []string) error {
	registryURL, client, err := resolveRegistry(cmd)
	if err != nil {
		return err
	}
	st, err := postDrain(client, registryURL, http.MethodDelete)
	if err != nil {
		return err
	}
	out := cmd.OutOrStdout()
	fmt.Fprintln(out, "Registry resumed — job dispatch active")
	fmt.Fprintf(out, "  Live claims: %d\n", st.LiveClaims)
	return nil
}

func newRegistryStatusCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show registry drain state and live-claim count",
		Long: `Report whether the registry is draining and how many live claims remain
(non-terminal jobs with an owner).

Examples:
  meshctl registry status
  meshctl registry status --json`,
		Args: cobra.NoArgs,
		RunE: runRegistryStatus,
	}
	addRegistryFlags(cmd)
	cmd.Flags().Bool("json", false, "Output raw JSON from registry")
	return cmd
}

func runRegistryStatus(cmd *cobra.Command, args []string) error {
	registryURL, client, err := resolveRegistry(cmd)
	if err != nil {
		return err
	}
	jsonOut, _ := cmd.Flags().GetBool("json")

	endpoint := strings.TrimRight(registryURL, "/") + "/admin/drain"
	resp, err := client.Get(endpoint)
	if err != nil {
		return fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return drainHTTPError(resp.StatusCode, body)
	}

	if jsonOut {
		fmt.Fprintln(cmd.OutOrStdout(), string(body))
		return nil
	}

	var st drainState
	if err := json.Unmarshal(body, &st); err != nil {
		return fmt.Errorf("failed to parse drain status: %w", err)
	}
	out := cmd.OutOrStdout()
	mode := "active (normal dispatch)"
	if st.Draining {
		mode = "DRAINING (new claims paused)"
	}
	fmt.Fprintf(out, "Registry:    %s\n", mode)
	fmt.Fprintf(out, "Live claims: %d\n", st.LiveClaims)
	return nil
}

// postDrain sends POST/DELETE to /admin/drain and decodes the drain state.
func postDrain(client *http.Client, registryURL, method string) (*drainState, error) {
	endpoint := strings.TrimRight(registryURL, "/") + "/admin/drain"
	req, err := http.NewRequest(method, endpoint, nil)
	if err != nil {
		return nil, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return nil, drainHTTPError(resp.StatusCode, body)
	}
	var st drainState
	if err := json.Unmarshal(body, &st); err != nil {
		return nil, fmt.Errorf("failed to parse drain response: %w", err)
	}
	return &st, nil
}

// drainHTTPError formats a non-200 /admin/drain response. A 404 usually means
// the registry runs a separate admin port (MCP_MESH_ADMIN_PORT), where the
// admin endpoints live only on that port — so we hint the operator to retarget.
func drainHTTPError(status int, body []byte) error {
	if status == http.StatusNotFound {
		return fmt.Errorf("registry returned status 404: %s\n"+
			"hint: if the registry runs a separate admin port, pass --registry-url http://<host>:<admin-port>",
			strings.TrimSpace(string(body)))
	}
	return fmt.Errorf("registry returned status %d: %s", status, string(body))
}

// getDrain reads the current drain state via GET /admin/drain.
func getDrain(client *http.Client, registryURL string) (*drainState, error) {
	endpoint := strings.TrimRight(registryURL, "/") + "/admin/drain"
	resp, err := client.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return nil, drainHTTPError(resp.StatusCode, body)
	}
	var st drainState
	if err := json.Unmarshal(body, &st); err != nil {
		return nil, fmt.Errorf("failed to parse drain status: %w", err)
	}
	return &st, nil
}
