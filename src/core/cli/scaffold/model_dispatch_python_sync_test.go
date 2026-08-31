package scaffold

import (
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

	entryRe := regexp.MustCompile(`"([\w_]+)":\s*(\w+)`)
	entries := entryRe.FindAllStringSubmatch(blockMatch[1], -1)
	require.NotEmpty(t, entries, "parsed no vendors out of the _handlers mapping")

	// A handler ships a native adapter exactly when it overrides
	// `_native_module` — the same derivation `native_dispatch_vendors()`
	// performs at runtime. A vendor mapped to a handler that does not override
	// it takes the LiteLLM path and must NOT appear in nativeVendorPrefixes.
	pythonNative := map[string]bool{}
	nativeByClass := map[string]bool{}
	for _, e := range entries {
		vendor, class := e[1], e[2]

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
