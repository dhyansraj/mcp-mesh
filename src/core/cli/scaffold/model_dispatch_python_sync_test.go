package scaffold

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

// nativeVendorPrefixes is a hand-copy of a table the Python runtime owns, and
// the two comments saying so were the only thing holding them together. Issue
// #1551 gave the Python side a second consumer — a startup assertion that
// refuses to start a provider whose declared model needs the optional
// `mcp-mesh[litellm]` extra — so drift is no longer just a wasted pip layer.
// A vendor that gains a native adapter in Python but not here makes the
// scaffolder pin an extra the agent will never load; the reverse direction
// generates an agent WITHOUT the pin that now fails to start at all.
//
// This test reads the Python source and reconstructs
// `ProviderHandlerRegistry.native_dispatch_vendors()` from it, so the halves
// cannot drift silently: adding a vendor on either side alone fails the build.
//
// It reconstructs rather than imports for the same reason the duplicate exists
// — `meshctl` must decide this with no Python available. Parsing is therefore
// deliberately strict: anything it cannot read is a failure, never a skip. A
// moved or restructured file must be noticed here, not quietly waved through.
func TestGoNativeVendorsMatchPythonRegistry(t *testing.T) {
	const registryPath = "../../../runtime/python/_mcp_mesh/engine/provider_handlers/provider_handler_registry.py"

	registrySrc, err := os.ReadFile(registryPath)
	require.NoError(t, err,
		"cannot read the Python provider registry at %s. If it moved, update "+
			"this path — do not delete this test: it is the only thing keeping "+
			"nativeVendorPrefixes in sync with the runtime.", registryPath)

	// `from .claude_handler import ClaudeHandler` -> ClaudeHandler lives in
	// claude_handler.py. Needed because whether a handler dispatches natively
	// is a property of its own module (does it override `_native_module`),
	// not of the registry.
	classModule := map[string]string{}
	importRe := regexp.MustCompile(`(?m)^from \.(\w+) import (\w+)$`)
	for _, m := range importRe.FindAllStringSubmatch(string(registrySrc), -1) {
		classModule[m[2]] = m[1]
	}
	require.NotEmpty(t, classModule,
		"parsed no handler imports out of %s — the parse, not the runtime, "+
			"is what broke", registryPath)

	// The `_handlers` mapping, up to its closing brace.
	handlersBlock := regexp.MustCompile(`(?s)_handlers: dict\[str, type\[BaseProviderHandler\]\] = \{(.*?)\n    \}`)
	blockMatch := handlersBlock.FindStringSubmatch(string(registrySrc))
	require.Len(t, blockMatch, 2,
		"could not locate the _handlers mapping in %s", registryPath)

	entries, err := parsePythonHandlerEntries(blockMatch[1])
	require.NoError(t, err,
		"could not read the _handlers mapping in %s: %v", registryPath, err)
	require.NotEmpty(t, entries, "parsed no vendors out of the _handlers mapping")

	// A handler ships a native adapter exactly when it overrides
	// `_native_module` — the same derivation `native_dispatch_vendors()`
	// performs at runtime. A vendor mapped to a handler that does not override
	// it takes the LiteLLM path and must NOT appear in nativeVendorPrefixes.
	pythonNative := map[string]bool{}
	nativeByClass := map[string]bool{}
	for _, e := range entries {
		vendor, class := e.vendor, e.handlerClass

		isNative, seen := nativeByClass[class]
		if !seen {
			module, ok := classModule[class]
			require.True(t, ok,
				"handler %q is mapped in _handlers but never imported in %s",
				class, registryPath)

			handlerSrc, err := os.ReadFile(
				filepath.Join(filepath.Dir(registryPath), module+".py"))
			require.NoError(t, err, "cannot read handler module for %q", class)

			isNative = strings.Contains(string(handlerSrc), "def _native_module(")
			nativeByClass[class] = isNative
		}

		if isNative {
			pythonNative[vendor] = true
		}
	}

	require.NotEmpty(t, pythonNative,
		"reconstructed an EMPTY native-vendor set from %s. Either every native "+
			"adapter was removed, or `def _native_module(` is no longer how a "+
			"handler declares one — in which case this test's derivation needs "+
			"updating, not deleting.", registryPath)

	require.Equal(t, sortedKeys(pythonNative), sortedKeys(nativeVendorPrefixes),
		"nativeVendorPrefixes has drifted from the Python provider registry.\n"+
			"  Go   (%s)\n"+
			"  Py   (%s -> native_dispatch_vendors())\n"+
			"A vendor present only in Python makes scaffolded agents miss the "+
			"mcp-mesh[litellm] pin, and since #1551 such an agent fails to "+
			"start. A vendor present only here pins an extra it never loads.",
		"src/core/cli/scaffold/model_dispatch.go", registryPath)
}

// TestPythonHandlerEntriesRejectUnreadableLines is the test for the test above.
//
// TestGoNativeVendorsMatchPythonRegistry compares a set it RECONSTRUCTS, so its
// green is only worth as much as the reconstruction: an entry it cannot read is
// an entry it does not compare, and nothing about the result would say so. The
// forms below are not hypothetical Python — they are ordinary things a
// maintainer might write in that mapping — and each one must stop the run
// rather than shrink the set it is checking.
func TestPythonHandlerEntriesRejectUnreadableLines(t *testing.T) {
	unreadable := map[string]string{
		"parenthesized value":  `"anthropic": (ClaudeHandler),`,
		"call expression":      `"anthropic": pick_handler(),`,
		"attribute access":     `"anthropic": handlers.ClaudeHandler,`,
		"conditional value":    `"anthropic": ClaudeHandler if x else GenericHandler,`,
		"value on next line":   `"anthropic":`,
		"dict spread":          `**_EXTRA_HANDLERS,`,
		"two entries one line": `"anthropic": ClaudeHandler, "openai": OpenAIHandler,`,
		"single-quoted key":    `'anthropic': ClaudeHandler,`,
	}

	for name, line := range unreadable {
		t.Run(name, func(t *testing.T) {
			block := "\n        \"openai\": OpenAIHandler,\n        " + line + "\n"

			entries, err := parsePythonHandlerEntries(block)

			require.Error(t, err,
				"parsed %q as if the mapping held only the entries it "+
					"recognized. The vendor on that line would be missing from "+
					"the reconstructed set and the drift comparison would pass "+
					"without it — the failure this guard exists to make "+
					"impossible.", line)
			require.Nil(t, entries)
			require.Contains(t, err.Error(), strings.TrimSpace(line),
				"the error must name the line that could not be read")
		})
	}
}

// The forms the parser does accept, pinned so "reject everything" is not a way
// to pass the test above. `"gemini": GeminiHandler,  # comment` is the shape
// two of the four real entries are written in today.
func TestPythonHandlerEntriesReadsTheFormsTheRegistryUses(t *testing.T) {
	block := "\n" +
		"        # Built-in vendor mappings.\n" +
		"        \"anthropic\": ClaudeHandler,\n" +
		"\n" +
		"        \"gemini\": GeminiHandler,  # Google AI Studio (GOOGLE_API_KEY)\n" +
		"        \"vertex_ai\": GeminiHandler\n"

	entries, err := parsePythonHandlerEntries(block)

	require.NoError(t, err)
	require.Equal(t, []pythonHandlerEntry{
		{vendor: "anthropic", handlerClass: "ClaudeHandler"},
		{vendor: "gemini", handlerClass: "GeminiHandler"},
		{vendor: "vertex_ai", handlerClass: "GeminiHandler"},
	}, entries)
}

// pythonHandlerEntry is one `"vendor": HandlerClass,` line of the Python
// registry's `_handlers` mapping.
type pythonHandlerEntry struct {
	vendor       string
	handlerClass string
}

// handlerEntryRe matches a whole entry LINE, anchored at both ends, with an
// optional trailing comma and an optional trailing `# comment`.
var handlerEntryRe = regexp.MustCompile(`^"([\w_]+)":\s*(\w+),?(?:\s*#.*)?$`)

// parsePythonHandlerEntries reads every entry out of the `_handlers` block,
// and fails on any line it cannot read rather than skipping it.
//
// That distinction is the whole function. A `FindAllStringSubmatch` over the
// block returns only what matched and says nothing about the rest, so an entry
// written in a form the pattern does not cover — a parenthesized or
// multi-line value, a call expression, a `**` spread, a conditional insert —
// is silently dropped. That vendor never enters the reconstructed set, and the
// comparison against nativeVendorPrefixes then passes while never having
// checked it: a guard reporting green about a vendor it did not see is worse
// than no guard, because it also stops anyone from looking.
//
// Blank lines and whole-line comments are the only things skipped. Anything
// else is an error naming the offending line, so the fix (write the entry
// plainly, or teach the parser the new form) is a decision someone makes on
// purpose.
func parsePythonHandlerEntries(block string) ([]pythonHandlerEntry, error) {
	var entries []pythonHandlerEntry
	for _, rawLine := range strings.Split(block, "\n") {
		line := strings.TrimSpace(rawLine)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		m := handlerEntryRe.FindStringSubmatch(line)
		if m == nil {
			return nil, fmt.Errorf(
				"unreadable line in the _handlers mapping:\n  %s\n"+
					"Every entry must parse here — an unparsed one is dropped "+
					"from the reconstructed vendor set, and the drift check "+
					"then passes without ever having compared that vendor. "+
					"Either write it as a plain `\"vendor\": HandlerClass,` "+
					"line, or teach parsePythonHandlerEntries the new form",
				line)
		}
		entries = append(entries, pythonHandlerEntry{vendor: m[1], handlerClass: m[2]})
	}
	return entries, nil
}

func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k, v := range m {
		if v {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	return keys
}
