package trust

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
)

// entityCA holds the parsed CA certificates and metadata for a single entity.
type entityCA struct {
	id       string
	pool     *x509.CertPool
	certs    []*x509.Certificate
}

// FileStore is a TrustBackend that reads trusted entity CA PEM files from a directory.
type FileStore struct {
	dir     string
	mu      sync.RWMutex
	entities []entityCA
	watcher *fsnotify.Watcher
	done    chan struct{}
}

// NewFileStore creates a FileStore backend that reads CA PEM files from dir.
// If watch is true, it watches the directory for changes using fsnotify.
func NewFileStore(dir string, watch bool) (*FileStore, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return nil, fmt.Errorf("trust directory: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("trust directory %s is not a directory", dir)
	}

	fs := &FileStore{
		dir:  dir,
		done: make(chan struct{}),
	}

	if err := fs.loadAll(); err != nil {
		return nil, fmt.Errorf("loading trust store: %w", err)
	}

	if watch {
		if err := fs.startWatcher(); err != nil {
			return nil, fmt.Errorf("starting directory watcher: %w", err)
		}
	}

	return fs, nil
}

// Name returns the backend name.
func (fs *FileStore) Name() string {
	return "filestore"
}

// Verify checks whether the leaf certificate in certChain is trusted by any entity CA.
func (fs *FileStore) Verify(certChain []*x509.Certificate) (*VerifyResult, error) {
	if len(certChain) == 0 {
		return nil, ErrNoCertPresented
	}

	leaf := certChain[0]

	if leaf.IsCA {
		return nil, fmt.Errorf("presented certificate is a CA certificate, not a leaf")
	}

	now := time.Now()
	if now.After(leaf.NotAfter) {
		return nil, ErrExpiredCert
	}
	if now.Before(leaf.NotBefore) {
		return nil, ErrInvalidCertChain
	}

	// Build intermediate pool from remaining certs in the chain.
	intermediates := x509.NewCertPool()
	for _, c := range certChain[1:] {
		intermediates.AddCert(c)
	}

	fs.mu.RLock()
	defer fs.mu.RUnlock()

	for _, ent := range fs.entities {
		opts := x509.VerifyOptions{
			Roots:         ent.pool,
			Intermediates: intermediates,
			KeyUsages:     []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
		}
		if _, err := leaf.Verify(opts); err == nil {
			return &VerifyResult{
				EntityID:    ent.id,
				CertSubject: leaf.Subject.String(),
				BackendName: fs.Name(),
			}, nil
		}
	}

	return nil, ErrUntrustedCert
}

// ListTrustedEntities returns metadata for all loaded CA certificates.
func (fs *FileStore) ListTrustedEntities() ([]TrustedEntity, error) {
	fs.mu.RLock()
	defer fs.mu.RUnlock()

	var result []TrustedEntity
	for _, ent := range fs.entities {
		for _, cert := range ent.certs {
			fingerprint := sha256.Sum256(cert.Raw)
			result = append(result, TrustedEntity{
				ID:          ent.id,
				Subject:     cert.Subject.String(),
				NotBefore:   cert.NotBefore,
				NotAfter:    cert.NotAfter,
				Fingerprint: hex.EncodeToString(fingerprint[:]),
				Metadata: map[string]string{
					"source": "filestore",
					"file":   fs.dir,
				},
			})
		}
	}
	return result, nil
}

// Close stops the directory watcher if running.
func (fs *FileStore) Close() error {
	close(fs.done)
	if fs.watcher != nil {
		return fs.watcher.Close()
	}
	return nil
}

// loadAll reads all .pem files from the directory and parses them.
func (fs *FileStore) loadAll() error {
	entries, err := os.ReadDir(fs.dir)
	if err != nil {
		return fmt.Errorf("reading directory %s: %w", fs.dir, err)
	}

	var entities []entityCA
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".pem") {
			continue
		}
		ent, err := fs.loadPEMFile(filepath.Join(fs.dir, entry.Name()))
		if err != nil {
			log.Printf("[trust/filestore] skipping %s: %v", entry.Name(), err)
			continue
		}
		entities = append(entities, *ent)
	}

	// Also scan entities/ subdirectory (used by meshctl entity register)
	entitiesDir := filepath.Join(fs.dir, "entities")
	if entInfo, err := os.Stat(entitiesDir); err == nil && entInfo.IsDir() {
		entEntries, err := os.ReadDir(entitiesDir)
		if err == nil {
			for _, entry := range entEntries {
				if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".pem") {
					continue
				}
				ent, err := fs.loadPEMFile(filepath.Join(entitiesDir, entry.Name()))
				if err != nil {
					log.Printf("[trust/filestore] skipping entities/%s: %v", entry.Name(), err)
					continue
				}
				entities = append(entities, *ent)
			}
		}
	}

	fs.mu.Lock()
	fs.entities = entities
	fs.mu.Unlock()

	log.Printf("[trust/filestore] loaded %d entity CA(s) from %s", len(entities), fs.dir)
	return nil
}

// loadPEMFile parses a PEM file and returns an entityCA.
func (fs *FileStore) loadPEMFile(path string) (*entityCA, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading file: %w", err)
	}

	var certs []*x509.Certificate
	rest := data
	for {
		var block *pem.Block
		block, rest = pem.Decode(rest)
		if block == nil {
			break
		}
		if block.Type != "CERTIFICATE" {
			continue
		}
		cert, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			return nil, fmt.Errorf("parsing certificate: %w", err)
		}
		certs = append(certs, cert)
	}

	if len(certs) == 0 {
		return nil, fmt.Errorf("no certificates found in %s", path)
	}

	// Determine entity ID from the first certificate.
	id := extractEntityID(certs[0], path)

	pool := x509.NewCertPool()
	for _, c := range certs {
		if c.IsCA {
			pool.AddCert(c)
		}
	}

	return &entityCA{
		id:    id,
		pool:  pool,
		certs: certs,
	}, nil
}

// extractEntityID derives the entity ID from cert fields or falls back to filename.
func extractEntityID(cert *x509.Certificate, path string) string {
	if len(cert.Subject.Organization) > 0 && cert.Subject.Organization[0] != "" {
		return cert.Subject.Organization[0]
	}
	if len(cert.Subject.OrganizationalUnit) > 0 && cert.Subject.OrganizationalUnit[0] != "" {
		return cert.Subject.OrganizationalUnit[0]
	}
	base := filepath.Base(path)
	return strings.TrimSuffix(base, ".pem")
}

// startWatcher starts an fsnotify watcher on the directory and reloads on changes.
func (fs *FileStore) startWatcher() error {
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return fmt.Errorf("creating watcher: %w", err)
	}

	if err := watcher.Add(fs.dir); err != nil {
		watcher.Close()
		return fmt.Errorf("watching directory: %w", err)
	}

	entitiesDir := filepath.Join(fs.dir, "entities")
	if entInfo, err := os.Stat(entitiesDir); err == nil && entInfo.IsDir() {
		if err := watcher.Add(entitiesDir); err != nil {
			log.Printf("[trust/filestore] warning: cannot watch entities dir: %v", err)
		}
	}

	fs.watcher = watcher

	go func() {
		for {
			select {
			case <-fs.done:
				return
			case event, ok := <-watcher.Events:
				if !ok {
					return
				}
				// Watch newly created entities/ subdirectory
				if event.Has(fsnotify.Create) && filepath.Base(event.Name) == "entities" {
					if info, err := os.Stat(event.Name); err == nil && info.IsDir() {
						if err := watcher.Add(event.Name); err != nil {
							log.Printf("[trust/filestore] warning: cannot watch new entities dir: %v", err)
						}
						log.Printf("[trust/filestore] now watching entities directory: %s", event.Name)
						// Reload to catch any PEM files written before the watch was set up
						// (race: meshctl entity register MkdirAll's the dir AND writes the file
						// in rapid succession; fsnotify may fire entities/ Create before we add
						// a watch on it, missing the subsequent .pem write).
						if err := fs.loadAll(); err != nil {
							log.Printf("[trust/filestore] reload error after entities dir creation: %v", err)
						}
					}
				}
				if !strings.HasSuffix(event.Name, ".pem") {
					continue
				}
				if event.Has(fsnotify.Create) || event.Has(fsnotify.Write) ||
					event.Has(fsnotify.Remove) || event.Has(fsnotify.Rename) {
					log.Printf("[trust/filestore] detected change: %s %s, reloading", event.Op, event.Name)
					if err := fs.loadAll(); err != nil {
						log.Printf("[trust/filestore] reload error: %v", err)
					}
				}
			case err, ok := <-watcher.Errors:
				if !ok {
					return
				}
				log.Printf("[trust/filestore] watcher error: %v", err)
			}
		}
	}()

	return nil
}
