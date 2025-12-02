package man

import (
	"regexp"
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

		// Handle bullet points
		if strings.HasPrefix(line, "- ") {
			sb.WriteString(yellow + "  • " + reset + strings.TrimPrefix(line, "- ") + "\n")
			continue
		}
		if strings.HasPrefix(line, "  - ") {
			sb.WriteString(yellow + "    ◦ " + reset + strings.TrimPrefix(line, "  - ") + "\n")
			continue
		}

		// Handle numbered lists
		if matched, _ := regexp.MatchString(`^\d+\. `, line); matched {
			sb.WriteString(yellow + "  " + reset + line + "\n")
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
func (r *Renderer) styleInline(line string) string {
	// Inline code: `code`
	codeRe := regexp.MustCompile("`([^`]+)`")
	line = codeRe.ReplaceAllString(line, green+"$1"+reset)

	// Bold: **text** or __text__
	boldRe := regexp.MustCompile(`\*\*([^*]+)\*\*|__([^_]+)__`)
	line = boldRe.ReplaceAllString(line, bold+"$1$2"+reset)

	// Italic: *text* or _text_
	italicRe := regexp.MustCompile(`\*([^*]+)\*|_([^_]+)_`)
	line = italicRe.ReplaceAllString(line, italic+"$1$2"+reset)

	// Links: [text](url) - show as underlined text
	linkRe := regexp.MustCompile(`\[([^\]]+)\]\([^)]+\)`)
	line = linkRe.ReplaceAllString(line, underline+cyan+"$1"+reset)

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
