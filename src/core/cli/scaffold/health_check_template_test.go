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
// regression these tests exist to catch, in all three runtimes at once.
//
// The assertions are on the rendered vendor-outage BRANCH, not on the file
// as a whole: a template that says "unhealthy" somewhere while returning
// "degraded" for a 503 would still be broken.

func templatesRoot(t *testing.T) string {
	t.Helper()
	root := filepath.Join(getProjectRoot(), "cmd", "meshctl", "templates")
	if _, err := os.Stat(root); err != nil {
		t.Skipf("templates not found at %s", root)
	}
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
func section(t *testing.T, content, marker, end string) string {
	t.Helper()
	start := strings.Index(content, marker)
	require.GreaterOrEqual(t, start, 0, "marker %q not found in rendered output", marker)
	rest := content[start:]
	if stop := strings.Index(rest, end); stop > 0 {
		return rest[:stop]
	}
	return rest
}

// Entry file for a Java agent named "verdict-probe": the scaffolder derives
// the package (com.example.verdictprobe) and the class name from the name.
var javaEntry = filepath.Join(
	"src", "main", "java", "com", "example", "verdictprobe", "VerdictProbeApplication.java")

func TestLlmProviderTemplates_VendorOutageIsUnhealthy(t *testing.T) {
	cases := []struct {
		name     string
		language string
		model    string
		entry    string
		// Text opening the "vendor answered, and it is not serving" branch.
		outageMarker string
		// Where that branch ends.
		outageEnd string
		// The verdict the branch must produce.
		wantVerdict string
		// A verdict that would silently disable withdrawal.
		bannedVerdict string
	}{
		{
			name:          "python anthropic",
			language:      "python",
			model:         "anthropic/claude-sonnet-5",
			entry:         "main.py",
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "except Exception",
			wantVerdict:   `status = "unhealthy"`,
			bannedVerdict: `status = "degraded"`,
		},
		{
			name:          "python openai",
			language:      "python",
			model:         "openai/gpt-4o",
			entry:         "main.py",
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "except Exception",
			wantVerdict:   `status = "unhealthy"`,
			bannedVerdict: `status = "degraded"`,
		},
		{
			name:          "python gemini",
			language:      "python",
			model:         "gemini/gemini-2.5-flash",
			entry:         "main.py",
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "except Exception",
			wantVerdict:   `status = "unhealthy"`,
			bannedVerdict: `status = "degraded"`,
		},
		{
			name:          "typescript anthropic",
			language:      "typescript",
			model:         "anthropic/claude-sonnet-5",
			entry:         filepath.Join("src", "index.ts"),
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "} catch (err)",
			wantVerdict:   `status: "unhealthy"`,
			bannedVerdict: `status: "degraded"`,
		},
		{
			name:          "typescript openai",
			language:      "typescript",
			model:         "openai/gpt-4o",
			entry:         filepath.Join("src", "index.ts"),
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "} catch (err)",
			wantVerdict:   `status: "unhealthy"`,
			bannedVerdict: `status: "degraded"`,
		},
		{
			name:          "typescript gemini",
			language:      "typescript",
			model:         "gemini/gemini-2.5-flash",
			entry:         filepath.Join("src", "index.ts"),
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "} catch (err)",
			wantVerdict:   `status: "unhealthy"`,
			bannedVerdict: `status: "degraded"`,
		},
		{
			name:          "java anthropic",
			language:      "java",
			model:         "anthropic/claude-sonnet-5",
			entry:         javaEntry,
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "catch (InterruptedException",
			wantVerdict:   "MeshHealthStatus.UNHEALTHY",
			bannedVerdict: "MeshHealthStatus.DEGRADED",
		},
		{
			name:          "java openai",
			language:      "java",
			model:         "openai/gpt-4o",
			entry:         javaEntry,
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "catch (InterruptedException",
			wantVerdict:   "MeshHealthStatus.UNHEALTHY",
			bannedVerdict: "MeshHealthStatus.DEGRADED",
		},
		{
			name:          "java gemini",
			language:      "java",
			model:         "gemini/gemini-2.5-flash",
			entry:         javaEntry,
			outageMarker:  "vendor answered and it is not serving",
			outageEnd:     "catch (InterruptedException",
			wantVerdict:   "MeshHealthStatus.UNHEALTHY",
			bannedVerdict: "MeshHealthStatus.DEGRADED",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			content := renderProvider(t, tc.language, tc.model, tc.entry)
			branch := section(t, content, tc.outageMarker, tc.outageEnd)

			require.Contains(t, branch, tc.wantVerdict,
				"a vendor that answers with a non-200 is an OUTAGE: the branch must "+
					"report unhealthy so the heartbeat stops and consumers fail over")
			require.NotContains(t, branch, tc.bannedVerdict,
				"reporting degraded on a real outage keeps the heartbeat alive and "+
					"makes the provider unable to withdraw itself — the whole point "+
					"of the health check")
		})
	}
}

// The transport-failure branch (DNS, connect, timeout, TLS) is the other
// half of the same contract: the vendor is not answering at all.
func TestLlmProviderTemplates_TransportFailureIsUnhealthy(t *testing.T) {
	t.Run("python", func(t *testing.T) {
		content := renderProvider(t, "python", "anthropic/claude-sonnet-5", "main.py")
		branch := section(t, content, "API unreachable", "return {")
		require.Contains(t, branch, `status = "unhealthy"`)
	})

	t.Run("typescript", func(t *testing.T) {
		content := renderProvider(t, "typescript", "anthropic/claude-sonnet-5",
			filepath.Join("src", "index.ts"))
		branch := section(t, content, "The vendor is not answering at all", "}\n}")
		require.Contains(t, branch, `status: "unhealthy"`)
	})
}

// A cancelled probe concluded NOTHING about the vendor, so it must keep the
// heartbeat alive. This is the one place "degraded" is correct, and the
// inverse mistake (unhealthy on cancellation) would withdraw agents during
// ordinary shutdowns.
func TestLlmProviderTemplates_CancelledProbeIsDegraded(t *testing.T) {
	content := renderProvider(t, "typescript", "anthropic/claude-sonnet-5",
		filepath.Join("src", "index.ts"))
	branch := section(t, content, "if (isProbeCancelled(err))", "}\n    // The vendor")
	require.Contains(t, branch, `status: "degraded"`)
}

// The scaffolded agent must actually WIRE the check up — a correct
// healthCheck that nothing calls withdraws nothing.
func TestLlmProviderTemplates_HealthCheckIsWired(t *testing.T) {
	t.Run("python", func(t *testing.T) {
		content := renderProvider(t, "python", "anthropic/claude-sonnet-5", "main.py")
		require.Contains(t, content, "health_check=health_check")
		require.Contains(t, content, "health_check_ttl=")
	})

	t.Run("typescript", func(t *testing.T) {
		content := renderProvider(t, "typescript", "anthropic/claude-sonnet-5",
			filepath.Join("src", "index.ts"))
		require.Contains(t, content, "  healthCheck,")
		require.Contains(t, content, "healthCheckTtl:")
	})

	t.Run("java", func(t *testing.T) {
		content := renderProvider(t, "java", "anthropic/claude-sonnet-5", javaEntry)
		require.Contains(t, content, "@MeshHealthCheck(ttlSeconds =")
	})
}

// An unknown vendor gets a skeleton that cannot detect an outage. That is
// unavoidable — there is no generic reachability probe — but it must say so
// loudly rather than look finished.
func TestLlmProviderTemplates_UnknownVendorSkeletonWarns(t *testing.T) {
	entries := map[string]string{
		"python":     "main.py",
		"typescript": filepath.Join("src", "index.ts"),
		"java":       javaEntry,
	}
	for _, language := range []string{"python", "typescript", "java"} {
		entry := entries[language]
		t.Run(language, func(t *testing.T) {
			content := renderProvider(t, language, "cohere/command-r-plus", entry)
			require.Contains(t, content, "CANNOT DETECT AN")
			require.Contains(t, content, "NOT IMPLEMENTED")
		})
	}
}
