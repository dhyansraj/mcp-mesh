package registry

import (
	"crypto/md5"
	"encoding/json"
	"fmt"
	"sync"
	"time"
)

// cache provides simple in-memory caching with TTL
type cache struct {
	mu    sync.RWMutex
	items map[string]*cacheItem
	ttl   time.Duration
}

// cacheItem represents a cached value
type cacheItem struct {
	value     interface{}
	expiresAt time.Time
}

// newCache creates a new cache instance
func newCache(ttl time.Duration) *cache {
	c := &cache{
		items: make(map[string]*cacheItem),
		ttl:   ttl,
	}

	// Start cleanup goroutine
	go c.cleanup()

	return c
}

// get retrieves a value from cache
func (c *cache) get(key string) interface{} {
	c.mu.RLock()
	defer c.mu.RUnlock()

	item, exists := c.items[key]
	if !exists {
		return nil
	}

	if time.Now().After(item.expiresAt) {
		return nil
	}

	return item.value
}

// set stores a value in cache
func (c *cache) set(key string, value interface{}) {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.items[key] = &cacheItem{
		value:     value,
		expiresAt: time.Now().Add(c.ttl),
	}
}

// invalidate clears the entire cache
func (c *cache) invalidate() {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.items = make(map[string]*cacheItem)
}

// generateCacheKey creates a cache key from request parameters
func (c *cache) generateCacheKey(prefix string, params interface{}) string {
	data, _ := json.Marshal(params)
	hash := md5.Sum(data)
	return fmt.Sprintf("%s:%x", prefix, hash)
}

// cleanup periodically removes expired items
func (c *cache) cleanup() {
	ticker := time.NewTicker(c.ttl)
	defer ticker.Stop()

	for range ticker.C {
		c.mu.Lock()
		now := time.Now()
		for key, item := range c.items {
			if now.After(item.expiresAt) {
				delete(c.items, key)
			}
		}
		c.mu.Unlock()
	}
}
