package scaffold

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

// Issue #1483. The Python llm-provider README rendered its two tag sites from
// `.Tags` — the raw CONTEXT tags, which the `--template llm-provider` path never
// populates. The config table showed an empty Tags cell and the consumer example
// showed `"tags": null`, in a directory whose `main.py` beside it registered the
// real family tags.
//
// The fix routes both sites through the same `providerTags` func `main.py.tmpl`
// uses, so the README cannot state a different answer from the code it documents.
// That is what is pinned here: not a literal tag list (model_dispatch_test owns
// those), but the AGREEMENT between the two files in the same scaffold.

// readmeTagModels covers both resolver branches, because the two files could
// agree in one and diverge in the other: a big-3 family, a gateway model whose
// family survives the prefix, and a gateway model with no family at all.
var readmeTagModels = []struct {
	model    string
	wantTags []string
}{
	{"anthropic/claude-sonnet-5", []string{"llm", "claude", "anthropic", "provider"}},
	{"gpt-4o", []string{"llm", "openai", "gpt", "provider"}},
	{"gemini-2.5-flash", []string{"llm", "gemini", "google", "provider"}},
	{"bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0", []string{"llm", "claude", "anthropic", "provider"}},
	{"vertex_ai/gemini-2.5-flash", []string{"llm", "gemini", "google", "provider"}},
	{"bedrock/meta.llama3-70b-instruct-v1:0", []string{"llm", "provider"}},
	{"cohere/command-r-plus", []string{"llm", "provider"}},
}

func TestPythonProviderReadme_ShowsTheTagsTheAgentRegisters(t *testing.T) {
	for _, m := range readmeTagModels {
		t.Run(m.model, func(t *testing.T) {
			readme := renderProvider(t, "python", m.model, "README.md")
			main := renderProvider(t, "python", m.model, "main.py")

			// What the agent actually registers. Asserted against main.py first
			// so a change to the tag source fails here rather than silently
			// re-pointing the README at a new wrong answer.
			registered := tagsMarker("python", m.wantTags)
			require.Contains(t, main, registered,
				"main.py must register the %v tags for %s", m.wantTags, m.model)

			// The config table.
			require.Contains(t, readme,
				"| Tags | "+strings.Join(m.wantTags, ", ")+" | Discovery tags |",
				"the config table must list the tags main.py registers, not the "+
					"raw context tags — the llm-provider path leaves those empty, "+
					"which is how the cell rendered blank")

			// The consumer example. The literal is rendered by the same
			// expression main.py uses, so it must come out byte-identical to the
			// list in the decorator beside it.
			require.Contains(t, readme, `"tags": [`+quotedTagList(m.wantTags)+`]`,
				"the consumer example must pin the tags this provider registers; "+
					"`\"tags\": null` is what the raw context rendered")

			require.NotContains(t, readme, `"tags": null`,
				"the README read tags off a field the llm-provider path never sets")
			require.NotContains(t, readme, "| Tags |  |",
				"an empty Tags cell is the same defect wearing the table's clothes")
		})
	}
}

// quotedTagList renders `"a", "b"` — the inner text shared by the Python
// decorator literal and the README's consumer example.
func quotedTagList(tags []string) string {
	quoted := make([]string, len(tags))
	for i, tag := range tags {
		quoted[i] = `"` + tag + `"`
	}
	return strings.Join(quoted, ", ")
}
