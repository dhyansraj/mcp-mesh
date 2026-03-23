package cli

import (
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"mcp-mesh/src/core/cli/handlers"
)

// createJavaWatcher creates an AgentWatcher for a Java Maven project
func createJavaWatcher(agentPath string, env []string, workingDir, user, group string, quiet bool) (*AgentWatcher, error) {
	// Resolve project root
	projectDir := agentPath
	if info, err := os.Stat(agentPath); err == nil && !info.IsDir() {
		projectDir = filepath.Dir(agentPath)
	}
	absProjectDir, err := filepath.Abs(projectDir)
	if err != nil {
		return nil, fmt.Errorf("failed to get absolute path for %s: %w", projectDir, err)
	}
	javaHandler := &handlers.JavaHandler{}
	projectRoot, err := javaHandler.FindProjectRoot(absProjectDir)
	if err != nil {
		return nil, fmt.Errorf("cannot find Maven project: %w", err)
	}

	finalWorkingDir := projectRoot
	if workingDir != "" {
		absWorkingDir, err := AbsolutePath(workingDir)
		if err != nil {
			return nil, fmt.Errorf("invalid working directory: %w", err)
		}
		finalWorkingDir = absWorkingDir
	}

	// Add Java-specific environment variables
	javaEnv := []string{
		"SPRING_MAIN_BANNER_MODE=off",
	}
	fullEnv := append(env, javaEnv...)

	// Build command factory - creates a fresh cmd each restart
	cmdFactory := func() *exec.Cmd {
		cmd := exec.Command("mvn", "spring-boot:run", "-q")
		cmd.Env = fullEnv
		cmd.Dir = finalWorkingDir
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Stdin = os.Stdin
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
		// Set user/group if specified
		if user != "" || group != "" {
			if err := setProcessCredentials(cmd, user, group); err != nil {
				fmt.Fprintf(os.Stderr, "Warning: failed to set process credentials for watcher: %v\n", err)
			}
		}
		return cmd
	}

	watchDir := filepath.Join(projectRoot, "src")
	// If src directory doesn't exist, watch the project root
	if _, err := os.Stat(watchDir); os.IsNotExist(err) {
		watchDir = projectRoot
	}

	config := WatchConfig{
		ProjectRoot:   projectRoot,
		WatchDir:      watchDir,
		Extensions:    []string{".java", ".yml", ".yaml", ".properties", ".xml"},
		ExcludeDirs:   []string{"target", ".git", ".idea", "node_modules", ".mvn"},
		DebounceDelay: getWatchDebounceDelay(),
		PortDelay:     getWatchPortDelay(),
		StopTimeout:   3 * time.Second,
		AgentName:     filepath.Base(projectRoot),
	}

	// Pre-restart compile check: validate code compiles before killing agent
	if getWatchPrecheckEnabled() {
		compileProjectRoot := projectRoot
		compileEnv := fullEnv
		config.PreRestartCheck = func() error {
			cmd := exec.Command("mvn", "compile", "-q", "-o") // -q quiet, -o offline (deps already fetched)
			cmd.Dir = compileProjectRoot
			cmd.Env = compileEnv
			output, err := cmd.CombinedOutput()
			if err != nil {
				return fmt.Errorf("maven compile failed:\n%s", string(output))
			}
			return nil
		}
	}

	return NewAgentWatcher(config, cmdFactory, quiet), nil
}

// createPythonWatcher creates an AgentWatcher for a Python agent
func createPythonWatcher(agentPath string, env []string, workingDir, user, group string, quiet bool) (*AgentWatcher, error) {
	// Create the non-watch command to get all the resolved paths and env
	// We pass watch=false to get the plain python command
	templateCmd, err := createPythonAgentCommand(agentPath, env, workingDir, user, group, false)
	if err != nil {
		return nil, err
	}

	// Extract the resolved values from the template command
	resolvedEnv := templateCmd.Env
	resolvedDir := templateCmd.Dir
	resolvedArgs := templateCmd.Args // e.g., ["/path/to/python", "/path/to/script.py"]

	// Build command factory
	cmdFactory := func() *exec.Cmd {
		cmd := exec.Command(resolvedArgs[0], resolvedArgs[1:]...)
		cmd.Env = resolvedEnv
		cmd.Dir = resolvedDir
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Stdin = os.Stdin
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
		if user != "" || group != "" {
			if err := setProcessCredentials(cmd, user, group); err != nil {
				fmt.Fprintf(os.Stderr, "Warning: failed to set process credentials for watcher: %v\n", err)
			}
		}
		return cmd
	}

	// Watch the script's parent directory (same as Python reload.py does)
	watchDir := resolvedDir

	config := WatchConfig{
		ProjectRoot:   resolvedDir,
		WatchDir:      watchDir,
		Extensions:    []string{".py", ".jinja2", ".j2", ".yaml", ".yml"},
		ExcludeDirs:   []string{"__pycache__", ".git", ".venv", "venv", ".pytest_cache", ".mypy_cache", "node_modules", ".eggs", ".egg-info"},
		DebounceDelay: getWatchDebounceDelay(),
		PortDelay:     getWatchPortDelay(),
		StopTimeout:   3 * time.Second,
		AgentName:     extractAgentName(agentPath),
	}

	// Pre-restart syntax check: validate Python files have no syntax errors before killing agent
	if getWatchPrecheckEnabled() {
		pythonCmd := resolvedArgs[0] // python executable path
		checkDir := resolvedDir
		excludeDirs := config.ExcludeDirs
		config.PreRestartCheck = func() error {
			var errors []string
			filepath.WalkDir(checkDir, func(path string, d fs.DirEntry, err error) error {
				if err != nil {
					return nil
				}
				if d.IsDir() {
					basename := filepath.Base(path)
					for _, excl := range excludeDirs {
						if basename == excl {
							return filepath.SkipDir
						}
					}
					return nil
				}
				if filepath.Ext(path) != ".py" {
					return nil
				}
				cmd := exec.Command(pythonCmd, "-m", "py_compile", path)
				if output, err := cmd.CombinedOutput(); err != nil {
					errors = append(errors, fmt.Sprintf("%s: %s", path, string(output)))
				}
				return nil
			})
			if len(errors) > 0 {
				return fmt.Errorf("python syntax errors:\n%s", strings.Join(errors, "\n"))
			}
			return nil
		}
	}

	return NewAgentWatcher(config, cmdFactory, quiet), nil
}
