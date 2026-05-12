package scaffold

import (
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// allowLocal is the default test option set: httptest.NewServer always
// listens on 127.0.0.1, so functional tests must opt out of the SSRF guard.
// SSRF tests construct their own FetchOptions explicitly.
var allowLocal = FetchOptions{AllowPrivateNetwork: true}

func TestNormalizeCardURL(t *testing.T) {
	cases := []struct {
		in      string
		want    string
		wantErr bool
	}{
		{"https://example.com/agents/foo", "https://example.com/agents/foo/.well-known/agent.json", false},
		{"https://example.com/agents/foo/", "https://example.com/agents/foo/.well-known/agent.json", false},
		{"https://example.com/agents/foo/.well-known/agent.json", "https://example.com/agents/foo/.well-known/agent.json", false},
		{"http://localhost:9090/agents/date", "http://localhost:9090/agents/date/.well-known/agent.json", false},
		{"http://localhost:9090/agents/date/.well-known/agent.json", "http://localhost:9090/agents/date/.well-known/agent.json", false},
		{"https://example.com", "https://example.com/.well-known/agent.json", false},

		{"not-a-url", "", true},
		{"/just/a/path", "", true},
	}

	for _, tc := range cases {
		t.Run(tc.in, func(t *testing.T) {
			got, err := normalizeCardURL(tc.in)
			if tc.wantErr {
				assert.Error(t, err)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tc.want, got)
		})
	}
}

func TestProducerBaseURL(t *testing.T) {
	cases := []struct {
		in   string
		want string
	}{
		{"http://localhost:9090/agents/date", "http://localhost:9090/agents/date"},
		{"http://localhost:9090/agents/date/", "http://localhost:9090/agents/date"},
		{"http://localhost:9090/agents/date/.well-known/agent.json", "http://localhost:9090/agents/date"},
		{"https://example.com", "https://example.com"},
	}
	for _, tc := range cases {
		t.Run(tc.in, func(t *testing.T) {
			assert.Equal(t, tc.want, ProducerBaseURL(tc.in))
		})
	}
}

func TestFetchAgentCard_HappyPath(t *testing.T) {
	body := `{
		"name": "Date Agent",
		"description": "Returns the current date",
		"version": "1.0.0",
		"url": "http://localhost:9090/agents/date",
		"authentication": {"schemes": []},
		"skills": [
			{
				"id": "get-date",
				"name": "Get Date",
				"description": "Return today's date",
				"tags": ["date", "utility"],
				"inputModes": ["application/json"],
				"outputModes": ["application/json"]
			}
		]
	}`

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "/agents/date/.well-known/agent.json", r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()

	card, err := FetchAgentCard(srv.URL+"/agents/date", allowLocal)
	require.NoError(t, err)
	require.NotNil(t, card)

	assert.Equal(t, "Date Agent", card.Name)
	assert.Equal(t, "1.0.0", card.Version)
	require.Len(t, card.Skills, 1)
	assert.Equal(t, "get-date", card.Skills[0].ID)
	assert.Equal(t, "Get Date", card.Skills[0].Name)
	assert.Contains(t, card.Skills[0].Tags, "date")
	assert.False(t, card.hasBearerAuth())
}

func TestFetchAgentCard_BearerAuth(t *testing.T) {
	body := `{
		"name": "Secured Agent",
		"version": "1.0.0",
		"authentication": {"schemes": ["Bearer"]},
		"skills": [{"id": "x", "name": "X"}]
	}`

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()

	card, err := FetchAgentCard(srv.URL, allowLocal)
	require.NoError(t, err)
	assert.True(t, card.hasBearerAuth(), "bearer auth must be detected case-insensitively")
}

func TestFetchAgentCard_MultipleSkills(t *testing.T) {
	body := `{
		"name": "Multi Agent",
		"version": "1.0.0",
		"skills": [
			{"id": "skill-one", "name": "Skill One", "tags": ["a"]},
			{"id": "skill-two", "name": "Skill Two", "tags": ["b"]},
			{"id": "skill-three", "name": "Skill Three"}
		]
	}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()

	card, err := FetchAgentCard(srv.URL, allowLocal)
	require.NoError(t, err)
	require.Len(t, card.Skills, 3)
	assert.Equal(t, "skill-two", card.Skills[1].ID)
}

func TestFetchAgentCard_HTTPError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "not found", http.StatusNotFound)
	}))
	defer srv.Close()

	_, err := FetchAgentCard(srv.URL, allowLocal)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "HTTP 404")
}

func TestFetchAgentCard_InvalidJSON(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("not json"))
	}))
	defer srv.Close()

	_, err := FetchAgentCard(srv.URL, allowLocal)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to parse agent card JSON")
}

func TestFetchAgentCard_EmptySkills(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"name":"x","version":"1","skills":[]}`))
	}))
	defer srv.Close()

	_, err := FetchAgentCard(srv.URL, allowLocal)
	require.Error(t, err)
	assert.True(t, strings.Contains(err.Error(), "no skills"))
}

func TestFetchAgentCard_BadURL(t *testing.T) {
	_, err := FetchAgentCard("not-a-url", allowLocal)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "invalid producer URL")
}

func TestFetchAgentCard_RejectsOversizeBody(t *testing.T) {
	// Serve a body just over the 1 MiB cap. Content type is irrelevant —
	// the fetcher must short-circuit before JSON parsing.
	oversize := make([]byte, maxAgentCardBytes+1024)
	for i := range oversize {
		oversize[i] = 'a'
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write(oversize)
	}))
	defer srv.Close()

	_, err := FetchAgentCard(srv.URL, allowLocal)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "agent card body exceeded")
}

// ---------------------------------------------------------------------------
// SSRF guard (issue #928)
// ---------------------------------------------------------------------------

// TestIsBlockedAddr_AllRanges is the primary unit table for the IP guard.
// Every blocked range cited in #928 must be represented here so a future
// refactor can't silently drop coverage.
func TestIsBlockedAddr_AllRanges(t *testing.T) {
	cases := []struct {
		ip      string
		blocked bool
		why     string
	}{
		// Loopback
		{"127.0.0.1", true, "IPv4 loopback"},
		{"127.1.2.3", true, "IPv4 loopback range 127/8"},
		{"::1", true, "IPv6 loopback"},

		// Link-local (the metadata target lives here)
		{"169.254.169.254", true, "IMDS (EC2/GCP/Azure metadata)"},
		{"169.254.0.1", true, "IPv4 link-local"},
		{"fe80::1", true, "IPv6 link-local"},

		// RFC 1918 private
		{"10.0.0.1", true, "RFC1918 10/8"},
		{"10.255.255.255", true, "RFC1918 10/8 high"},
		{"172.16.0.1", true, "RFC1918 172.16/12"},
		{"172.31.255.255", true, "RFC1918 172.16/12 high"},
		{"192.168.1.1", true, "RFC1918 192.168/16"},

		// IPv6 ULA
		{"fc00::1", true, "IPv6 unique-local fc00::/7"},
		{"fd12:3456:789a::1", true, "IPv6 unique-local fd00::/8"},

		// 0/8
		{"0.0.0.0", true, "unspecified / 0/8"},
		{"0.1.2.3", true, "0/8 'this network'"},

		// IPv4-in-IPv6 smuggling
		{"::ffff:127.0.0.1", true, "IPv4-mapped loopback"},
		{"::ffff:169.254.169.254", true, "IPv4-mapped IMDS"},

		// Public — must NOT be blocked
		{"8.8.8.8", false, "public DNS"},
		{"1.1.1.1", false, "public DNS"},
		{"172.15.0.1", false, "just below RFC1918 172.16/12"},
		{"172.32.0.1", false, "just above RFC1918 172.16/12"},
		{"2606:4700:4700::1111", false, "Cloudflare public IPv6"},
	}
	for _, tc := range cases {
		t.Run(tc.ip, func(t *testing.T) {
			addr, ok := parseIP(tc.ip)
			require.True(t, ok, "must parse %q", tc.ip)
			got := isBlockedAddr(addr)
			assert.Equal(t, tc.blocked, got, "%s (%s)", tc.ip, tc.why)
		})
	}
}

// TestFetchAgentCard_PrivateInitialURL_Rejected covers the gap the original
// issue body didn't mention: the user passing --url http://169.254.169.254/...
// directly. Without the guard, the scaffolder would just dial it.
func TestFetchAgentCard_PrivateInitialURL_Rejected(t *testing.T) {
	cases := []struct {
		url     string
		mention string // substring expected in the error
	}{
		{"http://127.0.0.1:8080", "127.0.0.1"},
		{"http://169.254.169.254", "169.254.169.254"},
		{"http://10.0.0.1", "10.0.0.1"},
		{"http://192.168.1.1", "192.168.1.1"},
		{"http://[::1]:8080", "::1"},
		{"http://[fe80::1]", "fe80::1"},
	}
	for _, tc := range cases {
		t.Run(tc.url, func(t *testing.T) {
			_, err := FetchAgentCard(tc.url, FetchOptions{})
			require.Error(t, err)
			assert.Contains(t, err.Error(), tc.mention,
				"error must name the offending IP")
			assert.Contains(t, err.Error(), "--allow-private-network",
				"error must hint at the override flag")
		})
	}

	// Sentinel reachability: callers can match the SSRF rejection with
	// errors.Is(err, errPrivateDestination) regardless of the wrapping
	// message. One assertion on the simplest path proves the wrap.
	_, err := FetchAgentCard("http://127.0.0.1:8080", FetchOptions{})
	require.Error(t, err)
	assert.True(t, errors.Is(err, errPrivateDestination),
		"SSRF rejection must wrap errPrivateDestination so callers can match with errors.Is")
}

// TestFetchAgentCard_PrivateInitialURL_AllowedWithFlag asserts the override
// flag actually disables the guard. We can't successfully dial these
// addresses (nothing listens), but the call must get past the static check
// — we assert the failure mode is "connection refused", not "private IP".
func TestFetchAgentCard_PrivateInitialURL_AllowedWithFlag(t *testing.T) {
	_, err := FetchAgentCard("http://127.0.0.1:1", FetchOptions{AllowPrivateNetwork: true})
	require.Error(t, err)
	assert.NotContains(t, err.Error(), "private/loopback/link-local",
		"with override flag, the SSRF guard must NOT fire")
	assert.NotContains(t, err.Error(), "--allow-private-network",
		"override-already-set error must not re-suggest the flag")
}

// TestFetchAgentCard_RedirectToPrivate_Rejected: a public-looking server
// 302s to a loopback URL — the redirect must be refused.
func TestFetchAgentCard_RedirectToPrivate_Rejected(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Redirect(w, &http.Request{}, "http://169.254.169.254/.well-known/agent.json", http.StatusFound)
	}))
	defer srv.Close()

	// Use the override on the initial URL (httptest always binds 127.0.0.1)
	// but NOT a way to override per-redirect — that's the whole point: even
	// with AllowPrivateNetwork the redirect destination is checked when the
	// flag is OFF. So construct opts that allow the initial dial but block
	// the redirect.
	//
	// We can't do that in the current API (the flag is global). Instead,
	// re-aim the test: spin up TWO servers; the second one redirects to a
	// private destination AND the run is with allowPrivate=false. The
	// initial-URL guard would reject srv.URL too (it's 127.0.0.1), so we
	// instead exercise the CheckRedirect closure directly.
	client := newCardFetchClient(FetchOptions{})
	req, err := http.NewRequest("GET", "http://example.com/.well-known/agent.json", nil)
	require.NoError(t, err)

	// Synthesize a redirect hop: build a "via" chain and a target.
	target, err := http.NewRequest("GET", "http://169.254.169.254/agent.json", nil)
	require.NoError(t, err)
	err = client.CheckRedirect(target, []*http.Request{req})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "169.254.169.254")
	assert.Contains(t, err.Error(), "--allow-private-network")
}

// TestFetchAgentCard_RedirectToPrivate_AllowedWithFlag — same scenario but
// the override flag is set, and the redirect is permitted.
func TestFetchAgentCard_RedirectToPrivate_AllowedWithFlag(t *testing.T) {
	client := newCardFetchClient(FetchOptions{AllowPrivateNetwork: true})
	req, _ := http.NewRequest("GET", "http://example.com/.well-known/agent.json", nil)
	target, _ := http.NewRequest("GET", "http://127.0.0.1:8080/agent.json", nil)
	err := client.CheckRedirect(target, []*http.Request{req})
	assert.NoError(t, err, "with flag, private redirect must be permitted")
}

// TestFetchAgentCard_RedirectChainBounded — chain longer than maxCardRedirects
// is rejected by CheckRedirect with a clear message naming the cap.
func TestFetchAgentCard_RedirectChainBounded(t *testing.T) {
	// Build a chain at the cap, then verify the next hop is refused.
	via := make([]*http.Request, maxCardRedirects)
	for i := range via {
		via[i], _ = http.NewRequest("GET", fmt.Sprintf("http://hop-%d.example.com/", i), nil)
	}
	target, _ := http.NewRequest("GET", "http://final.example.com/", nil)

	client := newCardFetchClient(FetchOptions{AllowPrivateNetwork: true})
	err := client.CheckRedirect(target, via)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stopped after")
	assert.Contains(t, err.Error(), fmt.Sprintf("cap is %d", maxCardRedirects))
}

// TestFetchAgentCard_RedirectChainEndToEnd verifies the full client honors
// the cap when the server actually serves a redirect loop. This catches
// regressions where CheckRedirect is wired up but the redirect cap message
// would otherwise be Go's default ("stopped after 10 redirects").
func TestFetchAgentCard_RedirectChainEndToEnd(t *testing.T) {
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Always redirect back to ourselves with a different path.
		http.Redirect(w, r, srv.URL+r.URL.Path+"x", http.StatusFound)
	}))
	defer srv.Close()

	_, err := FetchAgentCard(srv.URL, allowLocal)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "stopped after",
		"redirect cap must engage end-to-end")
}

// TestCheckURLHostPublic_Hostname covers the hostname code path: "localhost"
// resolves (via /etc/hosts on every reasonable system) to 127.0.0.1 and
// must therefore be rejected.
func TestCheckURLHostPublic_Hostname(t *testing.T) {
	err := checkURLHostPublic("http://localhost:8080/x")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "localhost")
	assert.Contains(t, err.Error(), "--allow-private-network")
}
