package scaffold

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strings"
	"time"
)

// maxAgentCardBytes caps the size of an /.well-known/agent.json response body.
// A2A v1.0 cards are typically well under 10 KB; 1 MiB is generous and
// prevents a hostile producer from exhausting memory via an unbounded body.
const maxAgentCardBytes = 1024 * 1024 // 1 MiB

// maxCardRedirects bounds redirect chains during card fetch. Go's default
// is 10; a card-fetch realistically needs zero or one. Tighter is fine.
const maxCardRedirects = 5

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

// FetchOptions tunes FetchAgentCard's network behavior. The zero value is
// the secure default: private/loopback/link-local destinations rejected,
// redirects bounded to maxCardRedirects.
type FetchOptions struct {
	// AllowPrivateNetwork disables the SSRF guard so the fetcher can reach
	// localhost / RFC1918 / link-local destinations. Tests and local-dev
	// flows opt in via --allow-private-network on the CLI.
	AllowPrivateNetwork bool
}

// errPrivateDestination is returned by the SSRF guard so callers (the
// CheckRedirect closure, the dialer, etc.) can wrap it with context-
// specific error messages naming the offending IP and host.
var errPrivateDestination = errors.New("destination resolves to a private/loopback/link-local IP")

// FetchAgentCard fetches and parses the A2A v1.0 agent card from
// {url}/.well-known/agent.json. The producerURL may be either a base URL
// (the path is appended) or a full URL ending in /.well-known/agent.json.
//
// A2A v1.0 cards are publicly discoverable so the request is sent without
// auth headers (per design decision: do NOT fetch with auth).
//
// SSRF protection (issue #928): by default the fetcher rejects URLs whose
// host resolves to a loopback, link-local (incl. 169.254.169.254 cloud
// metadata), or RFC1918 private address. Both the initial URL and every
// redirect destination are checked, and the underlying TCP dial re-checks
// the resolved IP at connection time so a hostname cannot pass the static
// check and then be re-resolved to a private IP at dial time (TOCTOU).
// Pass FetchOptions{AllowPrivateNetwork: true} to disable for local dev.
func FetchAgentCard(producerURL string, opts FetchOptions) (*AgentCard, error) {
	cardURL, err := normalizeCardURL(producerURL)
	if err != nil {
		return nil, fmt.Errorf("invalid producer URL: %w", err)
	}

	// Up-front check on the initial URL so the user gets a clear "private IP
	// rejected" message rather than a generic dial error from the transport.
	if !opts.AllowPrivateNetwork {
		if err := checkURLHostPublic(cardURL); err != nil {
			return nil, err
		}
	}

	client := newCardFetchClient(opts)
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

// newCardFetchClient builds an http.Client with:
//   - 10 s overall timeout (preserved from the original implementation)
//   - CheckRedirect that bounds the chain to maxCardRedirects and (unless
//     AllowPrivateNetwork) rejects redirects to private destinations
//   - DialContext that re-checks every resolved IP at connection time so a
//     hostname cannot resolve public on the static check and private on
//     the dial (TOCTOU mitigation; the bulletproof layer)
func newCardFetchClient(opts FetchOptions) *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if !opts.AllowPrivateNetwork {
		baseDialer := &net.Dialer{Timeout: 10 * time.Second}
		transport.DialContext = func(ctx context.Context, network, addr string) (net.Conn, error) {
			host, port, err := net.SplitHostPort(addr)
			if err != nil {
				return nil, err
			}
			ips, err := net.DefaultResolver.LookupHost(ctx, host)
			if err != nil {
				return nil, fmt.Errorf("dns lookup for %s failed: %w", host, err)
			}
			for _, ipStr := range ips {
				addr, ok := parseIP(ipStr)
				if !ok {
					return nil, fmt.Errorf("dial: cannot parse resolved IP %q for %s", ipStr, host)
				}
				if isBlockedAddr(addr) {
					return nil, fmt.Errorf("refusing to dial %s (resolves to %s, a private/loopback/link-local address); pass --allow-private-network to override: %w", host, addr, errPrivateDestination)
				}
			}
			// Use the first resolved IP. This guarantees the IP we just
			// validated is the one we actually connect to (defeats DNS
			// rebinding between LookupHost and the kernel's own resolve).
			return baseDialer.DialContext(ctx, network, net.JoinHostPort(ips[0], port))
		}
	}

	return &http.Client{
		Timeout:   10 * time.Second,
		Transport: transport,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= maxCardRedirects {
				return fmt.Errorf("stopped after %d redirects (cap is %d) for %s", len(via), maxCardRedirects, req.URL.String())
			}
			if !opts.AllowPrivateNetwork {
				if err := checkURLHostPublic(req.URL.String()); err != nil {
					return fmt.Errorf("refusing redirect: %w", err)
				}
			}
			return nil
		},
	}
}

// checkURLHostPublic resolves the URL's host and verifies that NO resolved
// IP falls in a blocked range. A single private answer is enough to reject
// — defense in depth against split-horizon DNS or multi-A records.
func checkURLHostPublic(rawURL string) error {
	u, err := url.Parse(rawURL)
	if err != nil {
		return fmt.Errorf("invalid URL %q: %w", rawURL, err)
	}
	host := u.Hostname()
	if host == "" {
		return fmt.Errorf("URL %q has no host", rawURL)
	}

	// If the host is already a literal IP, check it directly without DNS.
	if addr, ok := parseIP(host); ok {
		if isBlockedAddr(addr) {
			return fmt.Errorf("refusing to fetch %s: %s is a private/loopback/link-local address; pass --allow-private-network to override: %w", rawURL, addr, errPrivateDestination)
		}
		return nil
	}

	ips, err := net.LookupHost(host)
	if err != nil {
		return fmt.Errorf("dns lookup for %s failed: %w", host, err)
	}
	for _, ipStr := range ips {
		addr, ok := parseIP(ipStr)
		if !ok {
			return fmt.Errorf("cannot parse resolved IP %q for %s", ipStr, host)
		}
		if isBlockedAddr(addr) {
			return fmt.Errorf("refusing to fetch %s: %s resolves to %s, a private/loopback/link-local address; pass --allow-private-network to override", rawURL, host, addr)
		}
	}
	return nil
}

// parseIP accepts both bracketless ("::1") and bracketed ("[::1]") IPv6
// literals as well as plain IPv4. The bracketed form turns up when callers
// hand us url.Hostname() output for some inputs and url.URL.Host for others.
func parseIP(s string) (netip.Addr, bool) {
	s = strings.TrimPrefix(strings.TrimSuffix(s, "]"), "[")
	addr, err := netip.ParseAddr(s)
	if err != nil {
		return netip.Addr{}, false
	}
	return addr, true
}

// isBlockedAddr reports whether addr falls in a range we refuse to fetch
// from by default. Ranges, in priority order:
//
//	IPv4: 0.0.0.0/8, 10/8, 127/8, 169.254/16, 172.16/12, 192.168/16
//	IPv6: ::1, fc00::/7 (ULA), fe80::/10 (link-local)
//
// We deliberately also reject IPv4-mapped IPv6 forms of any of the above
// (an attacker could otherwise smuggle 127.0.0.1 in via "::ffff:127.0.0.1").
func isBlockedAddr(addr netip.Addr) bool {
	if !addr.IsValid() {
		return true
	}
	// Unwrap IPv4-in-IPv6 so a single set of checks covers both forms.
	if addr.Is4In6() {
		addr = addr.Unmap()
	}
	switch {
	case addr.IsLoopback():
		return true
	case addr.IsLinkLocalUnicast(), addr.IsLinkLocalMulticast():
		return true
	case addr.IsPrivate():
		return true
	case addr.IsUnspecified():
		return true
	case addr.IsMulticast():
		return true
	}
	if addr.Is4() {
		b := addr.As4()
		// 0.0.0.0/8 — "this network", per RFC 1122. Some stacks route
		// 0.x.y.z to localhost; reject defensively.
		if b[0] == 0 {
			return true
		}
	}
	return false
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
