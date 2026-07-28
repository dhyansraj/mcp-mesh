package man

import (
	"regexp"
	"strconv"
	"strings"
)

// ANSI color codes for terminal styling
const (
	bold      = "\033[1m"
	dim       = "\033[2m"
	italic    = "\033[3m"
	underline = "\033[4m"
	reset     = "\033[0m"

	black   = "\033[30m"
	red     = "\033[31m"
	green   = "\033[32m"
	yellow  = "\033[33m"
	blue    = "\033[34m"
	magenta = "\033[35m"
	cyan    = "\033[36m"
	white   = "\033[37m"
	gray    = "\033[90m"

	bgBlack   = "\033[40m"
	bgRed     = "\033[41m"
	bgGreen   = "\033[42m"
	bgYellow  = "\033[43m"
	bgBlue    = "\033[44m"
	bgMagenta = "\033[45m"
	bgCyan    = "\033[46m"
	bgWhite   = "\033[47m"
	bgGray    = "\033[100m"
)

// Pre-compiled regex patterns for inline styling (avoids recompilation per line)
var (
	inlineCodeRe   = regexp.MustCompile("`([^`]+)`")
	inlineBoldRe   = regexp.MustCompile(`\*\*([^*]+)\*\*|__([^_]+)__`)
	inlineItalicRe = regexp.MustCompile(`\*([^*]+)\*|_([^_]+)_`)
	inlineLinkRe   = regexp.MustCompile(`\[([^\]]+)\]\([^)]+\)`)
	numberedListRe = regexp.MustCompile(`^\d+\. `)
)

// placeholderSentinel wraps the index of an already-styled span while the
// remaining inline passes run. NUL is stripped from the input first, so a
// placeholder can never be forged by real content, and it matches none of the
// bold/italic/link patterns (no backtick, underscore, asterisk, or brackets).
const placeholderSentinel = "\x00"

// Renderer handles guide content rendering.
type Renderer struct {
	Raw bool // Output raw markdown instead of styled
}

// NewRenderer creates a new renderer with the given options.
func NewRenderer(raw bool) *Renderer {
	return &Renderer{Raw: raw}
}

// Render renders guide content for terminal display.
func (r *Renderer) Render(guide *Guide, content string) string {
	if r.Raw {
		return content
	}
	return r.renderStyled(guide, content)
}

// renderStyled applies terminal styling to markdown content.
func (r *Renderer) renderStyled(guide *Guide, content string) string {
	var sb strings.Builder

	// Add title header
	sb.WriteString(cyan + bold)
	sb.WriteString("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	sb.WriteString("  " + guide.Title + "\n")
	sb.WriteString("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	sb.WriteString(reset)

	lines := strings.Split(content, "\n")
	inCodeBlock := false
	codeBlockLang := ""

	for _, line := range lines {
		// Handle code blocks
		if strings.HasPrefix(line, "```") {
			if !inCodeBlock {
				inCodeBlock = true
				codeBlockLang = strings.TrimPrefix(line, "```")
				sb.WriteString(gray + "┌─")
				if codeBlockLang != "" {
					sb.WriteString("[" + codeBlockLang + "]")
				}
				sb.WriteString("─────────────────────────────────────────────────────────────────\n")
				continue
			} else {
				inCodeBlock = false
				codeBlockLang = ""
				sb.WriteString("└──────────────────────────────────────────────────────────────────────────\n" + reset)
				continue
			}
		}

		if inCodeBlock {
			sb.WriteString(gray + "│ " + green + line + reset + "\n")
			continue
		}

		// Handle headers
		if strings.HasPrefix(line, "# ") {
			// Skip h1 since we already have a title
			continue
		}
		if strings.HasPrefix(line, "## ") {
			sb.WriteString("\n" + cyan + bold + strings.TrimPrefix(line, "## ") + reset + "\n")
			sb.WriteString(cyan + "────────────────────────────────────────────────────────────────────────────\n" + reset)
			continue
		}
		if strings.HasPrefix(line, "### ") {
			sb.WriteString("\n" + yellow + bold + strings.TrimPrefix(line, "### ") + reset + "\n")
			continue
		}
		if strings.HasPrefix(line, "#### ") {
			sb.WriteString("\n" + magenta + strings.TrimPrefix(line, "#### ") + reset + "\n")
			continue
		}

		// Handle blockquotes (summary lines)
		if strings.HasPrefix(line, "> ") {
			sb.WriteString(italic + gray + "  " + strings.TrimPrefix(line, "> ") + reset + "\n\n")
			continue
		}

		// Handle bullet points. Only the content is styled; the marker keeps its
		// own colouring so styleInline cannot disturb or swallow it. Code fences
		// are handled above, so a "- " line inside a fenced block never reaches
		// here and stays literal.
		if strings.HasPrefix(line, "- ") {
			sb.WriteString(yellow + "  • " + reset + r.styleInline(strings.TrimPrefix(line, "- ")) + "\n")
			continue
		}
		if strings.HasPrefix(line, "  - ") {
			sb.WriteString(yellow + "    ◦ " + reset + r.styleInline(strings.TrimPrefix(line, "  - ")) + "\n")
			continue
		}

		// Handle numbered lists
		if marker := numberedListRe.FindString(line); marker != "" {
			sb.WriteString(yellow + "  " + reset + marker + r.styleInline(strings.TrimPrefix(line, marker)) + "\n")
			continue
		}

		// Handle tables (simple pass-through with dim color)
		if strings.HasPrefix(line, "|") {
			sb.WriteString(dim + line + reset + "\n")
			continue
		}

		// Handle inline formatting
		styled := r.styleInline(line)
		sb.WriteString(styled + "\n")
	}

	return sb.String()
}

// styleInline applies inline styling for bold, italic, code, etc.
// Uses pre-compiled regex patterns for performance.
func (r *Renderer) styleInline(line string) string {
	// Code spans and links are styled first and stashed behind placeholders so
	// the bold/italic passes cannot reach their contents. Without this, a line
	// carrying two snake_case code spans (e.g. `dependency_resolved` and
	// `dependency_unresolved`) has its underscores paired across the spans by
	// the italic pass, and a link URL containing underscores gets ANSI injected
	// mid-URL. Reordering alone cannot fix this: running italic first would
	// instead corrupt the text inside the code spans.
	line = strings.ReplaceAll(line, placeholderSentinel, "")

	var stashed []string
	stash := func(styled string) string {
		stashed = append(stashed, styled)
		return placeholderSentinel + strconv.Itoa(len(stashed)-1) + placeholderSentinel
	}

	// Inline code: `code`
	line = inlineCodeRe.ReplaceAllStringFunc(line, func(match string) string {
		return stash(green + inlineCodeRe.FindStringSubmatch(match)[1] + reset)
	})

	// Links: [text](url) - show as underlined text
	line = inlineLinkRe.ReplaceAllStringFunc(line, func(match string) string {
		return stash(underline + cyan + inlineLinkRe.FindStringSubmatch(match)[1] + reset)
	})

	// Bold: **text** or __text__
	line = inlineBoldRe.ReplaceAllString(line, bold+"$1$2"+reset)

	// Italic: *text* or _text_
	line = inlineItalicRe.ReplaceAllString(line, italic+"$1$2"+reset)

	// Restore highest index first: a link may have stashed a code placeholder
	// inside its text, and that code span always holds a lower index.
	for i := len(stashed) - 1; i >= 0; i-- {
		token := placeholderSentinel + strconv.Itoa(i) + placeholderSentinel
		line = strings.ReplaceAll(line, token, stashed[i])
	}

	return line
}

// RenderList renders the list of available guides.
func (r *Renderer) RenderList(guides []*Guide) string {
	var sb strings.Builder

	if r.Raw {
		sb.WriteString("# Available Topics\n\n")
		for _, guide := range guides {
			sb.WriteString("- **" + guide.Name + "**")
			if len(guide.Aliases) > 0 {
				sb.WriteString(" (aliases: " + strings.Join(guide.Aliases, ", ") + ")")
			}
			sb.WriteString(" - " + guide.Description + "\n")
		}
		return sb.String()
	}

	// Styled output
	sb.WriteString(cyan + bold + "Available Topics" + reset + "\n")
	sb.WriteString(cyan + "────────────────────────────────────────────────────────────────────────────\n" + reset)
	sb.WriteString("\n")

	for _, guide := range guides {
		sb.WriteString(yellow + bold + "  " + guide.Name + reset)
		if len(guide.Aliases) > 0 {
			sb.WriteString(gray + " (" + strings.Join(guide.Aliases, ", ") + ")" + reset)
		}
		sb.WriteString("\n")
		sb.WriteString("    " + guide.Description + "\n\n")
	}

	sb.WriteString(gray + "Use 'meshctl man <topic>' to view a topic.\n")
	sb.WriteString("Use 'meshctl man <topic> --raw' for LLM-friendly markdown output." + reset + "\n")

	return sb.String()
}

// RenderSearchResults renders search results.
func (r *Renderer) RenderSearchResults(query string, results []*SearchResult) string {
	var sb strings.Builder

	if len(results) == 0 {
		if r.Raw {
			return "No results found for: " + query + "\n"
		}
		return yellow + "No results found for: " + reset + query + "\n"
	}

	if r.Raw {
		sb.WriteString("# Search Results for: " + query + "\n\n")
		for _, result := range results {
			sb.WriteString("## " + result.Guide.Title + " (" + result.Guide.Name + ")\n")
			for _, match := range result.Matches {
				sb.WriteString("  - " + match + "\n")
			}
			sb.WriteString("\n")
		}
		return sb.String()
	}

	// Styled output
	sb.WriteString(cyan + bold + "Search Results for: " + reset + yellow + query + reset + "\n")
	sb.WriteString(cyan + "────────────────────────────────────────────────────────────────────────────\n" + reset)
	sb.WriteString("\n")

	for _, result := range results {
		sb.WriteString(yellow + bold + "  " + result.Guide.Name + reset)
		sb.WriteString(" - " + result.Guide.Title + "\n")
		for _, match := range result.Matches {
			// Highlight query in match
			highlighted := strings.ReplaceAll(
				strings.ToLower(match),
				strings.ToLower(query),
				green+bold+query+reset+gray,
			)
			sb.WriteString(gray + "    " + highlighted + reset + "\n")
		}
		sb.WriteString("\n")
	}

	sb.WriteString(gray + "Use 'meshctl man <topic>' to view full topic." + reset + "\n")

	return sb.String()
}

// RenderSuggestions renders topic suggestions when a guide is not found.
func (r *Renderer) RenderSuggestions(query string, suggestions []string) string {
	var sb strings.Builder

	if r.Raw {
		sb.WriteString("Topic '" + query + "' not found.\n\n")
		if len(suggestions) > 0 {
			sb.WriteString("Did you mean:\n")
			for _, s := range suggestions {
				sb.WriteString("  - " + s + "\n")
			}
		}
		sb.WriteString("\nUse 'meshctl man --list' to see all available topics.\n")
		return sb.String()
	}

	sb.WriteString(red + "Topic '" + query + "' not found." + reset + "\n\n")
	if len(suggestions) > 0 {
		sb.WriteString(yellow + "Did you mean:" + reset + "\n")
		for _, s := range suggestions {
			sb.WriteString("  " + cyan + s + reset + "\n")
		}
		sb.WriteString("\n")
	}
	sb.WriteString(gray + "Use 'meshctl man --list' to see all available topics." + reset + "\n")

	return sb.String()
}
