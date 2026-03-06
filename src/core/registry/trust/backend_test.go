package trust

import (
	"errors"
	"testing"
)

func TestParseBackendConfig(t *testing.T) {
	tests := []struct {
		name   string
		input  string
		expect []string
	}{
		{
			name:   "empty string",
			input:  "",
			expect: nil,
		},
		{
			name:   "whitespace only",
			input:  "   ",
			expect: nil,
		},
		{
			name:   "single backend",
			input:  "filestore",
			expect: []string{"filestore"},
		},
		{
			name:   "two backends",
			input:  "filestore,k8s-secrets",
			expect: []string{"filestore", "k8s-secrets"},
		},
		{
			name:   "with whitespace",
			input:  " filestore , k8s-secrets ",
			expect: []string{"filestore", "k8s-secrets"},
		},
		{
			name:   "trailing comma",
			input:  "filestore,",
			expect: []string{"filestore"},
		},
		{
			name:   "empty entries filtered",
			input:  "filestore,,k8s-secrets",
			expect: []string{"filestore", "k8s-secrets"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := ParseBackendConfig(tt.input)
			if tt.expect == nil {
				if result != nil {
					t.Errorf("expected nil, got %v", result)
				}
				return
			}
			if len(result) != len(tt.expect) {
				t.Fatalf("expected %d items, got %d: %v", len(tt.expect), len(result), result)
			}
			for i, v := range result {
				if v != tt.expect[i] {
					t.Errorf("item %d: expected %q, got %q", i, tt.expect[i], v)
				}
			}
		})
	}
}

func TestSentinelErrors(t *testing.T) {
	// Verify sentinel errors are distinct and work with errors.Is
	errs := []error{ErrUntrustedCert, ErrExpiredCert, ErrNoCertPresented, ErrInvalidCertChain}
	for i, e1 := range errs {
		for j, e2 := range errs {
			if i != j && errors.Is(e1, e2) {
				t.Errorf("expected %v and %v to be distinct errors", e1, e2)
			}
		}
	}
}

func TestTrustedEntityMetadata(t *testing.T) {
	entity := TrustedEntity{
		ID:          "acme-corp",
		Subject:     "CN=acme-corp,OU=agents,O=Acme",
		Fingerprint: "AA:BB:CC:DD",
		Metadata:    map[string]string{"env": "production"},
	}

	if entity.Metadata["env"] != "production" {
		t.Errorf("expected metadata env=production, got %s", entity.Metadata["env"])
	}
}
