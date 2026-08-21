package man

import (
	"sort"
	"strings"
	"testing"
)

// Issue #1500. The three corpus tests in renderer_test.go sample the DEFAULT
// variant of each listed topic, and every one of their golden comments has had
// to end by saying so: "a review of those files cannot lean on this test". The
// `_java` and `_typescript` pages — 34 of the 61 files in content/ — were
// rendered by nothing here.
//
// That is not a theoretical hole. #1499's three false Actuator claims all lived
// in `_java` pages, and RFC #1502 rewrote both `_java` and `_typescript` health
// and deployment pages while the goldens below did not move by construction.
//
// These tests are about RENDERING, which is all a test in this package can
// speak to. Whether a variant page's PROSE matches the runtime it describes is
// checked by scripts/check_doc_claims.py, which can read the four runtimes'
// source; this file cannot, and pretending otherwise would be the same mistake
// the pages made.

// variantPages returns every (topic, variant) pair the registry advertises,
// with its rendered content.
func variantPages(t *testing.T) []variantPage {
	t.Helper()

	var pages []variantPage
	for _, guide := range ListGuides() {
		for _, variant := range []string{"typescript", "java"} {
			if variant == "typescript" && !guide.HasTypeScriptVariant {
				continue
			}
			if variant == "java" && !guide.HasJavaVariant {
				continue
			}
			g, content, err := GetGuideWithVariant(guide.Name, variant)
			if err != nil {
				t.Fatalf("GetGuideWithVariant(%q, %q) failed: %v",
					guide.Name, variant, err)
			}
			pages = append(pages, variantPage{
				guide:   g,
				name:    guide.Name + "_" + variant,
				content: content,
			})
		}
	}
	return pages
}

type variantPage struct {
	guide   *Guide
	name    string
	content string
}

// TestVariantFilesAndRegistryAgree is the structural half, and it guards a
// silent failure the count goldens cannot see.
//
// GetGuideWithVariant FALLS BACK to the default page when a variant file is
// missing, and reports no error. So deleting `health_java.md`, or renaming it,
// leaves `meshctl man health --java` quietly serving the Python page to a Java
// developer — every code sample in the wrong language, and a green build. The
// inverse is just as quiet: a new `foo_java.md` whose registry entry never got
// `HasJavaVariant: true` is a page that ships in the binary and can never be
// reached.
//
// Asserting the two sides against each other costs no golden to maintain.
func TestVariantFilesAndRegistryAgree(t *testing.T) {
	entries, err := guideContent.ReadDir("content")
	if err != nil {
		t.Fatalf("reading embedded content: %v", err)
	}

	onDisk := map[string]bool{}
	for _, e := range entries {
		name := strings.TrimSuffix(e.Name(), ".md")
		if strings.HasSuffix(name, "_java") || strings.HasSuffix(name, "_typescript") {
			onDisk[name] = true
		}
	}

	advertised := map[string]bool{}
	for _, guide := range ListGuides() {
		if guide.HasTypeScriptVariant {
			advertised[guide.Name+"_typescript"] = true
		}
		if guide.HasJavaVariant {
			advertised[guide.Name+"_java"] = true
		}
	}

	for name := range advertised {
		if !onDisk[name] {
			t.Errorf("the registry advertises %s.md, which is not in content/. "+
				"GetGuideWithVariant falls back to the default page without an "+
				"error, so this ships as the wrong language rather than as a "+
				"failure", name)
		}
	}
	for name := range onDisk {
		if !advertised[name] {
			t.Errorf("content/%s.md ships in the binary but no registry entry "+
				"sets the matching Has*Variant flag, so no meshctl invocation "+
				"can reach it", name)
		}
	}

	if len(advertised) == 0 {
		t.Fatal("no variant pages advertised; every test in this file is inert")
	}
}

// TestVariantPagesAreNotTheDefault pins the other half of the same fallback:
// a variant that resolves must resolve to DIFFERENT content. A file that
// exists but was truncated to a stub, or one accidentally overwritten with a
// copy of the default, satisfies TestVariantFilesAndRegistryAgree and still
// serves a Java developer Python.
func TestVariantPagesAreNotTheDefault(t *testing.T) {
	for _, guide := range ListGuides() {
		_, base, err := GetGuide(guide.Name)
		if err != nil {
			t.Fatalf("GetGuide(%q) failed: %v", guide.Name, err)
		}
		for _, variant := range []string{"typescript", "java"} {
			if variant == "typescript" && !guide.HasTypeScriptVariant {
				continue
			}
			if variant == "java" && !guide.HasJavaVariant {
				continue
			}
			_, got, err := GetGuideWithVariant(guide.Name, variant)
			if err != nil {
				t.Fatalf("GetGuideWithVariant(%q, %q) failed: %v",
					guide.Name, variant, err)
			}
			// The cross-language header differs even on a fallback, so compare
			// the bodies with it stripped.
			if stripLangHeader(got) == stripLangHeader(base) {
				t.Errorf("%s --%s serves the default page's content", guide.Name, variant)
			}
		}
	}
}

func stripLangHeader(content string) string {
	const marker = "\n\n**Also available:**"
	idx := strings.Index(content, marker)
	if idx == -1 {
		return content
	}
	end := strings.Index(content[idx+2:], "\n")
	if end == -1 {
		return content[:idx]
	}
	return content[:idx] + content[idx+2+end:]
}

// Golden corpus size for the variant pages.
//
// ONE number, not the three renderer_test.go keeps for the default corpus, and
// deliberately so. The two list goldens there exist to detect a topic dropping
// out of ListGuides, and every comment added to them since #1401 has recorded
// them as "unmoved". Here that failure is caught structurally and exactly by
// TestVariantFilesAndRegistryAgree, which names the missing file instead of
// reporting a number that changed. A second and third count over a corpus that
// moves as often as this one would be maintenance without a defect class
// behind it.
//
// A docs change that moves this is expected to move it — update the constant in
// the same commit and confirm the delta is the size you intended, the same rule
// the default corpus follows. Measured across all 34 variant pages at the
// commit that added this test.
const wantVariantInlineCodeSpans = 1662

// TestVariantCorpusCodeSpans is TestStyleInlineCorpus plus
// TestRenderStyledCorpusListItems, run over the pages neither of them sees.
//
// Both assertions are made per page: a code span must survive styleInline
// verbatim, AND must survive into the fully rendered output, which is what
// covers the list branches in renderStyled (the #1392 defect class).
func TestVariantCorpusCodeSpans(t *testing.T) {
	r := NewRenderer(false)
	checked := 0
	var pageNames []string

	for _, page := range variantPages(t) {
		pageNames = append(pageNames, page.name)
		rendered := r.Render(page.guide, page.content)

		inCodeBlock := false
		for i, line := range strings.Split(page.content, "\n") {
			if strings.HasPrefix(line, "```") {
				inCodeBlock = !inCodeBlock
				continue
			}
			if inCodeBlock || strings.HasPrefix(line, "#") || strings.HasPrefix(line, "|") {
				continue
			}

			isListLine := strings.HasPrefix(line, "- ") ||
				strings.HasPrefix(line, "  - ") ||
				numberedListRe.MatchString(line)

			styled := r.styleInline(line)
			for _, m := range inlineCodeRe.FindAllStringSubmatch(line, -1) {
				checked++
				want := green + m[1] + reset
				if !strings.Contains(styled, want) {
					t.Errorf("%s:%d code span %q corrupted by styleInline\n src: %q\n out: %q",
						page.name, i+1, m[1], line, styled)
				}
				if isListLine && !strings.Contains(rendered, want) {
					t.Errorf("%s:%d list-item code span %q not styled in the rendered page\n src: %q",
						page.name, i+1, m[1], line)
				}
			}
		}
	}

	sort.Strings(pageNames)
	if checked == 0 {
		t.Fatal("no inline code spans found in the variant pages; test is not exercising anything")
	}
	if got, want := checked, wantVariantInlineCodeSpans; got != want {
		t.Errorf("the %d variant pages hold %d inline code spans, want %d "+
			"(delta %+d).\nIf a docs change moved this, update "+
			"wantVariantInlineCodeSpans in the same commit and confirm the "+
			"delta is the size you intended. Pages sampled: %s",
			len(pageNames), got, want, got-want, strings.Join(pageNames, ", "))
	} else {
		t.Logf("verified %d inline code spans across %d variant pages",
			checked, len(pageNames))
	}
}

// TestVariantCorpusLeavesNoLiteralMarkup renders every variant page and
// asserts no markdown escaped the renderer into the output. This is the
// symptom a reader of `meshctl man health --java` actually sees, and it is
// checked against the whole page rather than against a count, so it needs no
// golden and cannot drift.
func TestVariantCorpusLeavesNoLiteralMarkup(t *testing.T) {
	r := NewRenderer(false)

	for _, page := range variantPages(t) {
		body := strings.TrimPrefix(r.Render(page.guide, page.content), renderedHeader(page.guide))

		inCodeBlock := false
		for i, line := range strings.Split(page.content, "\n") {
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
			if !strings.Contains(line, "**") {
				continue
			}
			for _, m := range inlineBoldRe.FindAllStringSubmatch(line, -1) {
				text := m[1]
				if text == "" {
					text = m[2]
				}
				if strings.Contains(body, "**"+text+"**") {
					t.Errorf("%s:%d bold %q rendered literally on a list line\n src: %q",
						page.name, i+1, text, line)
				}
			}
		}
	}
}
