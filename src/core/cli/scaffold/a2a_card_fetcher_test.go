package scaffold

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

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

	card, err := FetchAgentCard(srv.URL + "/agents/date")
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

	card, err := FetchAgentCard(srv.URL)
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

	card, err := FetchAgentCard(srv.URL)
	require.NoError(t, err)
	require.Len(t, card.Skills, 3)
	assert.Equal(t, "skill-two", card.Skills[1].ID)
}

func TestFetchAgentCard_HTTPError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "not found", http.StatusNotFound)
	}))
	defer srv.Close()

	_, err := FetchAgentCard(srv.URL)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "HTTP 404")
}

func TestFetchAgentCard_InvalidJSON(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("not json"))
	}))
	defer srv.Close()

	_, err := FetchAgentCard(srv.URL)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to parse agent card JSON")
}

func TestFetchAgentCard_EmptySkills(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"name":"x","version":"1","skills":[]}`))
	}))
	defer srv.Close()

	_, err := FetchAgentCard(srv.URL)
	require.Error(t, err)
	assert.True(t, strings.Contains(err.Error(), "no skills"))
}

func TestFetchAgentCard_BadURL(t *testing.T) {
	_, err := FetchAgentCard("not-a-url")
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

	_, err := FetchAgentCard(srv.URL)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "agent card body exceeded")
}
