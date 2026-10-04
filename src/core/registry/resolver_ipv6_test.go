package registry

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"testing"

	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
)

// registerIPv6Pair registers a provider advertising providerHost:providerPort
// and a consumer depending on its capability, and returns the endpoint the
// resolver handed the consumer.
func registerIPv6Pair(t *testing.T, service *EntService, providerHost string, providerPort int) string {
	t.Helper()
	_, err := service.RegisterAgent(&AgentRegistrationRequest{
		AgentID: "v6-provider",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "v6-provider",
			"version":    "1.0.0",
			"http_host":  providerHost,
			"http_port":  float64(providerPort),
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "get_date",
					"capability":    "date_service",
					"version":       "1.0.0",
				},
			},
		},
	})
	require.NoError(t, err, "provider registration")

	resp, err := service.RegisterAgent(&AgentRegistrationRequest{
		AgentID: "v6-consumer",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "v6-consumer",
			"version":    "1.0.0",
			"http_host":  "10.0.0.9",
			"http_port":  float64(9090),
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "greet",
					"capability":    "greeting",
					"version":       "1.0.0",
					"dependencies": []interface{}{
						map[string]interface{}{"capability": "date_service"},
					},
				},
			},
		},
	})
	require.NoError(t, err, "consumer registration")
	deps := resp.DependenciesResolved["greet"]
	require.Len(t, deps, 1, "consumer should resolve its date_service dependency")
	require.Equal(t, "v6-provider", deps[0].AgentID)
	return deps[0].Endpoint
}

// TestResolver_IPv6ProviderEndpointParses pins issue #1604: a provider that
// advertises an IPv6 literal as http_host used to be handed to consumers as
// http://fd00:10:244::5:8080, which url.Parse cannot split into a host and a
// port. The endpoint must bracket the literal. A host that is already
// bracketed must not be double-bracketed.
func TestResolver_IPv6ProviderEndpointParses(t *testing.T) {
	for _, host := range []string{"fd00:10:244::5", "[fd00:10:244::5]"} {
		t.Run(host, func(t *testing.T) {
			service := setupTestService(t)
			endpoint := registerIPv6Pair(t, service, host, 8080)

			require.Equal(t, "http://[fd00:10:244::5]:8080", endpoint)
			u, err := url.Parse(endpoint)
			require.NoError(t, err, "resolved endpoint %q must parse", endpoint)
			require.Equal(t, "fd00:10:244::5", u.Hostname())
			require.Equal(t, "8080", u.Port())

			// The agents list builds the same endpoint independently.
			list, err := service.ListAgents(&AgentQueryParams{})
			require.NoError(t, err)
			found := false
			for _, a := range list.Agents {
				if a.Id == "v6-provider" {
					found = true
					require.Equal(t, "http://[fd00:10:244::5]:8080", a.Endpoint)
				}
			}
			require.True(t, found, "provider missing from the agents list")
		})
	}
}

// TestResolver_IPv6ProviderEndpointDials goes one step further than parsing:
// a provider actually listening on the IPv6 loopback is reachable at the
// endpoint the resolver hands the consumer. Skipped where the host has no
// IPv6 loopback (some CI containers).
func TestResolver_IPv6ProviderEndpointDials(t *testing.T) {
	ln, err := net.Listen("tcp", "[::1]:0")
	if err != nil {
		t.Skipf("no IPv6 loopback on this host: %v", err)
	}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))
	srv.Listener = ln
	srv.Start()
	defer srv.Close()

	port := ln.Addr().(*net.TCPAddr).Port
	service := setupTestService(t)
	endpoint := registerIPv6Pair(t, service, "::1", port)
	require.Equal(t, "http://[::1]:"+strconv.Itoa(port), endpoint)

	resp, err := http.Get(endpoint + "/mcp")
	require.NoError(t, err, "consumer could not reach the resolved endpoint %q", endpoint)
	resp.Body.Close()
	require.Equal(t, http.StatusNoContent, resp.StatusCode)
}

// TestEndpoints_UnspecifiedBindHostMapsToLocalhost pins that every endpoint
// builder handed to consumers maps an unspecified bind address — IPv4 or
// IPv6, bracketed or not — to localhost. The LLM tool and provider paths
// used to map only 0.0.0.0, and the dependency resolver mapped nothing, so
// a provider advertising its bind address was handed out as
// http://0.0.0.0:8080 (or an unparseable http://:::8080).
func TestEndpoints_UnspecifiedBindHostMapsToLocalhost(t *testing.T) {
	for _, host := range []string{"0.0.0.0", "::", "[::]"} {
		t.Run(host, func(t *testing.T) {
			service := setupTestService(t)
			require.Equal(t, "http://localhost:8080", registerIPv6Pair(t, service, host, 8080),
				"dependency resolver endpoint")

			capRow := &ent.Capability{Edges: ent.CapabilityEdges{Agent: &ent.Agent{ID: "p", HTTPHost: host, HTTPPort: 8080}}}
			require.Equal(t, "http://localhost:8080", buildEndpoint(capRow), "LLM tool endpoint")
			require.Equal(t, "http://localhost:8080", buildProviderEndpoint(capRow), "LLM provider endpoint")
		})
	}

	// A real address is left alone on every path.
	capRow := &ent.Capability{Edges: ent.CapabilityEdges{Agent: &ent.Agent{ID: "p", HTTPHost: "fd00::5", HTTPPort: 8080}}}
	require.Equal(t, "http://[fd00::5]:8080", buildEndpoint(capRow))
	require.Equal(t, "http://[fd00::5]:8080", buildProviderEndpoint(capRow))
}

// TestProxyRegistrationCheck_BracketedAndBareIPv6Match pins that the proxy's
// registered-agent check compares hosts unbracketed: an agent that
// registered its IPv6 http_host as "[::1]" or "::1" is reachable through
// /proxy/[::1]:<port>/..., and the dial target is bracketed exactly once.
func TestProxyRegistrationCheck_BracketedAndBareIPv6Match(t *testing.T) {
	for _, registered := range []string{"[::1]", "::1"} {
		t.Run(registered, func(t *testing.T) {
			service := setupTestService(t)
			registerProxyTargetAgent(t, service, "v6-agent", registered, 8443)
			h := NewEntBusinessLogicHandlers(service)

			ok, scheme, dial, err := h.isRegisteredAgentEndpoint(context.Background(), "[::1]:8443")
			require.NoError(t, err)
			require.True(t, ok, "agent registered as %q not matched by /proxy/[::1]:8443", registered)
			require.Equal(t, "http", scheme)
			require.Equal(t, "[::1]:8443", dial)

			ok, _, _, err = h.isRegisteredAgentEndpoint(context.Background(), "[::2]:8443")
			require.NoError(t, err)
			require.False(t, ok, "a different IPv6 host must not match")
		})
	}
}
