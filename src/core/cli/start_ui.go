package cli

import (
	"fmt"
	"os/exec"

	"github.com/spf13/cobra"
)

// maybeStartUIServer starts the UI server if --ui flag is set
func maybeStartUIServer(cmd *cobra.Command, config *CLIConfig, registryURL string) {
	startUI, _ := cmd.Flags().GetBool("ui")
	if !startUI {
		return
	}

	quiet, _ := cmd.Flags().GetBool("quiet")
	uiPort, _ := cmd.Flags().GetInt("ui-port")
	openDashboard, _ := cmd.Flags().GetBool("dashboard")

	pm := GetGlobalProcessManager()

	processInfo, err := pm.StartUIProcess(uiPort, registryURL, config.DBPath)
	if err != nil {
		if !quiet {
			fmt.Printf("Warning: failed to start UI server: %v\n", err)
		}
		return
	}

	actualPort := uiPort
	if actualPort == 0 {
		actualPort = 3080
	}

	if !quiet {
		fmt.Printf("Dashboard UI available at http://localhost:%d\n", actualPort)
	}

	// Write PID file for UI process
	pidMgr, pidErr := NewPIDManager()
	if pidErr == nil {
		if err := pidMgr.WritePID("ui", processInfo.PID); err != nil && !quiet {
			fmt.Printf("Warning: could not write UI PID file: %v\n", err)
		}
	}

	// Open browser if --dashboard flag is set
	if openDashboard {
		openBrowser(fmt.Sprintf("http://localhost:%d", actualPort))
	}
}

// openBrowser opens the default browser on macOS/Linux
func openBrowser(url string) {
	// Use "open" on macOS, "xdg-open" on Linux
	if err := exec.Command("open", url).Start(); err != nil {
		// Fallback for Linux
		exec.Command("xdg-open", url).Start()
	}
}
