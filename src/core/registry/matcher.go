package registry

import (
	"github.com/Masterminds/semver/v3"
	"mcp-mesh/src/core/logger"
)

// Candidate represents a potential dependency provider.
// This consolidates the repeated anonymous struct definitions throughout the codebase.
type Candidate struct {
	AgentID      string
	FunctionName string
	Capability   string
	Version      string
	Tags         []string
	HttpHost     string
	HttpPort     int
}

// ScoredCandidate adds priority scoring to Candidate for ranking.
type ScoredCandidate struct {
	Candidate
	Score int // Priority score from tag matching (higher = better match)
}

// Matcher handles all dependency matching logic.
// Centralizes version and tag matching with consistent behavior.
type Matcher struct {
	logger *logger.Logger
}

// NewMatcher creates a new Matcher instance.
func NewMatcher(logger *logger.Logger) *Matcher {
	return &Matcher{logger: logger}
}

// MatchVersion checks if a provider version satisfies a consumer's version constraint.
// Supports full semver constraint syntax: =, !=, >, <, >=, <=, ~, ^, ranges.
//
// Rules:
//   - Empty constraint matches any version (including empty)
//   - Empty version only matches empty constraint
//   - Invalid semver falls back to exact string match with warning
//
// Examples:
//   - MatchVersion("1.2.3", ">=1.0.0") → true
//   - MatchVersion("2.0.0", "^1.0.0") → false
//   - MatchVersion("1.2.3", "") → true (empty constraint = any)
//   - MatchVersion("", ">=1.0.0") → false (no version can't satisfy constraint)
func (m *Matcher) MatchVersion(version, constraint string) bool {
	// Empty constraint matches any version
	if constraint == "" {
		return true
	}

	// Empty version can't satisfy a non-empty constraint
	if version == "" {
		return false
	}

	// Parse the version
	v, err := semver.NewVersion(version)
	if err != nil {
		// Invalid semver - log warning and fall back to exact string match
		if m.logger != nil {
			m.logger.Debug("Invalid semver version '%s': %v, falling back to string comparison", version, err)
		}
		return version == constraint
	}

	// Parse the constraint
	c, err := semver.NewConstraint(constraint)
	if err != nil {
		// Invalid constraint - log warning and fall back to exact string match
		if m.logger != nil {
			m.logger.Debug("Invalid semver constraint '%s': %v, falling back to string comparison", constraint, err)
		}
		return version == constraint
	}

	// Check if version satisfies constraint
	return c.Check(v)
}

// MatchTags implements enhanced tag matching with +/- operators and OR alternatives.
// Returns (matches, score) where:
//   - matches: true if the provider satisfies all constraints
//   - score: numeric score for ranking providers (higher = better match)
//
// Tag prefixes:
//   - No prefix: Required tag (must be present) - adds 5 points
//   - "+": Preferred tag (bonus if present, no penalty if missing) - adds 10 points
//   - "-": Excluded tag (must NOT be present, fails if found)
//
// OR Alternatives (tagAlternatives):
// Each []string in tagAlternatives is an OR group - at least one must match.
// e.g., tagAlternatives: [["python", "typescript"]] means (python OR typescript)
//
// Examples:
//   - MatchTags(["llm", "claude"], ["llm"], nil) → (true, 5)
//   - MatchTags(["llm", "claude"], ["+claude"], nil) → (true, 10)
//   - MatchTags(["llm", "claude"], ["-gpt"], nil) → (true, 0)
//   - MatchTags(["llm"], ["llm", ["python", "typescript"]], [["python", "typescript"]]) → (false, 0)
func (m *Matcher) MatchTags(providerTags, requiredTags []string, tagAlternatives [][]string) (bool, int) {
	score := 0

	// Process required tags (simple string tags with +/- operators)
	for _, reqTag := range requiredTags {
		if len(reqTag) == 0 {
			continue // Skip empty tags
		}

		switch reqTag[0] {
		case '-':
			// Excluded tag: must NOT be present
			excludedTag := reqTag[1:]
			if excludedTag != "" && containsTag(providerTags, excludedTag) {
				return false, 0 // Hard failure if excluded tag is present
			}
			// No score change for excluded tags (they don't add value, just filter)

		case '+':
			// Preferred tag: bonus points if present, no penalty if missing
			preferredTag := reqTag[1:]
			if preferredTag != "" && containsTag(providerTags, preferredTag) {
				score += 10 // Bonus points for preferred tags
			}
			// No penalty if preferred tag is missing

		default:
			// Required tag: must be present
			if containsTag(providerTags, reqTag) {
				score += 5 // Base points for required tags
			} else {
				return false, 0 // Hard failure if required tag is missing
			}
		}
	}

	// Process OR alternatives (if provided)
	// Each OR group must have at least one matching tag
	// Supports +/- operators within OR groups:
	// - No prefix: required alternative
	// - "+": preferred alternative (bonus score if matched)
	// - "-": excluded (fail if this tag is present)
	for _, orGroup := range tagAlternatives {
		if len(orGroup) == 0 {
			continue // Skip empty OR groups
		}

		// At least one tag in this OR group must match
		matched := false
		matchScore := 0
		for _, altTag := range orGroup {
			if len(altTag) == 0 {
				continue
			}

			switch altTag[0] {
			case '-':
				// Excluded alternative: fail if present
				excludedTag := altTag[1:]
				if excludedTag != "" && containsTag(providerTags, excludedTag) {
					return false, 0 // Hard failure if excluded tag is present
				}
				// Don't count as "matched" - exclusions are filters, not matches

			case '+':
				// Preferred alternative: bonus score if matched
				preferredTag := altTag[1:]
				if preferredTag != "" && containsTag(providerTags, preferredTag) {
					matched = true
					matchScore = 10 // Bonus for preferred
				}

			default:
				// Required alternative: base score if matched
				if containsTag(providerTags, altTag) {
					matched = true
					if matchScore < 5 { // Don't override higher score from preferred
						matchScore = 5
					}
				}
			}
		}

		if !matched {
			return false, 0 // Hard failure if no alternative in OR group matched
		}
		score += matchScore
	}

	return true, score
}

// MatchCandidate checks if a candidate satisfies a DependencySpec.
// Returns (matches, score) where score is used for ranking multiple matches.
func (m *Matcher) MatchCandidate(candidate Candidate, spec DependencySpec) (bool, int) {
	// Capability must match exactly
	if candidate.Capability != spec.Capability {
		return false, 0
	}

	// Version matching
	if spec.Version != "" && !m.MatchVersion(candidate.Version, spec.Version) {
		return false, 0
	}

	// Tag matching with scoring
	return m.MatchTags(candidate.Tags, spec.Tags, spec.TagAlternatives)
}

// containsTag checks if a tag exists in a slice of tags.
func containsTag(tags []string, tag string) bool {
	for _, t := range tags {
		if t == tag {
			return true
		}
	}
	return false
}

// hasAllTags checks if all required tags are present in available tags.
// Simple AND logic without +/- operators.
func hasAllTags(available, required []string) bool {
	for _, req := range required {
		if !containsTag(available, req) {
			return false
		}
	}
	return true
}

// Package-level convenience functions for use without a Matcher instance.
// These use a nil-logger matcher for simpler API in places that don't need logging.

// matchesVersion is a package-level convenience function for version matching.
// Used by llm_filtering.go and llm_provider_resolver.go.
func matchesVersion(version, constraint string) bool {
	return (&Matcher{}).MatchVersion(version, constraint)
}

// matchesEnhancedTags is a package-level convenience function for tag matching.
// Uses variadic tagAlternatives to match the original function signature.
// Used by llm_filtering.go and llm_provider_resolver.go.
func matchesEnhancedTags(providerTags, requiredTags []string, tagAlternatives ...[][]string) (bool, int) {
	var alts [][]string
	if len(tagAlternatives) > 0 {
		alts = tagAlternatives[0]
	}
	return (&Matcher{}).MatchTags(providerTags, requiredTags, alts)
}
