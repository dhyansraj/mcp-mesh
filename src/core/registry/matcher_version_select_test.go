package registry

import (
	"sort"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

// TestCompareVersion verifies the "highest wins" ordering helper: valid semver
// compares numerically, valid always beats unparseable/empty, and two
// unparseable versions fall back to deterministic string comparison.
func TestCompareVersion(t *testing.T) {
	m := &Matcher{}

	assert.Positive(t, m.CompareVersion("2.0.0", "1.0.0"), "2.0.0 > 1.0.0")
	assert.Zero(t, m.CompareVersion("1.0.0", "1.0.0"), "1.0.0 == 1.0.0")
	// Numeric, not lexical: 1.2.0 < 1.10.0
	assert.Negative(t, m.CompareVersion("1.2.0", "1.10.0"), "1.2.0 < 1.10.0 numerically")
	assert.Negative(t, m.CompareVersion("", "1.0.0"), "empty ranks below valid semver")
	assert.Negative(t, m.CompareVersion("garbage", "1.0.0"), "unparseable ranks below valid semver")
	assert.Positive(t, m.CompareVersion("1.0.0", "garbage"), "valid semver ranks above unparseable")

	// Two unparseable versions: deterministic strings.Compare sign.
	want := strings.Compare("garbage", "other")
	got := m.CompareVersion("garbage", "other")
	assert.Equal(t, want, got, "two unparseable versions fall back to strings.Compare")

	// Package-level convenience mirrors the method.
	assert.Equal(t, m.CompareVersion("2.0.0", "1.0.0"), compareVersion("2.0.0", "1.0.0"))
}

// sortScored applies the exact tiebreaker ordering used by the resolver
// (score DESC, version DESC, agentID ASC) so selection can be asserted in
// isolation from the DB pipeline.
func sortScored(xs []scoredCandidateWithHealth) {
	m := &Matcher{}
	sort.SliceStable(xs, func(i, j int) bool {
		if xs[i].Score != xs[j].Score {
			return xs[i].Score > xs[j].Score
		}
		if vc := m.CompareVersion(xs[i].Version, xs[j].Version); vc != 0 {
			return vc > 0
		}
		return xs[i].AgentID < xs[j].AgentID
	})
}

func scored(agentID, version string, score int) scoredCandidateWithHealth {
	return scoredCandidateWithHealth{
		candidateWithHealth: candidateWithHealth{
			Candidate: Candidate{AgentID: agentID, Version: version},
		},
		Score: score,
	}
}

// TestTiebreakerSelection verifies the resolver's selection ordering: tag score
// is primary; among equal scores the highest version wins; identical
// score+version is broken by agent ID for determinism.
func TestTiebreakerSelection(t *testing.T) {
	t.Run("HighestVersionWinsAmongEqualScore", func(t *testing.T) {
		xs := []scoredCandidateWithHealth{
			scored("a", "4.6.0", 5),
			scored("b", "4.7.0", 5),
			scored("c", "5.0.0", 5),
		}
		sortScored(xs)
		assert.Equal(t, "c", xs[0].AgentID, "5.0.0 wins")
	})

	t.Run("HigherScoreBeatsHigherVersion", func(t *testing.T) {
		xs := []scoredCandidateWithHealth{
			scored("high-version", "9.9.9", 5),
			scored("preferred", "1.0.0", 10),
		}
		sortScored(xs)
		assert.Equal(t, "preferred", xs[0].AgentID, "tag score is primary")
	})

	t.Run("AgentIDBreaksScoreAndVersionTie", func(t *testing.T) {
		xs := []scoredCandidateWithHealth{
			scored("zeta", "1.0.0", 5),
			scored("alpha", "1.0.0", 5),
		}
		sortScored(xs)
		assert.Equal(t, "alpha", xs[0].AgentID, "lexicographically smallest agent ID wins ties")
	})
}
