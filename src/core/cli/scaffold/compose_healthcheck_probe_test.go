package scaffold

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	"gopkg.in/yaml.v3"
)

// Issue #1490. A generated agent healthcheck must probe /livez, never /health.
//
// A container-level health signal should mean "this process is serving", not
// "everything it depends on is reachable". /health carries the health-check
// verdict and answers 503 while a dependency (an LLM vendor, say) is down, so
// probing it there has two real consequences in plain Compose:
//
//   - `depends_on: condition: service_healthy` BLOCKS dependents. One agent
//     whose vendor is down stops unrelated agents from starting.
//   - `docker compose ps` reports a live, serving process as unhealthy, so the
//     signal operators triage from is wrong.
//
// It does NOT restart the container: `restart:` acts on process exit, not on
// health status — verified with `--restart unless-stopped --health-cmd 'exit
// 1'`, which sat unhealthy with zero restarts. Only Swarm reschedules unhealthy
// tasks, and autoheal sidecars do it explicitly. Do not reintroduce the restart
// claim; it was in the first draft of this fix and in issue #1490, and it is
// wrong for the runtime the scaffolder targets.
//
// Compose has one healthcheck per service, so it cannot carry both meanings the
// way k8s splits liveness (#1468) from readiness; "is it serving" wins, and
// real readiness gating is the thing that gives.
//
// The healthcheck line is hand-duplicated SIX times — three runtimes across two
// templates (`agentServicesTemplate`, used when merging into an existing
// compose file, and `composeTemplate`, used for a fresh one). A revert of a
// single copy is the likeliest regression, so this guard renders through BOTH
// paths for all three languages and names the path and language that failed.
//
// The registry is asserted to still probe /health on purpose: its handler is a
// static 200 that consults nothing, which is why the registry chart keeps both
// probes there. A sweeping s/health/livez/ across this file would break it, and
// the registry serves no /livez at all.

type composeHealthcheck struct {
	Test []string `yaml:"test"`
}

type composeService struct {
	Healthcheck composeHealthcheck `yaml:"healthcheck"`
}

type composeDoc struct {
	Services map[string]composeService `yaml:"services"`
}

// probeAgents is the agent set every render in this file uses: one per
// runtime, so a single render covers all three per-language template branches.
var probeAgents = []DetectedAgent{
	{Name: "probe-python", Port: 9401, Dir: "probe-python", Language: "python"},
	{Name: "probe-typescript", Port: 9402, Dir: "probe-typescript", Language: "typescript"},
	{Name: "probe-java", Port: 9403, Dir: "probe-java", Language: "java"},
}

// parseCompose reads the generated docker-compose.yml and returns its services.
func parseCompose(t *testing.T, dir string) composeDoc {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir, "docker-compose.yml"))
	require.NoError(t, err, "generated compose file")

	var doc composeDoc
	require.NoError(t, yaml.Unmarshal(raw, &doc), "generated compose is not valid YAML")
	require.NotEmpty(t, doc.Services, "generated compose has no services")
	return doc
}

// renderFreshCompose renders through composeTemplate (no pre-existing file).
func renderFreshCompose(t *testing.T, observability bool) composeDoc {
	t.Helper()
	dir := t.TempDir()
	_, err := GenerateDockerCompose(&ComposeConfig{
		Agents:        probeAgents,
		Observability: observability,
		ProjectName:   "probe-project",
	}, dir)
	require.NoError(t, err)
	return parseCompose(t, dir)
}

// renderMergedCompose renders through agentServicesTemplate by seeding a
// compose file the generator has to merge into.
func renderMergedCompose(t *testing.T) composeDoc {
	t.Helper()
	dir := t.TempDir()
	existing := `services:
  postgres:
    image: postgres:15-alpine
  registry:
    image: mcpmesh/registry:latest
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8000/health"]
networks:
  probe-network:
    driver: bridge
`
	require.NoError(t, os.WriteFile(
		filepath.Join(dir, "docker-compose.yml"), []byte(existing), 0644))

	result, err := GenerateDockerCompose(&ComposeConfig{
		Agents:      probeAgents,
		ProjectName: "probe-project",
		NetworkName: "probe-network",
	}, dir)
	require.NoError(t, err)
	require.True(t, result.WasMerged,
		"this case must exercise the MERGE path (agentServicesTemplate); a fresh "+
			"render here would leave three of the six healthcheck copies unguarded")
	return parseCompose(t, dir)
}

// assertAgentProbesLivez checks one agent service in one rendered document.
func assertAgentProbesLivez(t *testing.T, site string, svc composeService, port int) {
	t.Helper()
	probe := strings.Join(svc.Healthcheck.Test, " ")

	require.NotEmpty(t, svc.Healthcheck.Test,
		"%s: the agent service has no healthcheck at all — an assertion that it "+
			"does not probe /health would pass for the wrong reason", site)
	require.NotContains(t, probe, "/health",
		"%s: the agent healthcheck probes /health, which answers 503 on a "+
			"dependency outage. That marks a live, serving agent unhealthy: it "+
			"blocks every dependent gated on depends_on: service_healthy and "+
			"misreports the agent in docker compose ps. Probe /livez, which "+
			"answers 200 while the process serves (#1490).", site)
	require.Contains(t, probe, fmt.Sprintf("localhost:%d/livez", port),
		"%s: the agent healthcheck must probe /livez on the agent's own port", site)
}

// Every agent service, in every render path, probes /livez and nothing else.
func TestComposeHealthchecks_AgentsProbeLivez(t *testing.T) {
	paths := []struct {
		name   string
		render func(t *testing.T) composeDoc
	}{
		{"fresh", func(t *testing.T) composeDoc { return renderFreshCompose(t, false) }},
		{"fresh+observability", func(t *testing.T) composeDoc { return renderFreshCompose(t, true) }},
		{"merged", renderMergedCompose},
	}

	for _, path := range paths {
		t.Run(path.name, func(t *testing.T) {
			doc := path.render(t)
			for _, agent := range probeAgents {
				t.Run(agent.Language, func(t *testing.T) {
					svc, ok := doc.Services[agent.Name]
					require.True(t, ok,
						"%s/%s: no service was rendered for this agent, so its "+
							"healthcheck is unguarded", path.name, agent.Language)
					assertAgentProbesLivez(t,
						path.name+"/"+agent.Language, svc, agent.Port)
				})
			}
		})
	}
}

// The registry keeps /health: its handler is a static 200 that consults
// nothing, and it serves no /livez. This is the counterweight to the test
// above — it fails a blanket search-and-replace.
func TestComposeHealthchecks_RegistryKeepsHealth(t *testing.T) {
	doc := renderFreshCompose(t, false)

	registry, ok := doc.Services["registry"]
	require.True(t, ok, "no registry service was rendered")
	probe := strings.Join(registry.Healthcheck.Test, " ")
	require.Contains(t, probe, "localhost:8000/health",
		"the registry healthcheck must stay on /health: its handler is a static "+
			"200 that consults nothing, and the registry serves no /livez")
}
