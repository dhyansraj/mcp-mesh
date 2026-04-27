package cli

import (
	"fmt"
	"os/exec"
	"runtime"

	"github.com/spf13/cobra"

	"mcp-mesh/src/core/cli/lifecycle"
)

// maybeStartUIServer starts the UI server if --ui flag is set.
//
// The protocol-driven check (IsUIRunning) takes precedence over the
// in-process map maintained by ProcessManager — if some other meshctl
// invocation already started the UI on the requested port, we just write
// our deps under that running UI's PID file (handled by the caller via
// registerInvocationDeps) and return without spawning a duplicate.
//
// Bracketed in lifecycle.WithStartLock(ServiceUI, ...) so concurrent
// meshctl invocations racing to start the UI cleanly serialize: only one
// wins the spawn, others see the now-running UI and reuse it.
func maybeStartUIServer(cmd *cobra.Command, config *CLIConfig, registryURL string) {
	startUI, _ := cmd.Flags().GetBool("ui")
	if !startUI {
		return
	}

	quiet, _ := cmd.Flags().GetBool("quiet")
	uiPort, _ := cmd.Flags().GetInt("ui-port")
	openDashboard, _ := cmd.Flags().GetBool("dashboard")

	_ = lifecycle.WithStartLock(lifecycle.ServiceUI, func() error {
		// Re-check inside the lock so the loser of the race takes the reuse
		// branch instead of double-starting.
		if IsUIRunning(uiPort) {
			actualPort := uiPort
			if actualPort == 0 {
				actualPort = 3080
			}
			if !quiet {
				fmt.Printf("UI server already running at http://localhost:%d (reusing)\n", actualPort)
			}
			if openDashboard {
				openBrowser(fmt.Sprintf("http://localhost:%d", actualPort))
			}
			return nil
		}

		pm := GetGlobalProcessManager()
		processInfo, err := pm.StartUIProcess(uiPort, registryURL, config.DBPath)
		if err != nil {
			fmt.Printf("Warning: failed to start UI server: %v\n", err)
			fmt.Println("Agents and registry will continue without the dashboard")
			return nil
		}

		actualPort := uiPort
		if actualPort == 0 {
			actualPort = 3080
		}

		if !quiet {
			fmt.Printf("Dashboard UI available at http://localhost:%d\n", actualPort)
			fmt.Printf("Dashboard logs: ~/.mcp-mesh/logs/meshui.log\n")
		}

		// Write UI PID file via lifecycle (canonical writer for service PIDs).
		if err := lifecycle.WriteService(lifecycle.ServiceUI, processInfo.PID); err != nil && !quiet {
			fmt.Printf("Warning: could not write UI PID file: %v\n", err)
		}

		if openDashboard {
			openBrowser(fmt.Sprintf("http://localhost:%d", actualPort))
		}
		return nil
	})
}

// openBrowser opens the default browser to the given URL
func openBrowser(url string) {
	var cmd string
	var args []string

	switch runtime.GOOS {
	case "darwin":
		cmd = "open"
		args = []string{url}
	case "linux":
		cmd = "xdg-open"
		args = []string{url}
	case "windows":
		cmd = "rundll32"
		args = []string{"url.dll,FileProtocolHandler", url}
	default:
		fmt.Printf("Open %s in your browser\n", url)
		return
	}

	if err := exec.Command(cmd, args...).Start(); err != nil {
		fmt.Printf("Could not open browser: %v\nOpen %s manually\n", err, url)
	}
}
