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
//
// RFC #1515 makes the contract binary and takes `degraded` out of the teaching
// surface entirely, so the branch-scoped bans above are joined by a WHOLE-FILE
// one (TestScaffoldedAgentsNeverMentionDegraded). Java's interrupt branch was
// the last selection left: it now restores the interrupt and rethrows, which
// lands on the runtime's own indeterminate verdict — the same outcome, chosen
// by the runtime rather than named by the author.

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
	outageMarker    = "vendor ANSWERED, so it is reachable"
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
	// Text proving the probe's error handling is narrowed to transport
	// failures, and text proving it is not catch-all.
	narrowHandler string
	broadHandler  string
}

var runtimeProbes = []runtimeProbe{
	{
		language:      "python",
		entry:         "main.py",
		outageEnd:     "except httpx.RequestError",
		transportEnd:  "return {",
		wantVerdict:   `status = "unhealthy"`,
		bannedVerdict: `status = "degraded"`,
		wiring:        []string{"health_check=health_check", "health_check_ttl="},
		narrowHandler: "except httpx.RequestError",
		broadHandler:  "except Exception",
	},
	{
		language:      "typescript",
		entry:         filepath.Join("src", "index.ts"),
		outageEnd:     "} catch (err)",
		transportEnd:  "}\n}",
		wantVerdict:   `status: "unhealthy"`,
		bannedVerdict: `status: "degraded"`,
		wiring:        []string{"  healthCheck,", "healthCheckTtl:"},
		// TypeScript cannot name a transport failure in the catch clause, so
		// the narrowing is the rethrow on the first line of the handler.
		narrowHandler: "if (!isVendorUnreachable(err)) throw err;",
	},
	{
		language: "java",
		entry:    javaEntry,
		// Java's transport branch is the LAST catch, after the
		// InterruptedException one, which restores the interrupt and rethrows.
		outageEnd:     "catch (InterruptedException",
		transportEnd:  "\n    }",
		wantVerdict:   "MeshHealthStatus.UNHEALTHY",
		bannedVerdict: "MeshHealthStatus.DEGRADED",
		wiring:        []string{"@MeshHealthCheck(ttlSeconds ="},
		narrowHandler: "catch (IOException e)",
		broadHandler:  "catch (Exception e)",
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

// The two branches disagree about REACHABILITY, and the disagreement is the
// point: a vendor that answers with a 503 is reachable and not serving, while
// one that never answers is not reachable at all. Reporting the first as
// unreachable puts a claim on /health that the probe just disproved — the
// connection succeeded — and it did so in the same function that gets 401
// right two lines above.
//
// Both branches still report unhealthy; only the sub-check differs. That is
// what makes this a separate guard from the two above rather than a widening
// of them.
func TestLlmProviderTemplates_VendorOutageReportsReachable(t *testing.T) {
	// The rendered `reachable` sub-check, per runtime: false in the transport
	// branch, true in the outage branch.
	reachableTrue := map[string]string{
		"python":     `_api_reachable"] = True`,
		"typescript": "_api_reachable = true;",
		"java":       `_api_reachable", true)`,
	}
	reachableFalse := map[string]string{
		"python":     `_api_reachable"] = False`,
		"typescript": "_api_reachable = false;",
		"java":       `_api_reachable", false)`,
	}

	for _, rt := range runtimeProbes {
		for _, vendor := range probeVendors {
			t.Run(rt.language+" "+vendor.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, vendor.model, rt.entry)

				outage := section(t, content, outageMarker, rt.outageEnd)
				require.Contains(t, outage, reachableTrue[rt.language],
					"the vendor ANSWERED in this branch, so it is reachable — the "+
						"failure is the status it answered with, which the error string "+
						"already carries")
				require.NotContains(t, outage, reachableFalse[rt.language],
					"reporting unreachable for a vendor that just answered contradicts "+
						"the 401 branch of the same probe and misleads whoever reads "+
						"/health during an outage")

				transport := section(t, content, transportMarker, rt.transportEnd)
				require.Contains(t, transport, reachableFalse[rt.language],
					"nothing answered in this branch: this is the one case that is "+
						"genuinely unreachable")
			})
		}
	}
}

// A catch-all handler reports a DEFECT IN THE PROBE as a vendor outage, and a
// vendor outage withdraws the agent. So a typo in the probe — a NameError, a
// ReferenceError — would take a provider whose vendor is perfectly healthy out
// of dependency resolution, permanently, because it recurs on every refresh.
//
// The runtime already refuses to do that: an exception that escapes a health
// check is recorded as the indeterminate verdict, which keeps the agent
// serving (issue #1477). The templates have to LET it escape to get that, so
// each one names the transport failure it means and rethrows the rest.
func TestLlmProviderTemplates_ProbeHandlersAreNarrow(t *testing.T) {
	for _, rt := range runtimeProbes {
		for _, vendor := range probeVendors {
			t.Run(rt.language+" "+vendor.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, vendor.model, rt.entry)

				require.Contains(t, content, rt.narrowHandler,
					"the probe must answer only for the failure it can actually "+
						"recognize — the vendor not answering — and let a defect in "+
						"itself propagate to the runtime's indeterminate verdict")
				if rt.broadHandler != "" {
					require.NotContains(t, content, rt.broadHandler,
						"a catch-all handler turns a bug in this probe into a vendor "+
							"outage, and a vendor outage withdraws a working provider "+
							"from the mesh")
				}
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

// RFC #1515: `degraded` is out of the teaching surface, scaffold comments
// included. The per-branch bans above stop the INVERSION; this stops the
// vocabulary from coming back at all — as a returned value, as advice in a
// comment, or as the "here is what the runtime does with a throw" aside that
// three templates carried and that reads, to someone skimming for what to
// return, like a third option.
//
// A whole-file assertion is only possible because nothing legitimate needs the
// word any more. It is also the only assertion that would have caught the
// original bug at its source: every template that shipped the inversion
// mentioned `degraded` in prose first and returned it second.
//
// Every template gets this, not just llm-provider — basic, llm-agent,
// a2a-consumer and api all carry the same health/startup preamble, and a
// re-added mention in any one of them is a re-added mention. All five
// templates in all three languages, so the table is the whole matrix.
func TestScaffoldedAgentsNeverMentionDegraded(t *testing.T) {
	templates := []struct {
		language string
		template string
		entry    string
	}{
		{"python", "basic", "main.py"},
		{"python", "llm-agent", "main.py"},
		{"python", "llm-provider", "main.py"},
		{"python", "a2a-consumer", "main.py"},
		{"python", "api", "main.py"},
		{"typescript", "basic", filepath.Join("src", "index.ts")},
		{"typescript", "llm-agent", filepath.Join("src", "index.ts")},
		{"typescript", "llm-provider", filepath.Join("src", "index.ts")},
		{"typescript", "a2a-consumer", filepath.Join("src", "index.ts")},
		{"typescript", "api", filepath.Join("src", "index.ts")},
		{"java", "basic", javaEntry},
		{"java", "llm-agent", javaEntry},
		{"java", "llm-provider", javaEntry},
		{"java", "a2a-consumer", javaEntry},
		{"java", "api", javaEntry},
	}

	for _, tpl := range templates {
		t.Run(tpl.language+" "+tpl.template, func(t *testing.T) {
			ctx := &ScaffoldContext{
				Name:        "verdict-probe",
				Description: "verdict probe",
				Language:    tpl.language,
				OutputDir:   t.TempDir(),
				Port:        9400,
				Model:       "anthropic/claude-sonnet-5",
				Template:    tpl.template,
				TemplateDir: templatesRoot(t),
			}
			require.NoError(t, NewStaticProvider().Execute(ctx))

			content, err := os.ReadFile(filepath.Join(ctx.OutputDir, ctx.Name, tpl.entry))
			require.NoError(t, err)

			require.NotContains(t, strings.ToLower(string(content)), "degraded",
				"a health check answers one binary question — keep routing here, or "+
					"stop — and `degraded` is the same answer as healthy on every mesh "+
					"path. Naming it in scaffolded code is what produced the inversion "+
					"this file exists to catch, so it stays out of the generated "+
					"output entirely (RFC #1515)")
		})
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
// The probe is only half of it. A gateway model still HAS a family — Bedrock
// Claude is Claude — so the discovery tags must keep naming it, or a consumer
// scaffolded with `--vendor claude` (which pins `+claude`) stops resolving this
// provider. wantTags below is the independent half: skeleton probe, real tags.
var gatewayModels = []struct {
	name string
	// The probe that must NOT be selected, and the credential that proves it.
	model     string
	bannedAPI string
	bannedKey string
	// The discovery tags the model's FAMILY earns, despite the skeleton probe.
	wantTags []string
}{
	{
		name:      "bedrock claude",
		model:     "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
		bannedAPI: "api.anthropic.com",
		bannedKey: "ANTHROPIC_API_KEY",
		wantTags:  []string{"llm", "claude", "anthropic", "provider"},
	},
	{
		// A cross-region inference profile: the family sits behind a region
		// segment, so a resolver that only looks at the first dot segment
		// ("us") drops the claude tags.
		name:      "bedrock claude cross-region profile",
		model:     "bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0",
		bannedAPI: "api.anthropic.com",
		bannedKey: "ANTHROPIC_API_KEY",
		wantTags:  []string{"llm", "claude", "anthropic", "provider"},
	},
	{
		name:      "vertex gemini",
		model:     "vertex_ai/gemini-2.5-flash",
		bannedAPI: "generativelanguage.googleapis.com",
		bannedKey: "GOOGLE_API_KEY",
		wantTags:  []string{"llm", "gemini", "google", "provider"},
	},
	{
		name:      "databricks claude",
		model:     "databricks/anthropic.claude-3-7-sonnet",
		bannedAPI: "api.anthropic.com",
		bannedKey: "ANTHROPIC_API_KEY",
		wantTags:  []string{"llm", "claude", "anthropic", "provider"},
	},
	{
		// A gateway model with no big-3 family at all: no probe AND no vendor
		// tags. Without this row every gateway case expects vendor tags, and a
		// family resolver that simply always answered "anthropic" would pass.
		name:      "bedrock llama",
		model:     "bedrock/meta.llama3-70b-instruct-v1:0",
		bannedAPI: "api.anthropic.com",
		bannedKey: "ANTHROPIC_API_KEY",
		wantTags:  []string{"llm", "provider"},
	},
}

// tagsMarker renders a tag list in one runtime's literal syntax, so the matrix
// can assert on tags without hand-writing three copies per case.
func tagsMarker(language string, tags []string) string {
	quoted := make([]string, len(tags))
	for i, tag := range tags {
		quoted[i] = `"` + tag + `"`
	}
	joined := strings.Join(quoted, ", ")

	switch language {
	case "python":
		return "tags=[" + joined + "]"
	case "typescript":
		return "tags: [" + joined + "]"
	default:
		return "tags = {" + joined + "}"
	}
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

// The README env-var instructions follow the PROBE: a gateway authenticates
// with its own credentials, so the README must not tell the operator to export
// the underlying vendor's API key.
//
// The tags follow the FAMILY instead, and asserting both here is the point —
// they are answers to different questions and a template that wires one arm to
// the other resolver breaks exactly one of these two assertions.
func TestLlmProviderTemplates_GatewayModelKeepsFamilyTagsButNotVendorCredentials(t *testing.T) {
	for _, rt := range runtimeProbes {
		for _, gw := range gatewayModels {
			t.Run(rt.language+" "+gw.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, gw.model, rt.entry)
				require.Contains(t, content, tagsMarker(rt.language, gw.wantTags),
					"%s is served by a gateway but it is still a %s model: wiring the "+
						"tags to the probe resolver de-registers the vendor tags and a "+
						"consumer pinning +claude / +gemini stops resolving it",
					gw.model, gw.wantTags)

				readme := renderProvider(t, rt.language, gw.model, "README.md")
				require.NotContains(t, readme, "export "+gw.bannedKey,
					"the README tells the operator to export a key the gateway "+
						"does not use")

				// Not just the vendor's key: a generic `API_KEY` / `api-key`
				// fallback is no better. The TypeScript README's Docker and
				// kubectl blocks ended their vendor chain with one, so a Bedrock
				// scaffold told the operator to pass `API_KEY=$API_KEY` and
				// create a secret keyed `api-key` — names neither gateway reads,
				// in the same file whose prose says to use the gateway's own
				// credentials.
				require.NotContains(t, readme, "API_KEY",
					"%s authenticates with its gateway's credentials: naming any "+
						"API key here, vendor-specific or generic, sends the "+
						"operator to configure something nothing reads", gw.model)
				require.NotContains(t, readme, "api-key",
					"%s authenticates with its gateway's credentials, so no "+
						"api-key secret name applies", gw.model)
			})
		}
	}
}

// The big-3 matrix is the other half: narrowing the gate must not have taken
// the real probes with it.
//
// The uppercase rows are what pin case-insensitivity, and they sit HERE rather
// than in the gateway matrix because this is the direction that can actually
// regress. `VERTEX_AI/...` in the gateway matrix proves nothing: a resolver
// that stopped lowercasing would miss the map, return "", emit the skeleton and
// pass. `ANTHROPIC/claude-sonnet-5` fails loudly instead — the miss silently
// degrades a real probe into the skeleton, which is the case that takes a
// working health check away.
func TestLlmProviderTemplates_BareBig3NameStillProbes(t *testing.T) {
	// wantTags is the whole rendered tag literal, matched via tagsMarker, not a
	// bare family word: "anthropic" appears in the API host, the import path and
	// the comments of every Anthropic render, so `Contains(content, "anthropic")`
	// holds even with the tag list absent or carrying another family's tags.
	bare := []struct {
		model    string
		wantAPI  string
		wantKey  string
		wantTags []string
	}{
		{"claude-sonnet-5", "api.anthropic.com", "ANTHROPIC_API_KEY", []string{"llm", "claude", "anthropic", "provider"}},
		{"gpt-4o", "api.openai.com", "OPENAI_API_KEY", []string{"llm", "openai", "gpt", "provider"}},
		{"gemini-2.5-flash", "generativelanguage.googleapis.com", "GOOGLE_API_KEY", []string{"llm", "gemini", "google", "provider"}},

		// --model is free-form, so the casing is the user's.
		{"ANTHROPIC/claude-sonnet-5", "api.anthropic.com", "ANTHROPIC_API_KEY", []string{"llm", "claude", "anthropic", "provider"}},
		{"Claude-Sonnet-5", "api.anthropic.com", "ANTHROPIC_API_KEY", []string{"llm", "claude", "anthropic", "provider"}},
		{"OpenAI/GPT-4o", "api.openai.com", "OPENAI_API_KEY", []string{"llm", "openai", "gpt", "provider"}},
		{"GEMINI/Gemini-2.5-Flash", "generativelanguage.googleapis.com", "GOOGLE_API_KEY", []string{"llm", "gemini", "google", "provider"}},
	}

	for _, rt := range runtimeProbes {
		for _, b := range bare {
			t.Run(rt.language+" "+b.model, func(t *testing.T) {
				content := renderProvider(t, rt.language, b.model, rt.entry)
				require.Contains(t, content, b.wantAPI)
				require.Contains(t, content, b.wantKey)
				require.Contains(t, content, tagsMarker(rt.language, b.wantTags),
					"%s must register its family's discovery tags, or a consumer "+
						"pinning +claude / +gpt / +gemini stops resolving it", b.model)
				require.NotContains(t, content, "NOT IMPLEMENTED",
					"an unprefixed big-3 name is probeable and must get the real probe")
			})
		}
	}
}
