package scaffold

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

// RFC #1502 step 4: every scaffold ships BOTH hooks, and an llm-provider ships
// real ones.
//
// `health_check` answers "can I serve right now" and a failing one pauses the
// heartbeat; `startup_check` answers "can I ever serve" and a failing one keeps
// the pod from ever becoming ready. Two hooks that both take a "is this agent
// OK" verdict and do opposite things with it are exactly the pair a scaffold
// gets wrong by hand-copying, and the failure is silent in both directions: a
// missing hook is a template that simply says nothing, and an outage mapped
// onto the startup check crash-loops a correctly configured pod for as long as
// a vendor is down.
//
// So the guards here are mechanical rather than illustrative:
//
//  1. every template that CAN declare the hooks declares BOTH, wires BOTH, and
//     carries the comment that tells the two apart;
//  2. the two templates that CANNOT (issue #1506, closed as by design) declare
//     NEITHER, and say why;
//  3. the generated llm-provider `startup_check` maps a rejected credential to
//     FAIL and a vendor outage — a 5xx, a timeout, an unreachable host — to
//     PASS, for three vendors in three runtimes.
//
// (3) is the one that regresses invisibly. The probe body is hand-duplicated
// nine times, the two verdicts differ by one word, and a template that failed
// startup on a 5xx would look completely reasonable in review while turning
// every vendor outage into a CrashLoopBackOff — which is also how the signal
// this hook exists to produce ("your configuration is wrong") stops meaning
// anything.

// The comment markers are identical across the three runtimes on purpose: they
// are what makes this guard a matrix rather than fifteen hand-written cases.
const (
	// The two questions the hooks answer, verbatim from the scaffold comment.
	// A scaffold that declares both hooks and explains neither has shipped the
	// code and dropped the deliverable.
	nowQuestionMarker  = `"Can I serve RIGHT NOW?"`
	everQuestionMarker = `"Can I EVER serve?"`

	// Branch openers in the generated `startup_check`.
	missingKeyMarker  = "a missing key costs nothing to detect"
	rejectedMarker    = "The vendor answered and REJECTED the credential"
	notARejectMarker  = "that is not a rejection"
	unreachableMarker = "could not be reached at all"
)

// One runtime's spelling of the two hooks.
type hookRuntime struct {
	language string
	// Entry file, relative to the generated agent directory. Java's carries
	// the agent name, so it is a func rather than a constant.
	entry func(name string) string
	// Proof the hook is DECLARED.
	declaresHealth  string
	declaresStartup string
	// Proof the hook is HANDED TO the agent. A correct check nothing calls
	// withdraws nothing and admits everything.
	wiresHealth  string
	wiresStartup string
	// The verdict literals a `startup_check` branch can produce.
	startupPass string
	startupFail string
}

// javaEntryFor mirrors the scaffolder's Java layout: package
// com.example.<name with separators stripped>, class <NamePascal>Application.
func javaEntryFor(name string) string {
	flat := strings.NewReplacer("-", "", "_", "").Replace(strings.ToLower(name))
	pascal := ""
	for _, part := range strings.FieldsFunc(name, func(r rune) bool { return r == '-' || r == '_' }) {
		pascal += strings.ToUpper(part[:1]) + part[1:]
	}
	return filepath.Join("src", "main", "java", "com", "example", flat, pascal+"Application.java")
}

var hookRuntimes = []hookRuntime{
	{
		language:        "python",
		entry:           func(string) string { return "main.py" },
		declaresHealth:  "def health_check(",
		declaresStartup: "def startup_check(",
		wiresHealth:     "health_check=health_check",
		wiresStartup:    "startup_check=startup_check",
		startupPass:     `"status": "healthy"`,
		startupFail:     `"status": "unhealthy"`,
	},
	{
		language:        "typescript",
		entry:           func(string) string { return filepath.Join("src", "index.ts") },
		declaresHealth:  "function healthCheck(",
		declaresStartup: "function startupCheck(",
		wiresHealth:     "\n  healthCheck,",
		wiresStartup:    "\n  startupCheck,",
		startupPass:     `status: "healthy"`,
		startupFail:     `status: "unhealthy"`,
	},
	{
		language: "java",
		entry:    javaEntryFor,
		// Java has no separate declaration site: the annotation IS the
		// declaration and the wiring, since the starter scans beans for it.
		declaresHealth:  "@MeshHealthCheck(ttlSeconds =",
		declaresStartup: "@MeshStartupCheck",
		wiresHealth:     "@MeshHealthCheck(ttlSeconds =",
		wiresStartup:    "@MeshStartupCheck",
		startupPass:     "MeshHealth.healthy()",
		startupFail:     "MeshHealth.unhealthy(",
	},
}

// renderTemplateEntry scaffolds `template` in `language` and returns one
// generated file. Defaults come from NewScaffoldContext so the render matches
// what `meshctl scaffold` actually produces.
func renderTemplateEntry(t *testing.T, language, template, name, file string) string {
	t.Helper()
	ctx := NewScaffoldContext()
	ctx.Name = name
	ctx.Description = "hook probe"
	ctx.Language = language
	ctx.OutputDir = t.TempDir()
	ctx.Port = 9500
	ctx.Template = template
	ctx.TemplateDir = templatesRoot(t)
	ctx.AgentType = ""
	ctx.ProviderTags = []string{"llm", "+claude"}
	if template == "llm-provider" {
		ctx.Model = "anthropic/claude-sonnet-5"
	}
	require.NoError(t, NewStaticProvider().Execute(ctx))

	path := filepath.Join(ctx.OutputDir, ctx.Name, file)
	content, err := os.ReadFile(path)
	require.NoError(t, err, "rendered file %s", path)
	return string(content)
}

// The templates whose agent surface can carry both hooks. `api` is absent from
// every language, for two different reasons — see the exemption guard below.
var hookBearingTemplates = []string{"basic", "llm-agent", "llm-provider", "a2a-consumer"}

func TestScaffold_EveryHookBearingTemplateDeclaresAndWiresBothHooks(t *testing.T) {
	for _, rt := range hookRuntimes {
		for _, template := range hookBearingTemplates {
			t.Run(rt.language+" "+template, func(t *testing.T) {
				name := "hook-probe"
				content := renderTemplateEntry(t, rt.language, template, name, rt.entry(name))

				require.Contains(t, content, rt.declaresHealth,
					"%s/%s declares no health check: the agent cannot say "+
						"\"I am not available\" and mesh keeps routing to it "+
						"through an outage", rt.language, template)
				require.Contains(t, content, rt.declaresStartup,
					"%s/%s declares no startup check: a misconfigured pod "+
						"comes up, registers, and fails every call it is given "+
						"— indistinguishable from a vendor outage, which is the "+
						"confusion RFC #1502 exists to remove",
					rt.language, template)

				require.Contains(t, content, rt.wiresHealth,
					"%s/%s declares a health check the agent is never given, "+
						"so nothing ever runs it", rt.language, template)
				require.Contains(t, content, rt.wiresStartup,
					"%s/%s declares a startup check the agent is never given, "+
						"so /startupz answers 200 whatever it would have said",
					rt.language, template)
			})
		}
	}
}

// The code is half the deliverable. Two hooks that both take an "is this agent
// OK" verdict and do opposite things with it are useless — worse than useless,
// since one of the two mistakes crash-loops a working pod — unless the file
// says which is which.
func TestScaffold_HookBearingTemplatesExplainBothQuestions(t *testing.T) {
	for _, rt := range hookRuntimes {
		for _, template := range hookBearingTemplates {
			t.Run(rt.language+" "+template, func(t *testing.T) {
				name := "hook-probe"
				content := renderTemplateEntry(t, rt.language, template, name, rt.entry(name))

				require.Contains(t, content, nowQuestionMarker,
					"the scaffold must say what the health check is FOR: "+
						"without it the hook reads as a second startup check")
				require.Contains(t, content, everQuestionMarker,
					"the scaffold must say what the startup check is FOR: "+
						"without it the hook reads as a second health check, "+
						"and a vendor outage put in it crash-loops a pod whose "+
						"configuration was fine")

				// Naming the consequence is what makes the distinction
				// actionable — "override this one" is advice, "the pod lands in
				// CrashLoopBackOff" is a reason.
				require.Contains(t, content, "CrashLoopBackOff",
					"the startup check's consequence is the whole reason to "+
						"choose it over the health check")
				require.Contains(t, content, "heartbeat",
					"the health check's consequence — a paused heartbeat and "+
						"withdrawal from discovery, not a restart — is the "+
						"whole reason to choose it over the startup check")
			})
		}
	}
}

// Issue #1506, closed as BY DESIGN. Neither the Python nor the TypeScript `api`
// template can carry a hook, for two different structural reasons, and neither
// is waiting on a fix:
//
//   - Python: both hooks are `@mesh.agent` arguments, and `@mesh.agent` cannot
//     share a process with `@mesh.route` — the runtime rejects the combination
//     at startup ("Mixed mode not supported"), because each family owns the
//     HTTP server and the heartbeat;
//   - TypeScript: the hooks live on a mesh agent's config object, and a bare
//     `mesh.route()` app has none. `meshExpress()` carries them, but calling it
//     as well would register a SECOND agent from one process, since
//     `mesh.route()` already auto-starts the API runtime.
//
// Emitting a hook here anyway would be worse than emitting nothing: it would
// look declared, read as active, and do nothing at all. So the assertion is
// that the hook is ABSENT and the reason is PRESENT.
//
// Java's `api` template is deliberately not in this list — the starter scans
// every Spring bean for both annotations and serves the probes from one
// controller whatever the agent type, so a Java gateway carries both hooks and
// is covered by the matrix above.
var hookExemptAPITemplates = []string{"python", "typescript"}

func TestScaffold_APITemplatesThatCannotCarryHooksEmitNoneAndSayWhy(t *testing.T) {
	for _, language := range hookExemptAPITemplates {
		t.Run(language, func(t *testing.T) {
			var rt hookRuntime
			for _, candidate := range hookRuntimes {
				if candidate.language == language {
					rt = candidate
				}
			}
			require.NotEmpty(t, rt.language, "no runtime spelling for %s", language)

			name := "hook-probe"
			content := renderTemplateEntry(t, language, "api", name, rt.entry(name))

			require.NotContains(t, content, rt.declaresHealth,
				"%s/api cannot carry a health check: a declared one is dead "+
					"code that reads as active", language)
			require.NotContains(t, content, rt.declaresStartup,
				"%s/api cannot carry a startup check: a declared one is dead "+
					"code that reads as active", language)
			require.NotContains(t, content, rt.wiresStartup,
				"%s/api has nothing to wire a startup check into", language)

			require.Contains(t, content, "#1506",
				"the absence needs its citation, or the next reader adds the "+
					"hook back and it silently does nothing")
			require.Contains(t, content, "design decision rather than a gap",
				"#1506 is closed as BY DESIGN: wording that reads as \"not "+
					"yet\" promises a fix that is not coming")
			// Stating the gap without the replacement leaves the operator with
			// nothing. The replacement is not advice, it is generated code: a
			// gateway validates its own configuration at boot and exits, which
			// is what its framework already does and is strictly more flexible
			// than a hook.
			exitCall := map[string]string{
				"python":     "raise SystemExit(1)",
				"typescript": "process.exit(1)",
			}[language]
			require.Contains(t, content, "non-zero",
				"the comment must name what a gateway does INSTEAD of the hook")
			require.Contains(t, content, exitCall,
				"the replacement must be generated code, not a suggestion: a "+
					"gateway that comes up misconfigured takes ingress it "+
					"cannot answer")
		})
	}
}

// The generated `startup_check` must distinguish a credential the vendor
// REJECTED from a vendor that is merely unwell. Three branches, three runtimes,
// three vendors, and the whole design is in which verdict each one produces.
var startupBranches = []struct {
	name   string
	marker string
	// "pass" or "fail".
	want string
	why  string
}{
	{
		name:   "missing key fails",
		marker: missingKeyMarker,
		want:   "fail",
		why: "a key that is not set is never going to set itself: this is the " +
			"case the hook exists for, and passing it puts a provider on the " +
			"mesh that fails every call it is given",
	},
	{
		name:   "rejected credential fails",
		marker: rejectedMarker,
		want:   "fail",
		why: "the vendor answered and refused the key. No restart mints a valid " +
			"one, so the pod must crash-loop where an operator can see it " +
			"rather than register and fail every call",
	},
	{
		name:   "vendor answered non-200 passes",
		marker: notARejectMarker,
		want:   "pass",
		why: "a 5xx or a rate limit is the vendor's problem, not this agent's " +
			"configuration. Failing startup on it crash-loops a correctly " +
			"configured pod for as long as the outage lasts, and dilutes " +
			"CrashLoopBackOff from \"your configuration is wrong\" into noise. " +
			"The health check is what withdraws the agent meanwhile",
	},
	{
		name:   "unreachable vendor passes",
		marker: unreachableMarker,
		want:   "pass",
		why: "DNS, connect, timeout and TLS all mean the vendor did not answer, " +
			"which says nothing about the credential. Same reasoning as the " +
			"non-200 branch — and this is the branch a naive implementation " +
			"gets wrong, because the health check reports the identical " +
			"condition as UNHEALTHY",
	},
}

// firstVerdictAfter reports which verdict a branch produces: the FIRST of the
// two literals to appear after marker.
//
// Deliberately not a window between two end markers. The branch boundary in
// each runtime is a different token (`except`, `catch`, a closing brace), and a
// window that lost its end marker would silently widen until it matched some
// other branch's verdict and passed for the wrong reason. "What does this
// comment return" has one answer and needs no boundary.
func firstVerdictAfter(t *testing.T, content, marker, pass, fail string) string {
	t.Helper()
	start := strings.Index(content, marker)
	require.GreaterOrEqual(t, start, 0,
		"branch marker %q not found in the rendered startup check — the "+
			"comment moved, and with it this guard's only anchor", marker)

	rest := content[start+len(marker):]
	passAt := strings.Index(rest, pass)
	failAt := strings.Index(rest, fail)
	require.False(t, passAt < 0 && failAt < 0,
		"no verdict follows %q: the branch reports nothing", marker)

	if failAt < 0 || (passAt >= 0 && passAt < failAt) {
		return "pass"
	}
	return "fail"
}

// startupCheckOf isolates the generated `startup_check` from the `health_check`
// above it. The two probe the same endpoint and read the answer differently, so
// an assertion that could see both would be satisfied by the wrong one.
func startupCheckOf(t *testing.T, content, language string) string {
	t.Helper()
	var anchor string
	switch language {
	case "python":
		anchor = "async def startup_check("
	case "typescript":
		anchor = "async function startupCheck("
	default:
		anchor = "public MeshHealth startupCheck("
	}
	at := strings.Index(content, anchor)
	require.GreaterOrEqual(t, at, 0,
		"no startup check found in the rendered %s provider (%q)", language, anchor)
	return content[at:]
}

func TestLlmProviderTemplates_StartupCheckVerdictPerBranch(t *testing.T) {
	for _, rt := range hookRuntimes {
		for _, vendor := range probeVendors {
			for _, branch := range startupBranches {
				t.Run(rt.language+" "+vendor.name+" "+branch.name, func(t *testing.T) {
					content := renderProvider(t, rt.language, vendor.model, rt.entry("verdict-probe"))
					startup := startupCheckOf(t, content, rt.language)

					got := firstVerdictAfter(t, startup, branch.marker, rt.startupPass, rt.startupFail)
					require.Equal(t, branch.want, got, branch.why)
				})
			}
		}
	}
}

// The health check and the startup check must DISAGREE about a vendor that is
// not answering. That is the entire point of splitting them, and it is also the
// single easiest thing to get wrong by copying one probe into the other: both
// bodies call the same endpoint, and "unreachable" is a plausible failure in
// either.
func TestLlmProviderTemplates_TheTwoChecksDisagreeOnAnOutage(t *testing.T) {
	for _, rt := range hookRuntimes {
		for _, vendor := range probeVendors {
			t.Run(rt.language+" "+vendor.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, vendor.model, rt.entry("verdict-probe"))
				startup := startupCheckOf(t, content, rt.language)

				require.Equal(t, "pass",
					firstVerdictAfter(t, startup, unreachableMarker, rt.startupPass, rt.startupFail),
					"the startup check must PASS an unreachable vendor")

				// The health check's own verdict on the same condition is
				// pinned by TestLlmProviderTemplates_TransportFailureIsUnhealthy;
				// asserted again here so the DISAGREEMENT is a single failing
				// test rather than two passing ones in different files.
				health := content[:strings.Index(content, startup)]
				require.Contains(t, health, transportMarker,
					"the health check lost its transport-failure branch")
				require.NotContains(t, health, unreachableMarker,
					"the two probes must not share a branch comment: an "+
						"assertion anchored on it would stop being able to "+
						"tell which check it is reading")
			})
		}
	}
}

// A gateway-prefixed model has no probeable direct vendor API, so its startup
// check is a skeleton — and the skeleton must not name a vendor credential the
// deployment never sets. A startup check gated on one would fail forever, and
// unlike the health-check version of this bug (#1479, a provider withdrawn from
// the registry) this one keeps the pod from ever coming up at all.
func TestLlmProviderTemplates_GatewayModelGetsSkeletonStartupCheck(t *testing.T) {
	for _, rt := range hookRuntimes {
		for _, gw := range gatewayModels {
			t.Run(rt.language+" "+gw.name, func(t *testing.T) {
				content := renderProvider(t, rt.language, gw.model, rt.entry("verdict-probe"))

				require.Contains(t, content, rt.declaresStartup,
					"even with nothing to probe, the hook must be present so "+
						"the operator has somewhere to put their own check")
				require.NotContains(t, content, missingKeyMarker,
					"%s has no vendor key to look for: the real probe leaked "+
						"into the gateway branch", gw.model)
				require.NotContains(t, content, gw.bannedKey,
					"a startup check gated on %s never passes for %s, so the "+
						"pod never becomes ready — a permanent outage from a "+
						"credential nothing reads", gw.bannedKey, gw.model)
			})
		}
	}
}

// A bearer-authenticated A2A bridge knows exactly what it cannot run without,
// so its generated startup check is real rather than a TODO. This branch is
// only reachable when the producer's card advertises bearer auth, which the
// static render never sets, so the data is supplied directly.
func TestA2AConsumerTemplates_BearerAuthGetsARealStartupCheck(t *testing.T) {
	wantEnvRead := map[string]string{
		"python":     `os.getenv("A2A_TEST_TOKEN")`,
		"typescript": `process.env["A2A_TEST_TOKEN"]`,
		"java":       `System.getenv("A2A_TEST_TOKEN")`,
	}

	for _, rt := range hookRuntimes {
		t.Run(rt.language, func(t *testing.T) {
			name := "hook-probe"
			ctx := NewScaffoldContext()
			ctx.Name = name
			ctx.Language = rt.language
			ctx.Template = "a2a-consumer"
			ctx.Port = 9500
			ctx.JavaPackage = "com.example.hookprobe"

			data := TemplateDataFromContext(ctx)
			data["A2AURL"] = "https://producer.example/agents/x"
			data["AuthBearer"] = true
			data["AuthEnvVar"] = "A2A_TEST_TOKEN"
			data["Offline"] = false
			data["Skills"] = []map[string]interface{}{}

			outDir := t.TempDir()
			srcDir := filepath.Join(templatesRoot(t), rt.language, "a2a-consumer")
			require.NoError(t, NewTemplateRenderer().RenderDirectory(srcDir, outDir, data))

			raw, err := os.ReadFile(filepath.Join(outDir, rt.entry(name)))
			require.NoError(t, err)
			content := string(raw)

			startupAt := strings.Index(content, rt.declaresStartup)
			require.GreaterOrEqual(t, startupAt, 0, "no startup check declared")

			require.Contains(t, content[startupAt:], wantEnvRead[rt.language],
				"a bridge whose producer requires a bearer token must FAIL "+
					"startup without one: that token is not going to appear "+
					"while the pod runs, and a bridge without it fails every "+
					"call it is given")
		})
	}
}
