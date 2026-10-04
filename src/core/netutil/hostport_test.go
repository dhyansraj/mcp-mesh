package netutil

import (
	"net"
	"net/url"
	"testing"
)

func TestJoinHostPortAndBaseURL(t *testing.T) {
	tests := []struct {
		host     string
		wantAddr string
		wantHost string // url.Hostname() of BaseURL
	}{
		{"localhost", "localhost:8080", "localhost"},
		{"10.0.0.5", "10.0.0.5:8080", "10.0.0.5"},
		{"agent.ns.svc.cluster.local", "agent.ns.svc.cluster.local:8080", "agent.ns.svc.cluster.local"},
		{"::1", "[::1]:8080", "::1"},
		{"fd00:10:244::5", "[fd00:10:244::5]:8080", "fd00:10:244::5"},
		{"[::1]", "[::1]:8080", "::1"}, // already bracketed stays single-bracketed
	}
	for _, tc := range tests {
		t.Run(tc.host, func(t *testing.T) {
			addr := JoinHostPort(tc.host, 8080)
			if addr != tc.wantAddr {
				t.Fatalf("JoinHostPort(%q) = %q, want %q", tc.host, addr, tc.wantAddr)
			}
			if _, _, err := net.SplitHostPort(addr); err != nil {
				t.Fatalf("JoinHostPort(%q) = %q does not split: %v", tc.host, addr, err)
			}

			u, err := url.Parse(BaseURL("http", tc.host, 8080))
			if err != nil {
				t.Fatalf("BaseURL(%q) does not parse: %v", tc.host, err)
			}
			if u.Hostname() != tc.wantHost || u.Port() != "8080" {
				t.Errorf("BaseURL(%q) parsed to host=%q port=%q, want %q/8080", tc.host, u.Hostname(), u.Port(), tc.wantHost)
			}
		})
	}
}

func TestDialableHost(t *testing.T) {
	tests := map[string]string{
		"":                "localhost",
		"0.0.0.0":         "localhost",
		"::":              "localhost",
		"[::]":            "localhost",
		"0:0:0:0:0:0:0:0": "localhost",
		"localhost":       "localhost",
		"10.0.0.5":        "10.0.0.5",
		"::1":             "::1",
		"[::1]":           "[::1]",
		"agent.ns":        "agent.ns",
	}
	for in, want := range tests {
		if got := DialableHost(in); got != want {
			t.Errorf("DialableHost(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestUnbracket(t *testing.T) {
	tests := map[string]string{"[::1]": "::1", "::1": "::1", "host": "host", "[": "[", "": ""}
	for in, want := range tests {
		if got := Unbracket(in); got != want {
			t.Errorf("Unbracket(%q) = %q, want %q", in, got, want)
		}
	}
}
