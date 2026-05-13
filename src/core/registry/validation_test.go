package registry

import (
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/stretchr/testify/assert"
)

// TestValidateAgentDescription covers the issue #969 sanitisation helper.
// The contract is: trim whitespace, truncate to MaxAgentDescriptionLen,
// emit a single warning when truncation actually happens, never error.
func TestValidateAgentDescription(t *testing.T) {
	t.Run("PassthroughShortString", func(t *testing.T) {
		cleaned, warnings := validateAgentDescription("Hello mesh")
		assert.Equal(t, "Hello mesh", cleaned)
		assert.Empty(t, warnings)
	})

	t.Run("EmptyString", func(t *testing.T) {
		cleaned, warnings := validateAgentDescription("")
		assert.Equal(t, "", cleaned)
		assert.Empty(t, warnings)
	})

	t.Run("StripsLeadingAndTrailingWhitespace", func(t *testing.T) {
		cleaned, warnings := validateAgentDescription("  hello  \n\t")
		assert.Equal(t, "hello", cleaned)
		assert.Empty(t, warnings)
	})

	t.Run("AllWhitespaceCollapsesToEmpty", func(t *testing.T) {
		cleaned, warnings := validateAgentDescription("   \n\t  ")
		assert.Equal(t, "", cleaned)
		assert.Empty(t, warnings)
	})

	t.Run("ExactlyAtCapNoTruncation", func(t *testing.T) {
		s := strings.Repeat("a", MaxAgentDescriptionLen)
		cleaned, warnings := validateAgentDescription(s)
		assert.Len(t, cleaned, MaxAgentDescriptionLen)
		assert.Empty(t, warnings, "exact cap should not emit a warning")
	})

	t.Run("TruncatesWhenOverCap", func(t *testing.T) {
		over := strings.Repeat("x", 300)
		cleaned, warnings := validateAgentDescription(over)
		assert.Len(t, cleaned, MaxAgentDescriptionLen)
		assert.Equal(t, strings.Repeat("x", MaxAgentDescriptionLen), cleaned)
		if assert.Len(t, warnings, 1) {
			assert.Contains(t, warnings[0], "description truncated")
			assert.Contains(t, warnings[0], "300")
			assert.Contains(t, warnings[0], "256")
		}
	})

	t.Run("WhitespaceStrippedBeforeMeasuring", func(t *testing.T) {
		// Pre-strip the input is 270 chars (260 'a' + 10 trailing spaces).
		// After TrimSpace it's 260, which exceeds the 256 cap → truncate to 256.
		input := strings.Repeat("a", 260) + "          "
		cleaned, warnings := validateAgentDescription(input)
		assert.Equal(t, strings.Repeat("a", MaxAgentDescriptionLen), cleaned)
		if assert.Len(t, warnings, 1) {
			// The warning reports the *post-strip* pre-truncation length (260).
			assert.Contains(t, warnings[0], "260")
		}
	})

	t.Run("UTF8MultiByteHandling", func(t *testing.T) {
		// Each "世界🌍" is 3 runes (10 bytes). 100 reps = 300 runes / 1000 bytes,
		// which exceeds MaxAgentDescriptionLen (256 runes). A byte-slice
		// truncation at offset 256 would land mid-codepoint and produce invalid
		// UTF-8; rune-based truncation must produce a valid string of exactly
		// MaxAgentDescriptionLen runes.
		input := strings.Repeat("世界🌍", 100)
		cleaned, warnings := validateAgentDescription(input)
		assert.True(t, utf8.ValidString(cleaned), "truncated string must be valid UTF-8")
		assert.Equal(t, MaxAgentDescriptionLen, utf8.RuneCountInString(cleaned),
			"truncation must cap at MaxAgentDescriptionLen runes")
		if assert.Len(t, warnings, 1) {
			assert.Contains(t, warnings[0], "description truncated")
			assert.Contains(t, warnings[0], "300")
		}
	})
}
