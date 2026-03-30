package cli

import (
	"fmt"
	"os/exec"
	"runtime"

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
