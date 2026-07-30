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
const (
	wantInlineCodeSpans = 1605
	wantListCodeSpans   = 488
	wantMarkupListLines = 433
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
