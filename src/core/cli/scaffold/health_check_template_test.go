package scaffold

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

// The llm-provider health check exists so a provider can WITHDRAW itself
// while its vendor is down (issues #1472/#1474/#1476). Only an "unhealthy"
// verdict suppresses the heartbeat, and the Python and Java templates both
// shipped this INVERTED once — "unhealthy" for a missing API key but
// "degraded" for an actual outage — which compiled, passed review, and left
// every scaffolded provider unable to withdraw itself. That is exactly the
// regression these tests exist to catch.
//
// The probe body is hand-duplicated nine times (three runtimes x three
// vendors), so the guard runs the whole matrix: a fix applied to the
// anthropic copy and forgotten in the openai one is the likeliest way this
// regresses.
//
// The assertions are on the rendered BRANCH, not on the file as a whole: a
// template that says "unhealthy" somewhere while returning "degraded" for a
// 503 would still be broken.
//
// There is deliberately no "a cancelled probe is degraded" guard. The
// templates create no AbortController and no interrupt of their own except
// Java's, so on Python and TypeScript a cancel branch would be unreachable
// code — `AbortSignal.timeout` rejects with a "TimeoutError", which is a
// transport failure and belongs in the unhealthy branch asserted below.

func templatesRoot(t *testing.T) string {
	t.Helper()
	root := filepath.Join(getProjectRoot(), "cmd", "meshctl", "templates")
	_, err := os.Stat(root)
	// Not a skip: a guard that quietly does nothing when the templates move
	// is worse than no guard, because the suite still reports green.
	require.NoError(t, err, "templates not found at %s", root)
	return root
}

// renderProvider scaffolds an llm-provider agent and returns its entry file.
func renderProvider(t *testing.T, language, model, entry string) string {
	t.Helper()
	ctx := &ScaffoldContext{
		Name:        "verdict-probe",
		Description: "verdict probe",
		Language:    language,
		OutputDir:   t.TempDir(),
		Port:        9400,
		Model:       model,
		Template:    "llm-provider",
		TemplateDir: templatesRoot(t),
	}
	require.NoError(t, NewStaticProvider().Execute(ctx))

	path := filepath.Join(ctx.OutputDir, ctx.Name, entry)
	content, err := os.ReadFile(path)
	require.NoError(t, err, "rendered entry file %s", path)
	return string(content)
}

// section returns the text between marker and the next occurrence of end,
// so an assertion can target one branch instead of the whole file.
//
// A missing end marker FAILS rather than returning the rest of the file: a
// template refactor that drops one would otherwise widen the assertion
// window until it matched some other branch's verdict and passed for the
// wrong reason.
func section(t *testing.T, content, marker, end string) string {
	t.Helper()
	start := strings.Index(content, marker)
	require.GreaterOrEqual(t, start, 0, "marker %q not found in rendered output", marker)
	rest := content[start:]
	stop := strings.Index(rest[len(marker):], end)
	require.GreaterOrEqual(t, stop, 0,
		"end marker %q not found after %q — the branch boundary moved, and "+
			"without it this assertion would silently cover the whole file", end, marker)
	return rest[:len(marker)+stop]
}

// Entry file for a Java agent named "verdict-probe": the scaffolder derives
// the package (com.example.verdictprobe) and the class name from the name.
var javaEntry = filepath.Join(
	"src", "main", "java", "com", "example", "verdictprobe", "VerdictProbeApplication.java")

// The comments opening each branch are identical across the three runtimes
// on purpose — they are what makes this guard a matrix rather than nine
// hand-written cases.
const (
	outageMarker    = "vendor answered and it is not serving"
	transportMarker = "The vendor is not answering at all"
)

// One runtime's rendering of the shared probe.
type runtimeProbe struct {
	language string
	entry    string
	// Where the vendor-outage branch ends.
	outageEnd string
	// Where the transport-failure branch ends.
	transportEnd string
	// The verdict both branches must produce.
	wantVerdict string
	// A verdict that would silently disable withdrawal.
	bannedVerdict string
	// Text proving the check is actually wired to the agent.
	wiring []string
}

var runtimeProbes = []runtimeProbe{
	{
		language:      "python",
		entry:         "main.py",
		outageEnd:     "except Exception",
		transportEnd:  "return {",
		wantVerdict:   `status = "unhealthy"`,
		bannedVerdict: `status = "degraded"`,
		wiring:        []string{"health_check=health_check", "health_check_ttl="},
	},
	{
		language:      "typescript",
		entry:         filepath.Join("src", "index.ts"),
		outageEnd:     "} catch (err)",
		transportEnd:  "}\n}",
		wantVerdict:   `status: "unhealthy"`,
		bannedVerdict: `status: "degraded"`,
		wiring:        []string{"  healthCheck,", "healthCheckTtl:"},
	},
	{
		language: "java",
		entry:    javaEntry,
		// Java's transport branch is the LAST catch, after the
		// InterruptedException one that is legitimately degraded.
		outageEnd:     "catch (InterruptedException",
		transportEnd:  "\n    }",
		wantVerdict:   "MeshHealthStatus.UNHEALTHY",
		bannedVerdict: "MeshHealthStatus.DEGRADED",
		wiring:        []string{"@MeshHealthCheck(ttlSeconds ="},
	},
}

// The vendors every runtime ships a real probe for. Anything else gets the
// skeleton asserted by TestLlmProviderTemplates_UnknownVendorSkeletonWarns.
var probeVendors = []struct {
	name  string
	model string
}{
	{"anthropic", "anthropic/claude-sonnet-5"},
	{"openai", "openai/gpt-4o"},
	{"gemini", "gemini/gemini-2.5-flash"},
}

// A vendor that answers with a non-200 is an OUTAGE: the branch must report
// unhealthy so the heartbeat stops and consumers fail over.
func TestLlmProviderTemplates_VendorOutageIsUnhealthy(t *testing.T) {
	for _, rt := range runtimeProbes {
		for _, vendor := range probeVendors {
			t.Run(rt.language+" "+vendor.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, vendor.model, rt.entry)
				branch := section(t, content, outageMarker, rt.outageEnd)

				require.Contains(t, branch, rt.wantVerdict,
					"a vendor that answers with a non-200 is an OUTAGE: the branch must "+
						"report unhealthy so the heartbeat stops and consumers fail over")
				require.NotContains(t, branch, rt.bannedVerdict,
					"reporting degraded on a real outage keeps the heartbeat alive and "+
						"makes the provider unable to withdraw itself — the whole point "+
						"of the health check")
			})
		}
	}
}

// The transport-failure branch (DNS, connect, timeout, TLS) is the other
// half of the same contract: the vendor is not answering at all.
func TestLlmProviderTemplates_TransportFailureIsUnhealthy(t *testing.T) {
	for _, rt := range runtimeProbes {
		for _, vendor := range probeVendors {
			t.Run(rt.language+" "+vendor.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, vendor.model, rt.entry)
				branch := section(t, content, transportMarker, rt.transportEnd)

				require.Contains(t, branch, rt.wantVerdict,
					"a vendor that does not answer at all is an OUTAGE: the branch must "+
						"report unhealthy so the heartbeat stops and consumers fail over")
				require.NotContains(t, branch, rt.bannedVerdict,
					"reporting degraded when the vendor is unreachable keeps the "+
						"heartbeat alive and makes the provider unable to withdraw itself")
			})
		}
	}
}

// The scaffolded agent must actually WIRE the check up — a correct
// healthCheck that nothing calls withdraws nothing.
func TestLlmProviderTemplates_HealthCheckIsWired(t *testing.T) {
	for _, rt := range runtimeProbes {
		for _, vendor := range probeVendors {
			t.Run(rt.language+" "+vendor.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, vendor.model, rt.entry)
				for _, marker := range rt.wiring {
					require.Contains(t, content, marker,
						"the health check is declared but never handed to the agent, so "+
							"nothing ever runs it")
				}
			})
		}
	}
}

// An unknown vendor gets a skeleton that cannot detect an outage. That is
// unavoidable — there is no generic reachability probe — but it must say so
// loudly rather than look finished.
func TestLlmProviderTemplates_UnknownVendorSkeletonWarns(t *testing.T) {
	for _, rt := range runtimeProbes {
		t.Run(rt.language, func(t *testing.T) {
			content := renderProvider(t, rt.language, "cohere/command-r-plus", rt.entry)
			require.Contains(t, content, "CANNOT DETECT AN")
			require.Contains(t, content, "NOT IMPLEMENTED")
		})
	}
}

// Issue #1479. A gateway-prefixed model reaches a big-3 model through someone
// else's endpoint, with someone else's credentials: `bedrock/anthropic.claude-*`
// is served by AWS, `vertex_ai/gemini-*` by a Google Cloud project under ADC /
// Workload Identity. The templates used to select the probe with a
// case-sensitive substring test, so both strings selected a direct vendor probe
// gated on an API key those deployments never set.
//
// That is not cosmetic. The probe reports unhealthy on its first tick, which
// suppresses the heartbeat, and the registry withdraws an agent that is serving
// fine — permanently, because the missing key never appears. Falling through to
// the skeleton leaves the operator with a TODO; guessing a probe takes their
// working provider off the mesh.
//
// Uppercase is in the matrix because --model is free-form and the old gate was
// case-sensitive: a resolver that lowercases one side only would pass the two
// lowercase cases and still ship the bug.
var gatewayModels = []struct {
	name string
	// The probe that must NOT be selected, and the credential that proves it.
	model     string
	bannedAPI string
	bannedKey string
}{
	{
		name:      "bedrock claude",
		model:     "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
		bannedAPI: "api.anthropic.com",
		bannedKey: "ANTHROPIC_API_KEY",
	},
	{
		name:      "vertex gemini",
		model:     "vertex_ai/gemini-2.5-flash",
		bannedAPI: "generativelanguage.googleapis.com",
		bannedKey: "GOOGLE_API_KEY",
	},
	{
		name:      "vertex gemini uppercase",
		model:     "VERTEX_AI/gemini-2.5-flash",
		bannedAPI: "generativelanguage.googleapis.com",
		bannedKey: "GOOGLE_API_KEY",
	},
	{
		name:      "databricks claude",
		model:     "databricks/anthropic.claude-3-7-sonnet",
		bannedAPI: "api.anthropic.com",
		bannedKey: "ANTHROPIC_API_KEY",
	},
}

func TestLlmProviderTemplates_GatewayModelGetsSkeletonNotVendorProbe(t *testing.T) {
	for _, rt := range runtimeProbes {
		for _, gw := range gatewayModels {
			t.Run(rt.language+" "+gw.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, gw.model, rt.entry)

				require.Contains(t, content, "NOT IMPLEMENTED",
					"a gateway-prefixed model has no probeable direct vendor API, so "+
						"the skeleton is the only honest rendering")
				require.Contains(t, content, "CANNOT DETECT AN")

				require.NotContains(t, content, gw.bannedAPI,
					"%s is served by its gateway, not by %s — probing that endpoint "+
						"reports on an API this agent never calls", gw.model, gw.bannedAPI)
				require.NotContains(t, content, gw.bannedKey,
					"%s never sets %s, so a check gated on it returns unhealthy "+
						"forever and the registry withdraws a working provider",
					gw.model, gw.bannedKey)
			})
		}
	}
}

// The same defect sat on the tags and the README env-var instructions. They do
// not withdraw anything, but leaving one `contains` beside the fixed probe is
// how this class of bug survives, so one resolver governs all of them.
func TestLlmProviderTemplates_GatewayModelGetsGenericTagsAndReadme(t *testing.T) {
	tagsMarker := map[string]string{
		"python":     `tags=["llm", "provider"]`,
		"typescript": `tags: ["llm", "provider"]`,
		"java":       `tags = {"llm", "provider"}`,
	}

	for _, rt := range runtimeProbes {
		for _, gw := range gatewayModels {
			t.Run(rt.language+" "+gw.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, gw.model, rt.entry)
				require.Contains(t, content, tagsMarker[rt.language],
					"a gateway model must not advertise the underlying vendor's tags")

				readme := renderProvider(t, rt.language, gw.model, "README.md")
				require.NotContains(t, readme, "export "+gw.bannedKey,
					"the README tells the operator to export a key the gateway "+
						"does not use")
			})
		}
	}
}

// The big-3 matrix is the other half: narrowing the gate must not have taken
// the real probes with it.
func TestLlmProviderTemplates_BareBig3NameStillProbes(t *testing.T) {
	bare := []struct {
		model     string
		wantAPI   string
		wantKey   string
		wantTagIn string
	}{
		{"claude-sonnet-5", "api.anthropic.com", "ANTHROPIC_API_KEY", "anthropic"},
		{"gpt-4o", "api.openai.com", "OPENAI_API_KEY", "openai"},
		{"gemini-2.5-flash", "generativelanguage.googleapis.com", "GOOGLE_API_KEY", "gemini"},
	}

	for _, rt := range runtimeProbes {
		for _, b := range bare {
			t.Run(rt.language+" "+b.model, func(t *testing.T) {
				content := renderProvider(t, rt.language, b.model, rt.entry)
				require.Contains(t, content, b.wantAPI)
				require.Contains(t, content, b.wantKey)
				require.Contains(t, content, b.wantTagIn)
				require.NotContains(t, content, "NOT IMPLEMENTED",
					"an unprefixed big-3 name is probeable and must get the real probe")
			})
		}
	}
}
