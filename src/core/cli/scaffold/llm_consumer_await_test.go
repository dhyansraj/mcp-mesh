package scaffold

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

// The object `@mesh.llm` injects into a Python consumer is
// `_mcp_mesh/engine/mesh_llm_agent.py`'s `MeshLlmAgent`, whose `__call__` is
// `async def`, and `mesh_llm_agent_injector.py` has exactly one construction
// site for it — there is no sync variant of this proxy the way there is for
// `McpMeshTool` (SelfDependencyProxy). So `llm(...)` is a coroutine, always,
// and the only correct shape for the generated tool is `async def` + `await`.
//
// The scaffold shipped a sync `def` calling `llm(...)` bare (issue #1549), and
// nothing caught it because that shape *appears* to work: FastMCP's
// `function_tool.py` awaits an awaitable return value, so the one line the
// template happened to emit — `return llm(...)` as the final statement —
// round-trips. Anything a real agent does next does not:
//
//   - `response = llm(...)` then reading a field gets a coroutine attribute
//     error, and the tool returns None;
//   - two calls in sequence leak the first coroutine with a
//     "never awaited" RuntimeWarning;
//   - `f"{llm(...)}"` interpolates `<coroutine object ...>`.
//
// That is why this guard asserts the SHAPE (`async def`, every call awaited)
// rather than round-tripping one generated agent through a live provider: a
// behavioural test of the template's own line passes while the pattern it
// teaches is broken.
//
// Two constraints this file is built around, both learned from #1546:
//
//   - it renders through the real `scaffold llm` entry point, because a
//     hand-built ScaffoldContext does not populate what the subcommand does and
//     a guard on the wrong context proves nothing about what users get;
//   - the unawaited-call scan is scoped to the generated TOOL BODY. The rest of
//     the file legitimately contains `@mesh.llm(` and a sync `startup_check`,
//     and a whole-file ban would trip on prose that is not a call at all.

// llmCallSite matches an invocation of the injected agent: the bare name `llm`
// immediately followed by `(`. The word boundary keeps `mesh.llm(` (the
// decorator) and `MeshLlmAgent` from matching.
var llmCallSite = regexp.MustCompile(`\bllm\(`)

// scaffoldLLMConsumer runs the real `meshctl scaffold llm` for a vendor and
// response format and returns the generated Python entry file.
func scaffoldLLMConsumer(t *testing.T, vendor, responseFormat string) string {
	t.Helper()
	t.Chdir(findRepoRoot(t))

	out := t.TempDir()
	cmd := newScaffoldLLMCommand()
	cmd.SetOut(&bytes.Buffer{})
	cmd.SetErr(&bytes.Buffer{})
	require.NoError(t, cmd.Flags().Set("vendor", vendor))
	require.NoError(t, cmd.Flags().Set("lang", "python"))
	require.NoError(t, cmd.Flags().Set("name", "await-probe"))
	require.NoError(t, cmd.Flags().Set("output", out))
	require.NoError(t, cmd.Flags().Set("response-format", responseFormat))
	require.NoError(t, runScaffoldLLMConsumer(cmd, nil))

	content, err := os.ReadFile(filepath.Join(out, "await-probe", "main.py"))
	require.NoError(t, err)
	return string(content)
}

// generatedToolBody returns the `def` line of the generated LLM tool and the
// lines of its body. The signature spans several lines and closes on a line
// that starts in column 0 (`) -> str:`), so the split is: signature ends at the
// first line ending in `:`, and the body ends at the first non-empty line with
// no leading whitespace after that.
func generatedToolBody(t *testing.T, content, toolName string) (string, []string) {
	t.Helper()
	lines := strings.Split(content, "\n")

	start := -1
	for i, line := range lines {
		if strings.HasPrefix(line, "def "+toolName+"(") ||
			strings.HasPrefix(line, "async def "+toolName+"(") {
			start = i
			break
		}
	}
	require.NotEqualf(t, -1, start,
		"no definition of the generated tool %q in the rendered agent — the template "+
			"moved and this guard would otherwise pass by scanning nothing:\n%s",
		toolName, content)

	sigEnd := -1
	for i := start; i < len(lines); i++ {
		if strings.HasSuffix(strings.TrimRight(lines[i], " \t"), ":") {
			sigEnd = i
			break
		}
	}
	require.NotEqualf(t, -1, sigEnd, "unterminated signature for tool %q", toolName)

	end := len(lines)
	for i := sigEnd + 1; i < len(lines); i++ {
		trimmed := strings.TrimSpace(lines[i])
		if trimmed == "" {
			continue
		}
		if !strings.HasPrefix(lines[i], " ") && !strings.HasPrefix(lines[i], "\t") {
			end = i
			break
		}
	}

	return lines[start], lines[sigEnd+1 : end]
}

// The generated Python LLM consumer must be `async def` and must await every
// call it makes on the injected agent — including the commented media examples,
// which are the lines a reader is most likely to copy.
func TestScaffoldedPythonLLMConsumerAwaitsInjectedAgent(t *testing.T) {
	for _, vendor := range SupportedLLMVendors() {
		for _, responseFormat := range []string{"text", "json"} {
			t.Run(vendor+" "+responseFormat, func(t *testing.T) {
				content := scaffoldLLMConsumer(t, vendor, responseFormat)
				defLine, body := generatedToolBody(t, content, "await_probe")

				require.Truef(t, strings.HasPrefix(defLine, "async def "),
					"the generated LLM tool is a sync def, but the injected agent's "+
						"__call__ is async — every `llm(...)` in its body evaluates to a "+
						"coroutine (issue #1549): %s", defLine)

				calls := 0
				for _, line := range body {
					for _, loc := range llmCallSite.FindAllStringIndex(line, -1) {
						before := line[:loc[0]]
						if strings.HasSuffix(before, ".") {
							continue // mesh.llm(...) — the decorator, not a call
						}
						calls++
						require.Truef(t, strings.HasSuffix(before, "await "),
							"the generated tool calls the injected LLM agent without "+
								"awaiting it; `llm(...)` is a coroutine, so this line does "+
								"not produce a completion (issue #1549): %s",
							strings.TrimSpace(line))
					}
				}

				require.Positivef(t, calls,
					"found no call on the injected LLM agent in the generated tool body — "+
						"the guard passed by scanning nothing:\n%s", strings.Join(body, "\n"))
			})
		}
	}
}

// The commented media examples are teaching lines, not dead code: they carry
// the media argument shape a user copies. Pin them explicitly so a future edit
// cannot reintroduce a bare call there while the live `return` stays correct.
func TestScaffoldedPythonLLMConsumerMediaExamplesAreAwaited(t *testing.T) {
	content := scaffoldLLMConsumer(t, "claude", "text")
	_, body := generatedToolBody(t, content, "await_probe")

	commented := 0
	for _, line := range body {
		trimmed := strings.TrimSpace(line)
		if !strings.HasPrefix(trimmed, "#") || !llmCallSite.MatchString(trimmed) {
			continue
		}
		commented++
		require.Containsf(t, trimmed, "await llm(",
			"a commented example calls the injected LLM agent without awaiting it; "+
				"these are the lines a user uncomments (issue #1549): %s", trimmed)
	}

	require.Equalf(t, 2, commented,
		"expected the two commented media examples in the generated tool body, found %d — "+
			"the template changed and this pin needs revisiting", commented)
}
