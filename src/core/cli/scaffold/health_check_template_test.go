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
