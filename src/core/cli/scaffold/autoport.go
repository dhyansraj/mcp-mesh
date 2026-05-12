package scaffold

import "github.com/spf13/cobra"

// AutoAssignScaffoldPort returns the port to use for a newly-scaffolded
// agent. If the user explicitly passed --port (Flag.Changed), the supplied
// value is returned unchanged. Otherwise the output directory is scanned
// for previously-scaffolded agents and the next free port is returned
// (max(detected_ports)+1, or DefaultScaffoldPort if none found).
//
// A small log line is emitted on the cobra command's stdout whenever the
// auto-assigned port differs from DefaultScaffoldPort, so users can see
// what happened.
//
// agentName is used only for the log line ("using N for <name>"); it can be
// empty.
//
// See issue #957 (fix 2).
func AutoAssignScaffoldPort(cmd *cobra.Command, requestedPort int, outputDir, agentName string) int {
	if cmd != nil {
		if flag := cmd.Flags().Lookup("port"); flag != nil && flag.Changed {
			return requestedPort
		}
	}
	next := NextAvailablePort(outputDir)
	if next != DefaultScaffoldPort && cmd != nil {
		label := agentName
		if label == "" {
			label = "new agent"
		}
		cmd.Printf("Detected existing agent on port %d; using %d for %s\n",
			next-1, next, label)
	}
	return next
}
