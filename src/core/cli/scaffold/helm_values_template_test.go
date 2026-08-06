package scaffold

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	"gopkg.in/yaml.v3"
)

// Issue #1483. `helm-values.yaml.tmpl` used to wire ANTHROPIC_API_KEY,
// OPENAI_API_KEY and GOOGLE_API_KEY unconditionally, from a secret the header
// comment told the operator to create with all three literals — plus a generic
// `API_KEY: "your-api-key"` example lower down.
//
// Two false assertions came out of that, and they are the two pinned here:
//
//  1. a gateway scaffold (`bedrock/...`, `vertex_ai/...`, `databricks/...`) or a
//     long-tail model shipped a manifest instructing exactly the credentials its
//     own README — correctly, since #1484 — says are the wrong ones. The
//     gateway's endpoint authenticates with the gateway's own credentials, so a
//     manifest that names any vendor key is sending the operator to configure
//     something nothing reads;
//
//  2. a Gemini scaffold claimed it needed ANTHROPIC_API_KEY. The READMEs already
//     emit only the selected vendor's key; the helm values were the last place
//     claiming otherwise.
//
// Both are SUBTRACTIVE fixes — stop asserting something false. This guard
// deliberately does NOT pin any gateway-specific wiring (IRSA / AWS_ROLE_ARN, a
// `serviceAccount:` annotation for Workload Identity, a Databricks host+token).
// Modelling those is the additive half of #1483 and needs an owner decision on
// the env / ServiceAccount shape; the goal here is a manifest that is SILENT
// about credentials it cannot know, not one that guesses.

// Every vendor key the file used to wire, so a render can be checked for the
// ones it must NOT name.
var allVendorKeys = []string{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"}

var allVendorSecretKeys = []string{"anthropic-api-key", "openai-api-key", "google-api-key"}

// helmLanguages is the whole matrix: the same defect was hand-copied into all
// three files, and fixing two of them is how this regresses.
var helmLanguages = []string{"python", "typescript", "java"}

// renderHelmValues scaffolds an llm-provider agent and returns its rendered
// helm-values.yaml.
func renderHelmValues(t *testing.T, language, model string) string {
	t.Helper()
	return renderProvider(t, language, model, "helm-values.yaml")
}

// A gateway-prefixed or long-tail model has no direct vendor API and no vendor
// key. The manifest must name none of them, and must not fall back to a generic
// `API_KEY` / `api-key` either — that is the same fallback removed from the
// TypeScript README in #1484.
func TestHelmValues_GatewayModelWiresNoVendorCredentials(t *testing.T) {
	gatewayOrLongTail := []string{
		"bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
		"bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0",
		"bedrock/meta.llama3-70b-instruct-v1:0",
		"vertex_ai/gemini-2.5-flash",
		"databricks/anthropic.claude-3-7-sonnet",
		// A plain long-tail model: no gateway prefix, still no probeable
		// direct big-3 API and still no vendor key that applies.
		"cohere/command-r-plus",
	}

	for _, language := range helmLanguages {
		for _, model := range gatewayOrLongTail {
			t.Run(language+" "+model, func(t *testing.T) {
				content := renderHelmValues(t, language, model)

				for _, key := range allVendorKeys {
					require.NotContains(t, content, key,
						"%s authenticates with its endpoint's own credentials: wiring %s "+
							"tells the operator to create a secret nothing reads, in the "+
							"same scaffold whose README says to use the gateway's "+
							"credentials", model, key)
				}
				for _, key := range allVendorSecretKeys {
					require.NotContains(t, content, key,
						"the kubectl comment still instructs a %s literal for %s",
						key, model)
				}
				require.NotContains(t, content, "API_KEY",
					"%s authenticates with its endpoint's own credentials: naming any "+
						"API key here, vendor-specific or generic, sends the operator to "+
						"configure something nothing reads", model)
				require.NotContains(t, content, "api-key",
					"%s authenticates with its endpoint's own credentials, so no "+
						"api-key secret name applies", model)

				// Silent about the credential is not the same as silent about the
				// SUBJECT: the operator still has to be told where to look.
				require.Contains(t, content, "gateway",
					"the manifest must still point at the gateway's own credentials "+
						"rather than simply omitting the topic")
			})
		}
	}
}

// The other half: narrowing the wiring must not have taken the real vendor keys
// with it, and only the SELECTED vendor's key may appear.
func TestHelmValues_Big3WiresOnlyTheSelectedVendorKey(t *testing.T) {
	// Bare names, native prefixes and mixed case — `--model` is free-form, so
	// the casing is the user's. A resolver that stopped lowercasing would drop
	// to the gateway branch and silently ship a manifest with no key at all.
	big3 := []struct {
		model     string
		wantKey   string
		wantEnv   string
		wantValue string
	}{
		{"claude-sonnet-5", "ANTHROPIC_API_KEY", "anthropic-api-key", "sk-ant-"},
		{"anthropic/claude-sonnet-5", "ANTHROPIC_API_KEY", "anthropic-api-key", "sk-ant-"},
		{"Claude-Opus-4-8", "ANTHROPIC_API_KEY", "anthropic-api-key", "sk-ant-"},
		{"gpt-4o", "OPENAI_API_KEY", "openai-api-key", "sk-"},
		{"openai/gpt-4o", "OPENAI_API_KEY", "openai-api-key", "sk-"},
		{"OpenAI/GPT-4o", "OPENAI_API_KEY", "openai-api-key", "sk-"},
		{"gemini-2.5-flash", "GOOGLE_API_KEY", "google-api-key", "AIza"},
		{"gemini/gemini-2.5-flash", "GOOGLE_API_KEY", "google-api-key", "AIza"},
		{"GEMINI/Gemini-2.5-Flash", "GOOGLE_API_KEY", "google-api-key", "AIza"},
	}

	for _, language := range helmLanguages {
		for _, b := range big3 {
			t.Run(language+" "+b.model, func(t *testing.T) {
				content := renderHelmValues(t, language, b.model)

				require.Contains(t, content, "name: "+b.wantKey,
					"%s authenticates with %s: the manifest must wire it",
					b.model, b.wantKey)
				require.Contains(t, content, "key: "+b.wantEnv,
					"the secretKeyRef must name the %s key", b.wantEnv)
				require.Contains(t, content, "--from-literal="+b.wantEnv+"="+b.wantValue,
					"the kubectl comment must create exactly the key the env wires")

				for _, other := range allVendorKeys {
					if other == b.wantKey {
						continue
					}
					require.NotContains(t, content, other,
						"a %s scaffold must not claim it needs %s — that is the "+
							"assertion #1483 removes", b.model, other)
				}
				for _, other := range allVendorSecretKeys {
					if other == b.wantEnv {
						continue
					}
					require.NotContains(t, content, other,
						"the kubectl comment must not instruct a %s literal for %s",
						other, b.model)
				}
			})
		}
	}
}

// The generic `API_KEY: "your-api-key"` secrets example is gone from every
// llm-provider render, not just the gateway ones: for a big-3 model the real key
// is already wired above, so the example only offers a second, wrong name.
//
// Asserted on the whole file rather than a branch, and separately from the
// matrices above, because a fix applied only to the gateway arm would leave the
// big-3 renders still carrying it — and the big-3 matrix cannot see it, since
// `API_KEY` is a substring of the key those renders legitimately wire.
func TestHelmValues_NoGenericApiKeyExample(t *testing.T) {
	models := []string{"claude-sonnet-5", "gpt-4o", "gemini-2.5-flash",
		"bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0", "cohere/command-r-plus"}

	for _, language := range helmLanguages {
		for _, model := range models {
			t.Run(language+" "+model, func(t *testing.T) {
				content := renderHelmValues(t, language, model)
				require.NotContains(t, content, `API_KEY: "your-api-key"`,
					"the generic API_KEY example is the same fallback removed from the "+
						"TypeScript README in #1484 — it names a credential nothing reads")
				require.NotContains(t, content, "your-api-key")
			})
		}
	}
}

// The env block must be well-formed YAML in both branches. The gateway arm emits
// no `env:` key at all (nothing to wire), and the big-3 arm emits exactly one
// entry — a template whose whitespace control slipped could produce an `env:`
// with no items, which helm renders as null and the chart then fails on.
func TestHelmValues_EnvBlockShapePerBranch(t *testing.T) {
	for _, language := range helmLanguages {
		t.Run(language+" big-3", func(t *testing.T) {
			content := renderHelmValues(t, language, "anthropic/claude-sonnet-5")
			require.Contains(t, content, "\nenv:\n  - name: ANTHROPIC_API_KEY\n",
				"the env list must open immediately with its single entry")
			require.Equal(t, 1, strings.Count(content, "\n  - name: "),
				"exactly one credential may be wired")
		})
		t.Run(language+" gateway", func(t *testing.T) {
			content := renderHelmValues(t, language, "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0")
			require.NotContains(t, content, "\nenv:\n",
				"an empty `env:` key renders as null and breaks the chart — the "+
					"gateway branch must omit the key entirely")
			require.Contains(t, content, "# env:\n",
				"the commented reference skeleton must survive")
		})
	}
}

// The other half of #1483: llm-provider was not the only template wiring vendor
// keys. `llm-agent`, `api` and `basic` shipped the same `llm-secrets` block (and
// a generic `API_KEY: "your-api-key"` secrets example) in all three languages.
//
// `api` and `basic` are not LLM agents at all. `llm-agent` is one, but it reaches
// its model through mesh DI — `@mesh.llm(provider={"capability": "llm", ...})`,
// `mesh.llm({provider: {capability: "llm"}})`, `@MeshLlm(providerSelector =
// @Selector(capability = "llm"))`. The credential lives on the llm-provider agent
// it resolves to, and none of the three carries a vendor SDK in its dependency
// manifest to use one with. A key wired into the CONSUMER's pod is read by
// nothing.
//
// So the assertion is flat: a template that is not llm-provider may not name a
// vendor key, because none of them is in a position to know one. Same subtractive
// shape as the guards above — stop asserting something false.
var nonProviderTemplates = []string{"llm-agent", "api", "basic", "a2a-consumer"}

// renderNonProviderHelmValues scaffolds one of the non-llm-provider templates and
// returns its rendered helm-values.yaml. Defaults come from NewScaffoldContext so
// the render matches what `meshctl scaffold -t <template>` actually produces.
func renderNonProviderHelmValues(t *testing.T, language, template string) string {
	t.Helper()
	ctx := NewScaffoldContext()
	ctx.Name = "credential-guard"
	ctx.Description = "credential guard"
	ctx.Language = language
	ctx.OutputDir = t.TempDir()
	ctx.Port = 9400
	ctx.Template = template
	ctx.TemplateDir = templatesRoot(t)
	ctx.AgentType = ""
	ctx.ProviderTags = []string{"llm", "+claude"}
	require.NoError(t, NewStaticProvider().Execute(ctx))

	path := filepath.Join(ctx.OutputDir, ctx.Name, "helm-values.yaml")
	content, err := os.ReadFile(path)
	require.NoError(t, err, "rendered helm values %s", path)
	return string(content)
}

func TestHelmValues_NonProviderTemplatesWireNoVendorCredentials(t *testing.T) {
	for _, language := range helmLanguages {
		for _, template := range nonProviderTemplates {
			t.Run(language+" "+template, func(t *testing.T) {
				content := renderNonProviderHelmValues(t, language, template)

				for _, key := range allVendorKeys {
					require.NotContains(t, content, key,
						"a %s/%s scaffold has no vendor credential to hold: an "+
							"llm-agent resolves its provider through the mesh and "+
							"api/basic are not LLM agents at all, so wiring %s "+
							"sends the operator to configure something nothing reads",
						language, template, key)
				}
				for _, key := range allVendorSecretKeys {
					require.NotContains(t, content, key,
						"the kubectl comment still instructs a %s literal for %s/%s",
						key, language, template)
				}
				require.NotContains(t, content, "API_KEY",
					"naming any API key here, vendor-specific or generic, is the "+
						"assertion #1483 removes from %s/%s", language, template)
				require.NotContains(t, content, "your-api-key",
					"the generic secrets example names a credential nothing reads")
			})
		}
	}
}

// Removing the block must leave valid YAML, and specifically must not leave an
// `env:` key with nothing under it: helm parses that as null and the chart's
// range over it fails. The whole point of these files is to be applied, so they
// are parsed here rather than pattern-matched.
func TestHelmValues_NonProviderTemplatesParseWithNoEmptyEnv(t *testing.T) {
	for _, language := range helmLanguages {
		for _, template := range nonProviderTemplates {
			t.Run(language+" "+template, func(t *testing.T) {
				content := renderNonProviderHelmValues(t, language, template)

				var values map[string]interface{}
				require.NoError(t, yaml.Unmarshal([]byte(content), &values),
					"%s/%s helm values must parse", language, template)

				if env, ok := values["env"]; ok {
					require.NotNil(t, env,
						"`env:` with no items parses as null and breaks the chart — "+
							"omit the key instead of leaving it bare")
				}
				if secrets, ok := values["secrets"]; ok {
					require.NotNil(t, secrets,
						"`secrets:` with no items parses as null and breaks the chart")
				}
				require.NotContains(t, content, "\nenv:\n",
					"%s/%s must keep its env skeleton commented out — an active but "+
						"empty `env:` overrides the chart's base values with null",
					language, template)
			})
		}
	}
}
