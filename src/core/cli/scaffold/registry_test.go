package scaffold

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewProviderRegistry(t *testing.T) {
	registry := NewProviderRegistry()

	assert.NotNil(t, registry)
	assert.Empty(t, registry.List())
}

func TestProviderRegistry_Register(t *testing.T) {
	registry := NewProviderRegistry()
	provider := &MockProvider{name: "test", description: "Test provider"}

	err := registry.Register(provider)
	require.NoError(t, err)

	// Verify registration
	got, err := registry.Get("test")
	require.NoError(t, err)
	assert.Equal(t, provider, got)
}

func TestProviderRegistry_RegisterNil(t *testing.T) {
	registry := NewProviderRegistry()

	err := registry.Register(nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "provider cannot be nil")
}

func TestProviderRegistry_RegisterDuplicate(t *testing.T) {
	registry := NewProviderRegistry()
	provider := &MockProvider{name: "test", description: "Test provider"}

	err := registry.Register(provider)
	require.NoError(t, err)

	// Try to register again
	err = registry.Register(provider)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "already registered")
}

func TestProviderRegistry_GetNotFound(t *testing.T) {
	registry := NewProviderRegistry()

	_, err := registry.Get("nonexistent")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not found")
}

func TestProviderRegistry_List(t *testing.T) {
	registry := NewProviderRegistry()
	registry.Register(&MockProvider{name: "alpha"})
	registry.Register(&MockProvider{name: "beta"})

	names := registry.List()
	assert.Len(t, names, 2)
	assert.Contains(t, names, "alpha")
	assert.Contains(t, names, "beta")
}

func TestProviderRegistry_ListSorted(t *testing.T) {
	registry := NewProviderRegistry()
	registry.Register(&MockProvider{name: "zebra"})
	registry.Register(&MockProvider{name: "alpha"})
	registry.Register(&MockProvider{name: "beta"})

	names := registry.List()
	assert.Equal(t, []string{"alpha", "beta", "zebra"}, names)
}

func TestProviderRegistry_ThreadSafe(t *testing.T) {
	registry := NewProviderRegistry()

	// Register providers concurrently
	done := make(chan bool)
	for i := 0; i < 10; i++ {
		go func(n int) {
			provider := &MockProvider{name: string(rune('a' + n))}
			registry.Register(provider)
			done <- true
		}(i)
	}

	// Wait for all goroutines
	for i := 0; i < 10; i++ {
		<-done
	}

	// Should have registered providers without panicking
	names := registry.List()
	assert.Len(t, names, 10)
}

func TestDefaultRegistry(t *testing.T) {
	// DefaultRegistry should be initialized
	assert.NotNil(t, DefaultRegistry)
}
