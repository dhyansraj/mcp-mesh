package scaffold

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/registry"
)

// `+` and `-` are a CONSUMER-side construct. `meshctl man tags` states it
// outright — "Operators are for consumers only. When declaring tags on your
// tool, use plain strings without +/- prefixes" — and the matcher enforces it
// by construction: it strips the operator from what the CONSUMER asked for and
// then compares the remainder to the provider's tags with exact string equality
// (registry.containsTag). A provider tag of "+fallback" is therefore a literal
// tag spelled with a plus, and no pin a consumer can write will ever equal it.
//
// The scaffold shipped exactly that (issue #1546): every generated provider
// carried an operator tag, and for `litellm-fallback` the operator form was the
// ONLY fallback-ish tag, so the `+fallback` pin the scaffold itself prints for
// the consumer matched nothing. It failed silently, which is the whole reason
// this file exists — a preferred tag carries a bonus when present and NO
// penalty when absent, so the pin did not error, did not narrow the candidate
// set and did not fail resolution. It scored zero and the consumer resolved to
// whichever provider won on other criteria.
//
// So the guards below come in two halves that fail for different reasons:
//
//   - the operator BAN (no generated provider tag is operator-prefixed) is the
//     general shape, and would have caught all four vendors at source;
//   - the round-trip (the vendor's own consumer pin actually SCORES against the
//     vendor's own provider tags, through the real matcher) is what catches the
//     half of the bug that survives a naive fix. Stripping "+fallback" without
//     adding "fallback" satisfies the ban and leaves the pin just as dead.
//
// They are asserted on the map AND on the rendered agent, because the map is
// not what a user runs. The llm-provider subcommand always sets ctx.Tags, which
// selects the `{{ if .Tags }}` arm of all three templates — the `{{ else }}`
// arm, backed by ProviderTagsForModel, is a different code path and is covered
// separately below.

// operatorPrefixed reports whether tag carries a consumer-side operator.
func operatorPrefixed(tag string) bool {
	return strings.HasPrefix(tag, "+") || strings.HasPrefix(tag, "-")
}

// No vendor's provider tag list may carry an operator.
func TestVendorProviderTagsCarryNoOperators(t *testing.T) {
	for _, vendor := range SupportedLLMVendors() {
		t.Run(vendor, func(t *testing.T) {
			tags := VendorToProviderTags(vendor)
			require.NotEmpty(t, tags, "no discovery tags for vendor %s", vendor)
			for _, tag := range tags {
				require.Falsef(t, operatorPrefixed(tag),
					"provider tag %q on vendor %s carries a consumer-side operator: the "+
						"matcher compares provider tags by exact string equality, so this "+
						"is a literal tag spelled with an operator and no consumer pin can "+
						"match it (issue #1546)", tag, vendor)
			}
		})
	}
}

// The other producer of provider tags — the `{{ else }}` arm of the same three
// templates, and the interactive wizard — is held to the same rule.
func TestModelFamilyProviderTagsCarryNoOperators(t *testing.T) {
	models := []string{
		"anthropic/claude-sonnet-5",
		"openai/gpt-4o",
		"gemini/gemini-2.5-flash",
		"bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
		"vertex_ai/gemini-2.5-flash",
		"cohere/command-r-plus",
		"",
	}
	for _, model := range models {
		t.Run(model, func(t *testing.T) {
			for _, tag := range ProviderTagsForModel(model) {
				require.Falsef(t, operatorPrefixed(tag),
					"provider tag %q for model %q carries a consumer-side operator", tag, model)
			}
		})
	}
}

// The half a naive fix misses: the consumer tag the scaffold PRINTS must
// actually score against the provider tags the scaffold GENERATES. Run through
// the real matcher rather than a hand-rolled restatement of it, because the
// silence is the bug — the matcher returns (true, 0) for a pin that matched
// nothing, which is indistinguishable from success at every caller.
func TestVendorConsumerPinScoresAgainstItsOwnProvider(t *testing.T) {
	matcher := registry.NewMatcher(nil)

	for _, vendor := range SupportedLLMVendors() {
		t.Run(vendor, func(t *testing.T) {
			providerTags := VendorToProviderTags(vendor)
			consumerTag := VendorToConsumerTag(vendor)
			require.NotEmpty(t, consumerTag, "no consumer pin for vendor %s", vendor)

			matched, score := matcher.MatchTags(providerTags, []string{consumerTag}, nil)
			require.True(t, matched, "pin %q rejected provider tags %v", consumerTag, providerTags)
			require.Equalf(t, 10, score,
				"the pin %q that `meshctl scaffold llm-provider --vendor %s` tells the "+
					"user to put on their consumer scored %d against the provider tags %v "+
					"that the same command generates. A preferred tag that matches nothing "+
					"scores 0 and costs nothing, so the consumer still resolves — to some "+
					"other provider, with no error anywhere (issue #1546)",
				consumerTag, vendor, score, providerTags)
		})
	}
}

// For the big-3 the two producers of provider tags must agree. They render into
// the same decorator through different arms of the same template line, so a
// divergence means the same `--vendor claude` provider advertises one tag set
// from the subcommand and another from the wizard, and a consumer pin resolves
// one of them.
//
// litellm-fallback is deliberately exempt: its default model is openai/gpt-4o,
// but it is a general fallback route and must NOT claim the openai family's
// tags, so it carries the generic list plus its own "fallback".
func TestVendorProviderTagsMatchModelFamilyTags(t *testing.T) {
	for _, vendor := range SupportedLLMVendors() {
		if vendor == "litellm-fallback" {
			continue
		}
		t.Run(vendor, func(t *testing.T) {
			require.Equal(t, ProviderTagsForModel(VendorToModel(vendor)), VendorToProviderTags(vendor),
				"the tags the llm-provider subcommand pins and the tags the templates "+
					"derive from the model have diverged for %s", vendor)
		})
	}
}

// providerEntryFile is where each runtime puts the agent whose tags we read.
// The Java path is derived by the scaffolder from the agent name, so it is
// pinned to the name used below.
var providerEntryFile = map[string]string{
	"python":     "main.py",
	"typescript": filepath.Join("src", "index.ts"),
	"java": filepath.Join(
		"src", "main", "java", "com", "example", "tagprobe", "TagProbeApplication.java"),
}

// renderedTagsLiteral is the tag list as each runtime's template emits it when
// ctx.Tags is set. Python and TypeScript go through toJSON (compact, no space
// after the comma); Java hand-renders with ", ".
func renderedTagsLiteral(language string, tags []string) string {
	switch language {
	case "python":
		return "tags=" + toJSON(tags)
	case "typescript":
		return "tags: " + toJSON(tags)
	default:
		quoted := make([]string, len(tags))
		for i, tag := range tags {
			quoted[i] = `"` + tag + `"`
		}
		return "tags = {" + strings.Join(quoted, ", ") + "}"
	}
}

// scaffoldProviderEntry runs the real llm-provider subcommand for a vendor and
// runtime and returns the generated entry file. Going through the command, not
// through a hand-built ScaffoldContext, is the point: the operator tags reached
// users because the subcommand populates ctx.Tags, and a test that builds its
// own context would not exercise that.
func scaffoldProviderEntry(t *testing.T, vendor, language string) string {
	t.Helper()
	t.Chdir(findRepoRoot(t))

	out := t.TempDir()
	cmd := newScaffoldLLMProviderCommand()
	cmd.SetOut(&bytes.Buffer{})
	cmd.SetErr(&bytes.Buffer{})
	require.NoError(t, cmd.Flags().Set("vendor", vendor))
	require.NoError(t, cmd.Flags().Set("runtime", language))
	require.NoError(t, cmd.Flags().Set("name", "tag-probe"))
	require.NoError(t, cmd.Flags().Set("output", out))
	require.NoError(t, runScaffoldLLMProvider(cmd, nil))

	content, err := os.ReadFile(filepath.Join(out, "tag-probe", providerEntryFile[language]))
	require.NoError(t, err)
	return string(content)
}

// declaredTagsLine returns the single line on which the generated agent declares
// its discovery tags, so the operator ban below is scoped to the declaration
// instead of the whole file. The templates legitimately mention "+claude" and
// "+openai" in the consumer-usage comment they carry, and a whole-file ban would
// hit those — which are correct usage.
func declaredTagsLine(t *testing.T, content, language string) string {
	t.Helper()
	prefix := map[string]string{
		"python":     "tags=[",
		"typescript": "tags: [",
		"java":       "tags = {",
	}[language]

	for _, line := range strings.Split(content, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), prefix) {
			return line
		}
	}
	t.Fatalf("no line declaring tags (prefix %q) in the generated %s agent — the "+
		"template moved and this guard would otherwise pass by finding nothing", prefix, language)
	return ""
}

// The map edit is not the deliverable; the generated agent is. Every vendor in
// every runtime.
func TestScaffoldedProviderDeclaresOperatorFreeTags(t *testing.T) {
	for _, vendor := range SupportedLLMVendors() {
		for _, language := range []string{"python", "typescript", "java"} {
			t.Run(vendor+" "+language, func(t *testing.T) {
				content := scaffoldProviderEntry(t, vendor, language)

				want := renderedTagsLiteral(language, VendorToProviderTags(vendor))
				require.Contains(t, content, want,
					"the vendor's discovery tags did not reach the generated agent")

				line := declaredTagsLine(t, content, language)
				for _, tag := range VendorToProviderTags(vendor) {
					require.Falsef(t, operatorPrefixed(tag),
						"generated %s agent declares operator tag %q: %s", language, tag, line)
				}
				require.NotContains(t, line, `"+`,
					"an operator-prefixed tag on the provider side matches no consumer pin "+
						"and fails silently (issue #1546): %s", line)
				require.NotContains(t, line, `"-`,
					"an operator-prefixed tag on the provider side matches no consumer pin "+
						"and fails silently (issue #1546): %s", line)
			})
		}
	}
}
