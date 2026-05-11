package scaffold

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// maxAgentCardBytes caps the size of an /.well-known/agent.json response body.
// A2A v1.0 cards are typically well under 10 KB; 1 MiB is generous and
// prevents a hostile producer from exhausting memory via an unbounded body.
const maxAgentCardBytes = 1024 * 1024 // 1 MiB

// AgentCard mirrors the A2A v1.0 /.well-known/agent.json shape (issue #909).
// Only fields the scaffolder reads are typed; unknown fields are ignored
// so future card extensions don't break consumer scaffolding.
type AgentCard struct {
	Name           string      `json:"name"`
	Description    string      `json:"description"`
	Version        string      `json:"version"`
	URL            string      `json:"url"`
	Authentication CardAuth    `json:"authentication"`
	Skills         []CardSkill `json:"skills"`
}

// CardAuth captures the authentication.schemes list from the card.
// A2A v1.0 advertises schemes by name (e.g. "bearer", "oauth2").
type CardAuth struct {
	Schemes []string `json:"schemes"`
}

// CardSkill is one entry in the card's skills[] array. Each skill becomes
// one mesh capability in the generated consumer.
type CardSkill struct {
	ID          string                 `json:"id"`
	Name        string                 `json:"name"`
	Description string                 `json:"description"`
	Tags        []string               `json:"tags"`
	InputModes  []string               `json:"inputModes"`
	OutputModes []string               `json:"outputModes"`
	Metadata    map[string]interface{} `json:"metadata"`
}

// FetchAgentCard fetches and parses the A2A v1.0 agent card from
// {url}/.well-known/agent.json. The producerURL may be either a base URL
// (the path is appended) or a full URL ending in /.well-known/agent.json.
//
// A2A v1.0 cards are publicly discoverable so the request is sent without
// auth headers (per design decision: do NOT fetch with auth).
func FetchAgentCard(producerURL string) (*AgentCard, error) {
	cardURL, err := normalizeCardURL(producerURL)
	if err != nil {
		return nil, fmt.Errorf("invalid producer URL: %w", err)
	}

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(cardURL)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch agent card from %s: %w", cardURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("agent card fetch returned HTTP %d for %s", resp.StatusCode, cardURL)
	}

	// Read one byte beyond the cap so we can detect oversize bodies
	// without first slurping the entire (potentially huge) response.
	limited := io.LimitReader(resp.Body, maxAgentCardBytes+1)
	body, err := io.ReadAll(limited)
	if err != nil {
		return nil, fmt.Errorf("failed to read agent card response: %w", err)
	}
	if int64(len(body)) > maxAgentCardBytes {
		return nil, fmt.Errorf("agent card body exceeded %d bytes (got %d) — refusing to parse", maxAgentCardBytes, len(body))
	}

	var card AgentCard
	if err := json.Unmarshal(body, &card); err != nil {
		return nil, fmt.Errorf("failed to parse agent card JSON: %w", err)
	}

	if len(card.Skills) == 0 {
		return nil, fmt.Errorf("agent card has no skills (cannot generate consumer)")
	}

	return &card, nil
}

// normalizeCardURL accepts a base producer URL or a full
// /.well-known/agent.json URL and always returns the latter.
func normalizeCardURL(producerURL string) (string, error) {
	u, err := url.Parse(producerURL)
	if err != nil {
		return "", err
	}
	if u.Scheme == "" || u.Host == "" {
		return "", fmt.Errorf("URL must include scheme and host")
	}
	p := strings.TrimRight(u.Path, "/")
	if !strings.HasSuffix(p, "/.well-known/agent.json") {
		p = p + "/.well-known/agent.json"
	}
	u.Path = p
	return u.String(), nil
}

// ProducerBaseURL strips the trailing /.well-known/agent.json (if present)
// from a producer URL. The returned base URL is what an A2A consumer's
// a2a_url should be set to (the JSON-RPC tasks/* entry point).
func ProducerBaseURL(producerURL string) string {
	u, err := url.Parse(producerURL)
	if err != nil {
		return producerURL
	}
	p := strings.TrimRight(u.Path, "/")
	p = strings.TrimSuffix(p, "/.well-known/agent.json")
	u.Path = p
	return u.String()
}

// hasBearerAuth reports whether the card advertises a "bearer" auth scheme.
// Match is case-insensitive to tolerate producer formatting variance.
func (c *AgentCard) hasBearerAuth() bool {
	for _, s := range c.Authentication.Schemes {
		if strings.EqualFold(s, "bearer") {
			return true
		}
	}
	return false
}
