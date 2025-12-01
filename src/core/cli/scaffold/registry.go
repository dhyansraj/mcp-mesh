package scaffold

import (
	"fmt"
	"sort"
	"sync"
)

// ProviderRegistry manages scaffold provider registration and lookup.
// It is thread-safe and supports concurrent access.
type ProviderRegistry struct {
	providers map[string]ScaffoldProvider
	mu        sync.RWMutex
}

// NewProviderRegistry creates a new empty provider registry
func NewProviderRegistry() *ProviderRegistry {
	return &ProviderRegistry{
		providers: make(map[string]ScaffoldProvider),
	}
}

// Register adds a provider to the registry.
// Returns an error if the provider is nil or already registered.
func (r *ProviderRegistry) Register(provider ScaffoldProvider) error {
	if provider == nil {
		return fmt.Errorf("provider cannot be nil")
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	name := provider.Name()
	if _, exists := r.providers[name]; exists {
		return fmt.Errorf("provider %q already registered", name)
	}

	r.providers[name] = provider
	return nil
}

// Get retrieves a provider by name.
// Returns an error if the provider is not found.
func (r *ProviderRegistry) Get(name string) (ScaffoldProvider, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	provider, exists := r.providers[name]
	if !exists {
		return nil, fmt.Errorf("provider %q not found", name)
	}

	return provider, nil
}

// List returns all registered provider names, sorted alphabetically.
func (r *ProviderRegistry) List() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	names := make([]string, 0, len(r.providers))
	for name := range r.providers {
		names = append(names, name)
	}

	sort.Strings(names)
	return names
}

// DefaultRegistry is the global provider registry used by the scaffold command.
// Providers register themselves with this registry during initialization.
var DefaultRegistry = NewProviderRegistry()
