package trust

import (
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"log"
	"reflect"
	"sync"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/fields"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/tools/clientcmd"
)

const (
	defaultLabelSelector = "mcp-mesh.io/trust=entity-ca"
	entityNameAnnotation = "mcp-mesh.io/entity-name"
)

// K8sSecrets is a TrustBackend that reads trusted entity CA certificates
// from Kubernetes Secrets matching a label selector.
type K8sSecrets struct {
	namespace     string
	labelSelector string
	mu            sync.RWMutex
	entities      []entityCA
	client        kubernetes.Interface
	done          chan struct{}
}

// NewK8sSecrets creates a K8sSecrets backend using the provided Kubernetes client.
// If labelSelector is empty, the default "mcp-mesh.io/trust=entity-ca" is used.
func NewK8sSecrets(client kubernetes.Interface, namespace, labelSelector string) (*K8sSecrets, error) {
	if labelSelector == "" {
		labelSelector = defaultLabelSelector
	}

	ks := &K8sSecrets{
		namespace:     namespace,
		labelSelector: labelSelector,
		client:        client,
		done:          make(chan struct{}),
	}

	if err := ks.loadAll(); err != nil {
		return nil, fmt.Errorf("initial load of k8s secrets: %w", err)
	}

	ks.startInformer()

	return ks, nil
}

// NewK8sSecretsFromConfig creates a K8sSecrets backend using in-cluster config
// or KUBECONFIG for client creation.
func NewK8sSecretsFromConfig(namespace, labelSelector string) (*K8sSecrets, error) {
	config, err := rest.InClusterConfig()
	if err != nil {
		// Fall back to KUBECONFIG.
		loadingRules := clientcmd.NewDefaultClientConfigLoadingRules()
		configOverrides := &clientcmd.ConfigOverrides{}
		config, err = clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loadingRules, configOverrides).ClientConfig()
		if err != nil {
			return nil, fmt.Errorf("building k8s client config: %w", err)
		}
	}

	client, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, fmt.Errorf("creating k8s client: %w", err)
	}

	return NewK8sSecrets(client, namespace, labelSelector)
}

// Name returns the backend name.
func (ks *K8sSecrets) Name() string {
	return "k8s-secrets"
}

// Verify checks whether the leaf certificate in certChain is trusted by any entity CA.
func (ks *K8sSecrets) Verify(certChain []*x509.Certificate) (*VerifyResult, error) {
	if len(certChain) == 0 {
		return nil, ErrNoCertPresented
	}

	leaf := certChain[0]

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

	ks.mu.RLock()
	defer ks.mu.RUnlock()

	for _, ent := range ks.entities {
		opts := x509.VerifyOptions{
			Roots:         ent.pool,
			Intermediates: intermediates,
			KeyUsages:     []x509.ExtKeyUsage{x509.ExtKeyUsageAny},
		}
		if _, err := leaf.Verify(opts); err == nil {
			return &VerifyResult{
				EntityID:    ent.id,
				CertSubject: leaf.Subject.String(),
				BackendName: ks.Name(),
			}, nil
		}
	}

	return nil, ErrUntrustedCert
}

// ListTrustedEntities returns metadata for all loaded CA certificates.
func (ks *K8sSecrets) ListTrustedEntities() ([]TrustedEntity, error) {
	ks.mu.RLock()
	defer ks.mu.RUnlock()

	var result []TrustedEntity
	for _, ent := range ks.entities {
		for _, cert := range ent.certs {
			fingerprint := sha256.Sum256(cert.Raw)
			result = append(result, TrustedEntity{
				ID:          ent.id,
				Subject:     cert.Subject.String(),
				NotBefore:   cert.NotBefore,
				NotAfter:    cert.NotAfter,
				Fingerprint: hex.EncodeToString(fingerprint[:]),
				Metadata: map[string]string{
					"source": "k8s-secrets",
				},
			})
		}
	}
	return result, nil
}

// Close stops the informer goroutine.
func (ks *K8sSecrets) Close() error {
	close(ks.done)
	return nil
}

// loadAll lists Secrets matching the label selector and parses CA certs from them.
func (ks *K8sSecrets) loadAll() error {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	secretList, err := ks.client.CoreV1().Secrets(ks.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: ks.labelSelector,
	})
	if err != nil {
		return fmt.Errorf("listing secrets in %s: %w", ks.namespace, err)
	}

	var entities []entityCA
	for i := range secretList.Items {
		secret := &secretList.Items[i]
		ent, err := parseSecretCA(secret)
		if err != nil {
			log.Printf("[trust/k8s-secrets] skipping secret %s/%s: %v", secret.Namespace, secret.Name, err)
			continue
		}
		entities = append(entities, *ent)
	}

	ks.mu.Lock()
	ks.entities = entities
	ks.mu.Unlock()

	log.Printf("[trust/k8s-secrets] loaded %d entity CA(s) from namespace %s", len(entities), ks.namespace)
	return nil
}

// parseSecretCA extracts CA certificates from a Kubernetes Secret.
func parseSecretCA(secret *corev1.Secret) (*entityCA, error) {
	caCrtData, ok := secret.Data["ca.crt"]
	if !ok {
		return nil, fmt.Errorf("missing ca.crt key")
	}

	var certs []*x509.Certificate
	rest := caCrtData
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
		return nil, fmt.Errorf("no certificates found in ca.crt")
	}

	// Determine entity ID from annotation, falling back to Secret name.
	id := secret.Name
	if ann, ok := secret.Annotations[entityNameAnnotation]; ok && ann != "" {
		id = ann
	}

	pool := x509.NewCertPool()
	for _, c := range certs {
		pool.AddCert(c)
	}

	return &entityCA{
		id:    id,
		pool:  pool,
		certs: certs,
	}, nil
}

// startInformer watches for Secret changes and reloads the trust store.
// If the informer cannot be started (e.g., fake client with nil RESTClient),
// it logs a warning and returns without watching.
func (ks *K8sSecrets) startInformer() {
	restClient := ks.client.CoreV1().RESTClient()
	// The fake clientset returns a non-nil interface wrapping a nil *rest.RESTClient.
	// Detect this to avoid panics in the informer goroutine.
	if restClient == nil || reflect.ValueOf(restClient).IsNil() {
		log.Printf("[trust/k8s-secrets] RESTClient is nil, skipping informer (watch disabled)")
		return
	}

	listWatcher := cache.NewFilteredListWatchFromClient(
		restClient,
		"secrets",
		ks.namespace,
		func(options *metav1.ListOptions) {
			options.LabelSelector = ks.labelSelector
			options.FieldSelector = fields.Everything().String()
		},
	)

	_, informer := cache.NewInformer(
		listWatcher,
		&corev1.Secret{},
		0,
		cache.ResourceEventHandlerFuncs{
			AddFunc: func(obj interface{}) {
				log.Printf("[trust/k8s-secrets] secret added, reloading")
				if err := ks.loadAll(); err != nil {
					log.Printf("[trust/k8s-secrets] reload error: %v", err)
				}
			},
			UpdateFunc: func(oldObj, newObj interface{}) {
				log.Printf("[trust/k8s-secrets] secret updated, reloading")
				if err := ks.loadAll(); err != nil {
					log.Printf("[trust/k8s-secrets] reload error: %v", err)
				}
			},
			DeleteFunc: func(obj interface{}) {
				log.Printf("[trust/k8s-secrets] secret deleted, reloading")
				if err := ks.loadAll(); err != nil {
					log.Printf("[trust/k8s-secrets] reload error: %v", err)
				}
			},
		},
	)

	go func() {
		informer.Run(ks.done)
	}()
}
