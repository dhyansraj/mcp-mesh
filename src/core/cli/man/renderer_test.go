package man

import (
	"strings"
	"testing"
)

func TestStyleInline(t *testing.T) {
	r := NewRenderer(false)

	testCases := []struct {
		name string
		line string
		want string
	}{
		{
			// Regression: audit.md:7. Two snake_case code spans on one line had
			// their underscores paired across the spans by the italic pass.
			name: "two snake_case code spans keep their underscores",
			line: "records it as a `dependency_resolved` (or `dependency_unresolved`) event",
			want: "records it as a " + green + "dependency_resolved" + reset +
				" (or " + green + "dependency_unresolved" + reset + ") event",
		},
		{
			name: "single snake_case code span keeps its underscore",
			line: "the `agent_id` field",
			want: "the " + green + "agent_id" + reset + " field",
		},
		{
			name: "underscore italic outside code still italicises",
			line: "this is _emphasised_ text",
			want: "this is " + italic + "emphasised" + reset + " text",
		},
		{
			name: "asterisk italic outside code still italicises",
			line: "this is *emphasised* text",
			want: "this is " + italic + "emphasised" + reset + " text",
		},
		{
			name: "bold still bolds",
			line: "this is **strong** text",
			want: "this is " + bold + "strong" + reset + " text",
		},
		{
			name: "underscore bold still bolds",
			line: "this is __strong__ text",
			want: "this is " + bold + "strong" + reset + " text",
		},
		{
			name: "italic outside code coexists with snake_case code spans",
			line: "_note_: `agent_id` and `agent_name` differ",
			want: italic + "note" + reset + ": " + green + "agent_id" + reset +
				" and " + green + "agent_name" + reset + " differ",
		},
		{
			name: "link with underscores in url still renders as a link",
			line: "see [the docs](https://example.com/a_b_c/d_e) for more",
			want: "see " + underline + cyan + "the docs" + reset + " for more",
		},
		{
			name: "link with underscores in text still renders as a link",
			line: "see [dependency_injection](https://example.com/di) for more",
			want: "see " + underline + cyan + "dependency_injection" + reset + " for more",
		},
		{
			name: "code span containing an asterisk is not mangled",
			line: "the `a*b` expression",
			want: "the " + green + "a*b" + reset + " expression",
		},
		{
			name: "two code spans containing asterisks are not mangled",
			line: "compare `a*b` with `c*d`",
			want: "compare " + green + "a*b" + reset + " with " + green + "c*d" + reset,
		},
		{
			name: "code span containing double asterisks is not bolded",
			line: "the `**literal**` token",
			want: "the " + green + "**literal**" + reset + " token",
		},
		{
			name: "code span containing markdown link syntax is not linkified",
			line: "write `[text](url)` verbatim",
			want: "write " + green + "[text](url)" + reset + " verbatim",
		},
		{
			name: "code and bold and italic combine",
			line: "**bold** `snake_case_name` _italic_",
			want: bold + "bold" + reset + " " + green + "snake_case_name" + reset +
				" " + italic + "italic" + reset,
		},
		{
			name: "plain line is untouched",
			line: "nothing to style here",
			want: "nothing to style here",
		},
		{
			name: "raw NUL in content cannot forge a placeholder",
			line: "spooky \x000\x00 `agent_id`",
			want: "spooky 0 " + green + "agent_id" + reset,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			got := r.styleInline(tc.line)
			if got != tc.want {
				t.Errorf("styleInline(%q)\n got: %q\nwant: %q", tc.line, got, tc.want)
			}
		})
	}
}

// TestStyleInlineNoStrayItalicBetweenCodeSpans guards the specific corruption
// signature: an italic escape emitted between two code spans on the same line.
func TestStyleInlineNoStrayItalicBetweenCodeSpans(t *testing.T) {
	r := NewRenderer(false)

	lines := []string{
		"as a `dependency_resolved` (or `dependency_unresolved`) event in the log",
		"set `MCP_MESH_LOG_LEVEL` and `MCP_MESH_DEBUG_MODE` together",
		"`retry_on` accepts the same values as `max_duration`",
		"fields `agent_id`, `capability_name`, and `resolved_at`",
	}

	for _, line := range lines {
		t.Run(line, func(t *testing.T) {
			got := r.styleInline(line)
			if strings.Contains(got, italic) {
				t.Errorf("stray italic escape in styleInline(%q): %q", line, got)
			}
			// Every underscore in the source must survive into the output.
			if want, have := strings.Count(line, "_"), strings.Count(got, "_"); want != have {
				t.Errorf("styleInline(%q) dropped underscores: want %d, have %d (%q)",
					line, want, have, got)
			}
		})
	}
}

// Golden corpus sizes.
//
// #1409: the two corpus tests below used to report what they had measured via
// t.Logf, so the figures quoted in #1392 and in the v3.3.2 release notes (83
// corrupted code spans, 432 unstyled list lines) had no in-tree anchor —
// nothing failed when they changed. They had already drifted: the list-line
// figure was exactly 432 at the commit that fixed #1392 and is 433 today,
// because two docs PRs added content afterwards.
//
// Exact matches, not floors. A floor cannot tell you the corpus SHRANK, and a
// topic quietly dropping out of ListGuides is the one failure that would gut
// every corpus test in this file while leaving them green.
//
// A docs change that moves these is expected to move them — update the
// constant in the same commit and check the delta is the size you intended.
// #1401 (docs): +28 inline code spans. These tests sample the DEFAULT variant
// of each listed topic, so the many `_java` / `_typescript` edits in that
// change are invisible here; the delta is entirely `a2a.md` (+7, the
// cross-runtime positional-binding note plus the zero-based `deps[0]`
// clarification) and `upgrading.md` (+21, the new "3.4.0 — Dependency
// injection is positional everywhere" section, including the `@MeshTool`
// `@MeshInject` caveat and the on-3.3 qualifications). Neither added a
// markdown list line, so the two list goldens are unmoved.
//
// #1401 review follow-up: +4 more, all in `upgrading.md`. The "one dependency
// cannot change meaning" exemption was wrong in both runtimes and was rewritten
// to name the two real cases — a TypeScript handler still taking a
// capability-keyed callback (`async (req, res, { cap }) => ...`) and a Java
// sole `@MeshInject` that names a different capability (`null` on 3.3, a boot
// failure on 3.4). Four code spans in one replaced paragraph; still no list
// line, and the `text` fence labels added in the same change are skipped by
// these tests, which treat any ``` line as a block delimiter.
// #1430: +7 / +4 / +7, all in `audit.md`. The tiebreaker prose became the
// canonical description of resolver selection — a numbered score/version/agent-ID
// list, plus a "registry does not load balance" section whose two deployment
// shapes (Service DNS vs auto-detected pod IP) are bullets naming
// `MCP_MESH_HTTP_HOST` and `agent.advertisedHost`. Bullets, not a table: the
// renderer passes `|` lines through raw, so table-cell markup would print
// literally.
// #1423: +12 / +12 / +2, all in `upgrading.md`. Two bullets appended to "Helm
// Mechanics", both list lines carrying markup, so every span they add lands in
// all three counts. The Tempo one (8 spans) documents the
// `mcp-mesh-tempo.tempo.persistence.enabled` default flipping to `false` and
// the PVC deletion that flip causes on upgrade; the Grafana one (4 spans)
// backfills the `resource-policy: keep` note that #1426 landed in `docs/` but
// not here, since the Tempo bullet contrasts against it.
// #1414: +29 / +2 / +0. `upgrading.md` +18 for the new "3.5.0 — Helm chart
// upgrade order" section, which states the 3.3.x → 3.4.x → 3.5.0 sequence the
// `namespaceCreate` default flip requires, plus a reworded `commonAnnotations`
// bullet in "Helm Mechanics" (the +2 that also lands in the list golden — a
// rewrite of an existing list line, so no new line and the third golden is
// unmoved); `deployment.md` +11 for the same upgrade constraint restated where
// the install recipe lives, plus the rewrite of the paragraph that used to
// explain `--set namespaceCreate=false` (now redundant, and dropped from every
// recipe). The new section's version table contributes nothing: a `|` line is
// skipped by all three tests.
// #1383: +1 / +0 / +0. `llm.md`'s LiteLLM note is rewritten for the base
// install losing `litellm`: the "moving to an opt-in extra" wording becomes a
// statement of fact plus a `pip install 'mcp-mesh[litellm]'` block (fenced, so
// it contributes nothing), and the long-tail bullet gains the `[litellm]`
// extra. That bullet is the whole delta — the reworked paragraph swaps spans
// one-for-one. The two list goldens are unmoved because the new span sits on
// the bullet's wrapped continuation line, which is not itself a list line.
// #1467/#1468 follow-up: +12 / +10 / +3, all in `deployment.md`. The probe
// split landed in the chart with no doc surface saying which probe belongs on
// which path, so anyone writing their own manifests would repeat what the chart
// used to do — point everything at `/health` — and reproduce the restart loop.
// Three bullets under "Health Checks" name the endpoints (`/livez` for liveness
// and startup, `/ready` for readiness, `/health` for diagnostics only), which is
// the whole list delta; the two remaining spans are the closing sentence that
// names the two paths a liveness probe must not use. The `_java` and
// `_typescript` variants carry the same three bullets, but their `/ready` and
// `/health` lines and their closing reason are written to what those runtimes
// actually return. That was "no user health check; TypeScript's `/health` is a
// fixed 200" when this landed and is no longer true of either: #1474/#1475 gave
// Java a user check, #1478/#1487 made TypeScript's `/ready` and `/health`
// reflect its verdict, and #1488 exempted a Java gateway's `/ready` from it.
// The variants have been rewritten to match; do not read the superseded
// parenthetical as current behaviour. None of that moves these constants: they
// sample only the default variant, so edits confined to a `_java` /
// `_typescript` file are invisible here and a review of those files cannot lean
// on this test.
// #1472 follow-up: +25 / +0 / +0, all in `health.md`. The default variant
// documented `health_check` without saying what an unhealthy verdict DOES,
// while both siblings covered it — so the most-read page for the primary
// runtime omitted the whole feature. It gains four sections: withdrawal (the
// heartbeat stops, the registry withdraws, resolution reroutes) with the
// startup-seed exemption, the probe endpoints, `degraded` splitting the two
// surfaces, and the route/A2A case. Itemised so the next mover knows the bar:
// intro 2, "one check per agent" 5, startup seed 1, probes 7, explicit-unhealthy
// 5, `degraded` 3, route/A2A 2 = 25 added, 0 removed. The two list goldens held
// because every added paragraph is prose — not one new bullet — and those tests
// count only list lines.
// #1492 follow-up: +1 / +0 / +0, in `health.md`. The Python runtime now honours
// `MCP_MESH_HEALTH_CHECK_TTL`, so the default variant's `health_check_ttl`
// sentence closes with the same override clause both siblings already carried;
// that one new inline span is prose, so the list goldens hold.
// #1491 follow-up: +3 / +0 / +0, in `health.md`. A Python `@mesh.route` /
// `@mesh.a2a` gateway served none of the three probe endpoints, so the
// route/A2A section could only say the health check never runs there — it
// could not say what a probe hits. Now that both gateway pipelines register
// them on the user's own FastAPI app, that section states what each one
// reports (`/livez`, `/ready`, `/health` — the whole delta) and that a path
// the application already defines wins. Both sentences are prose, so the list
// goldens hold.
// #1498 follow-up: +12 / +3 / +2, all in `deployment.md`. The three probe
// bullets said which endpoint each probe belongs on but never showed a probe
// stanza, so the contract existed only for people who read prose and never
// wired a manifest — and the closing sentence handed the whole subject to the
// Helm chart, which is exactly the reader who does not need it. A new "Probe
// Wiring" section carries the stanza (fenced, so it contributes nothing) plus
// the rule and the two ways it is got wrong. The delta: the never-point
// paragraph 5 (`livenessProbe`, `startupProbe`, `/ready`, `/health`,
// `health_check`), the `livenessProbe: /health` bullet 2 (with
// `failureThreshold`), the `startupProbe: /ready` bullet 1, and the closing
// diagnostic sentence 4 (`/health`, `kubectl exec`, `checks`, `errors`) = 12.
// Only the two bullets are list lines, contributing 3 spans across 2 lines to
// the other goldens. The `_java` and `_typescript` variants gain the same
// section written to what those runtimes return — Java's endpoints answer 503
// until the mesh runtime is up, and TypeScript's `/health` only started
// answering 503 in 3.5.2 — and neither moves these constants, which sample the
// default variant alone.
// #1499 follow-up: +5 / +0 / +0, in `deployment.md`. #1494 gave Python route
// and A2A gateways `/livez`, `/ready` and `/health` for the first time, with a
// provider's semantics inverted: `health_check` never runs, `/ready` reports
// runtime state alone and `/health` is a fixed 200. The page said `/ready`
// "reflects your `health_check`" unqualified, so it described a provider to
// the gateway operator reading it while writing a manifest, and it was the one
// deployment variant with no carve-out — `_typescript` and `_java` both carry
// one. The `/ready` bullet gains "on a provider agent" (no new span) and a
// carve-out paragraph follows the endpoint list: the exception 5
// (`@mesh.route`, `@mesh.a2a`, `health_check`, `/ready`, `/health`) = 5. It is
// prose, not a bullet, so the two list goldens hold.
// RFC #1502 step 2 follow-up: +2 / +3 / +1, split between `deployment.md`
// (+1 / +3 / +1) and `health.md` (+1 / +0 / +0). `/ready` stopped reflecting
// the health verdict on every agent type and the chart repointed
// `startupProbe` from `/livez` to `/startupz`, so both pages described
// behaviour the runtimes no longer have.
//
// `deployment.md`: the endpoint list goes from three bullets to four — the new
// `/startupz` bullet is 3 spans (`/startupz`, `startupProbe`, `startup_check`)
// and the `/livez` bullet loses `startupProbe`, which is the whole +2 on the
// list goldens and the +1 markup list line. The rewritten `/ready` and
// `/health` bullets swap spans one-for-one. In prose, the two "never point
// liveness at" sentences shed `/ready` and `health_check` and the closing
// diagnostic sentence gains `health_check` back, netting 0; the `startupProbe:
// /ready` bullet gains `/startupz`, which is the remaining +1 on both the
// inline and list goldens. The stanza's `path:` change is fenced, so it
// contributes nothing.
//
// `health.md`: the two sentences that said a failing check 503s `/ready` are
// rewritten to say it 503s `/health` alone. Both swap spans one-for-one except
// the `degraded` sentence, which gains one `/health` explaining why the
// diagnostic endpoint is free to carry a status code — the single inline span.
// Prose throughout, so its list goldens hold.
//
// The `_java` and `_typescript` variants of both pages were rewritten the same
// way and, as ever, move nothing here: these constants sample the default
// variant alone, so a review of those files cannot lean on this test.
// RFC #1502 step 3 follow-up: +12 / +0 / +0, in `health.md` and
// `deployment.md`. Route and A2A agents stopped being exempt from the health
// check, so both pages that stated the exemption described behaviour the
// runtimes no longer have.
//
// `health.md`: the "Route and A2A Agents" section goes from two paragraphs to
// three. The first swaps "never run the check" for "run it on the same timer",
// gaining `/ready` (the endpoint whose 200 is what makes withdrawing a gateway
// safe) = +1. A new middle paragraph says a gateway cannot declare one yet,
// because `health_check` is an `@mesh.agent` argument and that decorator
// cannot share a process with `@mesh.route` or `@mesh.a2a` = +4. The endpoint
// paragraph swaps its `/health` clause one-for-one. Prose throughout, so the
// two list goldens hold.
//
// `deployment.md`: the carve-out sentence itself nets ZERO — it trades
// `/health` ("stays 200") for `/ready` ("stays 200, so the pod keeps its
// Service endpoints") and keeps its other three spans. The +7 is the paragraph
// after it, which states the gap the runtime change leaves in Python: the
// hooks are `@mesh.agent` arguments (`startup_check`, `health_check`,
// `@mesh.agent` = +3) and that decorator cannot share a process with
// `@mesh.route` or `@mesh.a2a` (+2), so the examples above are `@mesh.agent`
// only (+1) and `meshctl man health` carries the detail (+1). Python-only, so
// the `_java` and `_typescript` deployment pages do not get it — and they are
// not sampled here anyway.
// RFC #1502 step 4 follow-up: +4 / +0 / +0, split evenly between `health.md`
// and `deployment.md`. Both said Python "cannot yet" carry a gateway hook.
// Issue #1506 closed that as BY DESIGN, so "yet" promised a fix that is not
// coming, and both pages are rewritten to state the design instead: mesh gives
// a gateway dependency injection, not lifecycle management, so its startup
// validation is its own — check the configuration at boot and exit non-zero.
//
// `health.md`: two paragraphs, +1 each. The declaration paragraph swaps its
// four spans one-for-one and gains `CrashLoopBackOff`, the thing a gateway gets
// instead of the hook. The endpoint paragraph went from three endpoints to
// four — step 1 added `/startupz` and this page never counted it — which is the
// other +1.
//
// `deployment.md`: one paragraph, +2. It keeps all seven of its spans (the
// `#1506` citation stays; a closed issue carrying the rationale is a fine
// reference) and gains `CrashLoopBackOff` plus the second `startup_check` that
// names what it stands in for.
//
// Prose in both cases, so the two list goldens hold. The `_java` and
// `_typescript` variants of both pages gained the same design statement, plus
// two facts neither had: a bare `mesh.route()` app serves none of the four
// paths, and a Java `@GetMapping` for any of the four is an ambiguous mapping
// that fails the boot. As ever they move nothing here — these constants sample
// the default variant alone, so a review of those files cannot lean on this
// test.
// Issue #1509: +7 / +0 / +0, all of it in `tutorial.md`'s "Health probes"
// section, which predates #1468 and said the chart wires liveness and
// readiness to `/health`. It had one span, `/health`, and now has eight: the
// three probes with the endpoint each is actually wired to, `/health` as the
// one nothing probes, and `meshctl man deployment` for the stanzas. The
// replacement for the restart claim — heartbeat pause, age-out, no restart —
// is plain prose and adds none. Prose throughout, so the list goldens hold.
// The `docs/tutorial/day-10-whats-next.md` twin carries the same correction at
// tutorial length and is not sampled here.
// Issue #1517: +2 / +0 / +0, both in `health.md`'s one-paragraph description of
// what a check may return, which now states the parsing rules the runtimes
// agreed on: `None` (the new span) reads as an absent status, and a result
// carrying only `checks` (the second span) is reporting success. "sync or
// async", case-insensitivity and whitespace trimming are prose and add none.
// The `_typescript` variant gained the same sentence with `null` in place of
// `None`, and as ever moves nothing here — these constants sample the default
// variant alone.
// Issue #1515: -2 / +0 / +0, both of them the word `degraded` leaving
// `health.md`'s "Only an Explicit Unhealthy Withdraws the Agent" section. RFC
// #1515 makes the return contract binary, so per the project's deprecation
// convention the value comes out of the teaching surface entirely and the
// runtime warning is the discovery path. Both paragraphs keep their meaning and
// state it as a consequence instead: a check that raises "keeps heartbeating
// and stays in dependency resolution", and "those verdicts" show on the
// diagnostic surface only. No span is added in either — the removals are the
// whole delta. The `_java` and `_typescript` variants lost the same two,
// `deployment_java.md` one and `deployment_typescript.md` two (one of them the
// `degraded`/`unhealthy` pair in "answers 503 while the check reports ...",
// which becomes the single `healthy` of "whenever the check is not reporting
// ..."). None of those five files are sampled here — these constants sample
// the default variant alone, and `deployment.md` is untouched.
//
// The same issue ADDS a "When Every Provider Withdraws" section to all three
// health pages — the answer to RFC #1515's open question 1 (no floor, and a
// registry warning when a capability drops to zero providers), recorded where
// the operator who sees that warning will look. It is deliberately span-free:
// it names no identifier, no endpoint and no env var, only behaviour, so the
// three goldens below are unmoved by it.
// Issue #1536: +4 / +0 / +0, all four in a new "Tracing at More Than One
// Replica" section in `registry.md`. That page claimed multi-replica needed no
// additional configuration, which holds for the default stream-through
// exporter (Tempo reassembles by trace ID) and not for correlation mode, which
// correlates in one process's memory. The added spans are
// `TRACE_EXPORTER_TYPE=console`, `json`, `meshctl trace <id>` and
// `MCP_MESH_TRACE_CONSUMER_GROUP`, all in prose. The section's own bullet-free
// shape plus the one edited bullet above it ("No in-memory registration
// state", a word added to existing prose) leave both list goldens unmoved.
// The same issue documents `MCP_MESH_TRACE_CONSUMER_GROUP` in
// `observability.md` as a table row and in `environment.md` inside the bash
// fence; renderStyled takes other branches for both, so neither is sampled
// here.
// Issue #1556: +6 / +0 / +0, one added paragraph in `health.md` saying what a
// `checks` value may be. The page had described the result's `status` in
// detail and never the map beside it, and a non-bool in there — a status
// string, a nested dict, both of which this repo's own docs showed — used to
// escape the health path as a validation error and leave the agent serving
// `/livez` and `/startupz` 200 while registering nowhere. The runtime now
// drops the value and reports it, so the page states the type. The six spans
// are `checks`, the `True`/`False` it maps to, `"ok"` as the value that is
// neither (the nested dict beside it is named in prose and adds none),
// `errors` where the rejection lands, and the `health_check_checks_type:
// False` entry that marks it. The closing clause — the verdict the check
// returned still stands — is prose and adds none, and is the one place this
// deviates from #1539's "read the verdict, do not override it": a typo in
// `checks` must not re-admit an agent that returned unhealthy. Prose, not a
// list item, so the two list goldens hold.
//
// The marker is Python's alone (`health_check_checks_type` exists in
// `health_check_manager.py` and in no other runtime), so the `_java` and
// `_typescript` health pages did not get the sentence and the variant golden
// in `variant_corpus_test.go` is unmoved — the case the note below describes,
// in reverse.
//
// Issues #1561/#1562: +7 / +0 / +0, all of it in `jobs.md`, and it splits into
// two unrelated halves.
//
// +3 is the correction itself. The consumer-side passage said the parameter
// NAME picks the `MeshJobSubmitter` slot. It does not: `_prepare_injection_kwargs`
// pairs `dependencies[i]` to the i-th eligible slot positionally and branches on
// the `MeshJob` annotation alone ("Param NAME does not matter; the binding is
// positional"), so the Notes bullet was rewritten and gains `MeshJob` twice, a
// third `McpMeshTool`, and `meshctl man dependency-injection` for the pairing
// rule, against the `task=True` span the old claim needed and no longer does.
//
// +4 is a rendering defect this test could not see. renderStyled styles inline
// code per LINE, so a span wrapped across a break renders as literal backticks
// and is not a span at all. This page had four: the two `meshctl man
// dependency-injection` citations (one of them introduced by the fix above),
// `proxy.send_event(event_type, payload)` and `proxy.cancel(reason)`. Rewrapping
// each onto one line is what makes them spans for the first time — the words on
// the page are unchanged. A page-wide scan for a backtick opened on one line and
// closed on the next now reports none here.
//
// The renamed consumer parameter (`generate_report` to `report_job`, so the
// example demonstrates the free name) sits inside a fence, and the cheat-sheet
// cell is a table cell; renderStyled takes other branches for both and neither
// adds a span. The rewritten bullet is a list item but changes no line's markup
// shape, so the two list goldens below hold.
//
// Issue #1500: the sentence most annotations above end on — that the `_java`
// and `_typescript` files are invisible here, so a review of them cannot lean
// on this test — is still true of THESE constants and no longer true of this
// package. `variant_corpus_test.go` renders all 34 variant pages and carries
// its own single golden; a variant-only edit moves that one, not these. The
// three below stay default-variant on purpose, so their history remains a
// readable record of one corpus rather than a sum of two.
//
// Neither file says anything about whether the prose is TRUE. That is
// `scripts/check_doc_claims.py`, which can read the four runtimes' source and
// the starter's POM; a test in this package cannot, and #1499 shipped three
// false claims through a green run here.
const (
	wantInlineCodeSpans = 1787
	wantListCodeSpans   = 522
	wantMarkupListLines = 448
)

// assertCorpusSize replaces the t.Logf these tests used to end on.
func assertCorpusSize(t *testing.T, what string, got, want int) {
	t.Helper()
	if got == want {
		t.Logf("verified %d %s across the man corpus", got, what)
		return
	}
	t.Errorf("man corpus holds %d %s, want %d (delta %+d).\n"+
		"If a docs change moved this, update the golden in renderer_test.go in "+
		"the same commit and confirm the delta is the size you intended. A "+
		"large drop usually means a topic stopped being listed, which would "+
		"silently shrink every corpus assertion here.",
		got, what, want, got-want)
}

// TestStyleInlineCorpus renders every shipped man page and asserts that the
// content of every source code span survives verbatim into the output. Any
// bold/italic/link escape injected into a code span breaks this.
func TestStyleInlineCorpus(t *testing.T) {
	r := NewRenderer(false)
	checked := 0

	for _, guide := range ListGuides() {
		_, content, err := GetGuide(guide.Name)
		if err != nil {
			t.Fatalf("GetGuide(%q) failed: %v", guide.Name, err)
		}

		inCodeBlock := false
		for i, line := range strings.Split(content, "\n") {
			// Only inline-formatted prose reaches styleInline; code blocks,
			// headers and tables take other branches in renderStyled.
			if strings.HasPrefix(line, "```") {
				inCodeBlock = !inCodeBlock
				continue
			}
			if inCodeBlock || strings.HasPrefix(line, "#") || strings.HasPrefix(line, "|") {
				continue
			}

			styled := r.styleInline(line)
			for _, m := range inlineCodeRe.FindAllStringSubmatch(line, -1) {
				checked++
				if !strings.Contains(styled, green+m[1]+reset) {
					t.Errorf("%s:%d code span %q corrupted\n src: %q\n out: %q",
						guide.Name, i+1, m[1], line, styled)
				}
			}
		}
	}

	if checked == 0 {
		t.Fatal("no inline code spans found in man corpus; test is not exercising anything")
	}
	assertCorpusSize(t, "inline code spans", checked, wantInlineCodeSpans)
}

const (
	bulletMarker       = yellow + "  • " + reset
	nestedBulletMarker = yellow + "    ◦ " + reset
	numberedMarker     = yellow + "  " + reset
)

// TestRenderStyledListItems covers list content reaching the inline passes.
// Bullet and numbered branches used to write their remainder raw, so markup in
// a list item rendered literally.
func TestRenderStyledListItems(t *testing.T) {
	r := NewRenderer(false)
	guide := &Guide{Name: "t", Title: "T"}

	testCases := []struct {
		name    string
		content string
		want    string
	}{
		{
			name:    "bullet with inline code",
			content: "- For `dependency_resolved`:",
			want:    bulletMarker + "For " + green + "dependency_resolved" + reset + ":",
		},
		{
			name:    "bullet with bold",
			content: "- **Orphan reroute.** A job whose owner died",
			want:    bulletMarker + bold + "Orphan reroute." + reset + " A job whose owner died",
		},
		{
			name:    "bullet with two snake_case code spans",
			content: "- `agent_id` and `agent_name` differ",
			want: bulletMarker + green + "agent_id" + reset + " and " +
				green + "agent_name" + reset + " differ",
		},
		{
			name:    "nested bullet with inline code",
			content: "  - the `retry_on` field",
			want:    nestedBulletMarker + "the " + green + "retry_on" + reset + " field",
		},
		{
			name:    "nested bullet with bold and italic",
			content: "  - **note:** _see_ below",
			want:    nestedBulletMarker + bold + "note:" + reset + " " + italic + "see" + reset + " below",
		},
		{
			name:    "numbered item with inline code",
			content: "1. Run `meshctl start` first",
			want:    numberedMarker + "1. Run " + green + "meshctl start" + reset + " first",
		},
		{
			name:    "numbered item with bold, multi-digit marker",
			content: "12. **Deploy** the agent",
			want:    numberedMarker + "12. " + bold + "Deploy" + reset + " the agent",
		},
		{
			name:    "bullet with a markdown link",
			content: "- see [the docs](https://example.com/a_b_c)",
			want:    bulletMarker + "see " + underline + cyan + "the docs" + reset,
		},
		{
			name:    "plain bullet is unchanged",
			content: "- nothing to style",
			want:    bulletMarker + "nothing to style",
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			got := r.Render(guide, tc.content)
			if !strings.Contains(got, tc.want) {
				t.Errorf("Render(%q)\n got: %q\nwant to contain: %q", tc.content, got, tc.want)
			}
			// Markup must be consumed, not left literal.
			body := strings.TrimPrefix(got, renderedHeader(guide))
			if strings.Contains(body, "`") || strings.Contains(body, "**") {
				t.Errorf("Render(%q) left literal markdown: %q", tc.content, body)
			}
		})
	}
}

// TestRenderStyledFencedListItemsStayLiteral is the critical negative case:
// bullet- and numbered-looking lines inside a fenced code block must NOT be
// styled, or code samples would be corrupted. Code fences are handled before
// the list branches in renderStyled, which is what protects them.
func TestRenderStyledFencedListItemsStayLiteral(t *testing.T) {
	r := NewRenderer(false)
	guide := &Guide{Name: "t", Title: "T"}

	content := strings.Join([]string{
		"```yaml",
		"- name: `literal_backticks`",
		"  - nested: **not bold**",
		"1. numbered: `stays_literal`",
		"```",
	}, "\n")

	got := r.Render(guide, content)

	for _, literal := range []string{
		"- name: `literal_backticks`",
		"  - nested: **not bold**",
		"1. numbered: `stays_literal`",
	} {
		if !strings.Contains(got, literal) {
			t.Errorf("fenced line %q was altered; output: %q", literal, got)
		}
	}
	if strings.Contains(got, bulletMarker) || strings.Contains(got, nestedBulletMarker) {
		t.Errorf("fenced lines were turned into bullets: %q", got)
	}
	// The title block legitimately uses bold, so inspect only the body.
	if body := strings.TrimPrefix(got, renderedHeader(guide)); strings.Contains(body, bold) {
		t.Errorf("fenced ** was bolded: %q", body)
	}
}

// TestRenderStyledCorpusListItems asserts that code spans on list lines of the
// shipped man pages survive verbatim into the fully rendered page. The earlier
// styleInline-only corpus test could not catch renderStyled skipping the inline
// passes for list items.
func TestRenderStyledCorpusListItems(t *testing.T) {
	r := NewRenderer(false)
	checked := 0

	for _, guide := range ListGuides() {
		g, content, err := GetGuide(guide.Name)
		if err != nil {
			t.Fatalf("GetGuide(%q) failed: %v", guide.Name, err)
		}
		rendered := r.Render(g, content)

		inCodeBlock := false
		for i, line := range strings.Split(content, "\n") {
			if strings.HasPrefix(line, "```") {
				inCodeBlock = !inCodeBlock
				continue
			}
			if inCodeBlock {
				continue
			}
			if !strings.HasPrefix(line, "- ") && !strings.HasPrefix(line, "  - ") &&
				!numberedListRe.MatchString(line) {
				continue
			}

			for _, m := range inlineCodeRe.FindAllStringSubmatch(line, -1) {
				checked++
				if !strings.Contains(rendered, green+m[1]+reset) {
					t.Errorf("%s:%d list-item code span %q not styled\n src: %q",
						guide.Name, i+1, m[1], line)
				}
			}
		}
	}

	if checked == 0 {
		t.Fatal("no list-item code spans found in man corpus; test is not exercising anything")
	}
	assertCorpusSize(t, "list-item inline code spans", checked, wantListCodeSpans)
}

// TestManCorpusMarkupListLineCount re-derives the figure #1392 and the v3.3.2
// release notes published — "432 list lines in default-variant topics carry
// `code` or **bold**" — which was the size of the second defect: those lines
// were written raw, so their markup rendered literally.
//
// It is the one published figure that is still measurable after the fix (the
// 83 corrupted code spans were a property of the old renderer and cannot be
// re-derived from a corpus it no longer corrupts), so it is the one worth
// anchoring. Measured 432 at the commit that fixed #1392 and 433 today.
//
// This also guards the coverage the count stands for from the other side: the
// list branches in renderStyled are what carry these lines through
// styleInline, and a regression that stopped routing them would leave the two
// corpus tests above passing on whatever still worked.
func TestManCorpusMarkupListLineCount(t *testing.T) {
	lines := 0

	for _, guide := range ListGuides() {
		_, content, err := GetGuide(guide.Name)
		if err != nil {
			t.Fatalf("GetGuide(%q) failed: %v", guide.Name, err)
		}

		inCodeBlock := false
		for _, line := range strings.Split(content, "\n") {
			if strings.HasPrefix(line, "```") {
				inCodeBlock = !inCodeBlock
				continue
			}
			if inCodeBlock {
				continue
			}
			if !strings.HasPrefix(line, "- ") && !strings.HasPrefix(line, "  - ") &&
				!numberedListRe.MatchString(line) {
				continue
			}
			if inlineCodeRe.MatchString(line) || strings.Contains(line, "**") {
				lines++
			}
		}
	}

	assertCorpusSize(t, "list lines carrying inline markup", lines, wantMarkupListLines)
}

// renderedHeader reproduces the fixed title block Render emits, so tests can
// inspect only the body.
func renderedHeader(guide *Guide) string {
	bar := strings.Repeat("━", 78)
	return cyan + bold + bar + "\n  " + guide.Title + "\n" + bar + "\n" + reset
}
