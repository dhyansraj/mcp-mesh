package cli

import (
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// NewEntityCommand creates the entity command group
func NewEntityCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "entity",
		Short: "Manage trusted entities for registration trust",
		Long: `Manage trusted entity CAs for the mcp-mesh registry.

Entities represent organizations or teams whose agents are allowed to register
with the mesh. Each entity is identified by a CA certificate — any agent
presenting a certificate signed by a trusted entity CA can join the mesh.

Examples:
  meshctl entity register "partner-corp" --ca-cert /path/to/ca.pem
  meshctl entity list
  meshctl entity revoke "partner-corp"`,
	}
	cmd.AddCommand(newEntityRegisterCommand())
	cmd.AddCommand(newEntityListCommand())
	cmd.AddCommand(newEntityRevokeCommand())
	return cmd
}

func newEntityRegisterCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "register <entity-name>",
		Short: "Register a trusted entity CA certificate",
		Long: `Register a CA certificate for a trusted entity.

Any agent presenting a certificate signed by this entity CA will be allowed
to register with the mesh.

Examples:
  meshctl entity register "partner-corp" --ca-cert /path/to/ca.pem
  meshctl entity register "internal-team" --ca-cert ./team-ca.pem --force`,
		Args: cobra.ExactArgs(1),
		RunE: runEntityRegister,
	}

	cmd.Flags().String("ca-cert", "", "Path to entity CA PEM file (required)")
	cmd.Flags().String("trust-dir", "", "Override trust directory (default: ~/.mcp_mesh/tls)")
	cmd.Flags().Bool("force", false, "Overwrite if entity already registered")
	_ = cmd.MarkFlagRequired("ca-cert")

	return cmd
}

func newEntityListCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List all trusted entity CAs",
		Long: `List all registered trusted entity CA certificates.

Displays entity name, certificate subject, expiry date, and source file.

Examples:
  meshctl entity list
  meshctl entity list --json`,
		RunE: runEntityList,
	}

	cmd.Flags().String("trust-dir", "", "Override trust directory (default: ~/.mcp_mesh/tls)")
	cmd.Flags().Bool("json", false, "Output as JSON")

	return cmd
}

func newEntityRevokeCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "revoke <entity-name>",
		Short: "Revoke a trusted entity CA",
		Long: `Revoke a trusted entity by removing its CA certificate from the trust store.

Agents from the revoked entity will be rejected on next registration attempt.
Use --force to skip the confirmation warning.

Examples:
  meshctl entity revoke "partner-corp" --force`,
		Args: cobra.ExactArgs(1),
		RunE: runEntityRevoke,
	}

	cmd.Flags().String("trust-dir", "", "Override trust directory (default: ~/.mcp_mesh/tls)")
	cmd.Flags().Bool("force", false, "Skip confirmation warning")

	return cmd
}

// entityNameRegex validates entity names: alphanumeric, hyphens, underscores only
var entityNameRegex = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_-]*$`)

func validateEntityName(name string) error {
	if len(name) == 0 {
		return fmt.Errorf("entity name cannot be empty")
	}
	if len(name) > 255 {
		return fmt.Errorf("entity name too long (max 255 characters)")
	}
	if !entityNameRegex.MatchString(name) {
		return fmt.Errorf("entity name must contain only alphanumeric characters, hyphens, and underscores (and start with alphanumeric)")
	}
	return nil
}

func getDefaultTrustDir() string {
	if envDir := os.Getenv("MCP_MESH_TRUST_DIR"); envDir != "" {
		return envDir
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".mcp_mesh", "tls")
}

func getEntitiesDir(trustDir string) string {
	return filepath.Join(trustDir, "entities")
}

func resolveTrustDir(cmd *cobra.Command) string {
	trustDir, _ := cmd.Flags().GetString("trust-dir")
	if trustDir == "" {
		trustDir = getDefaultTrustDir()
	}
	return trustDir
}

func parseCACertFile(path string) ([]*x509.Certificate, []byte, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to read CA cert file: %w", err)
	}

	var certs []*x509.Certificate
	rest := data
	foundCertBlock := false
	for {
		var block *pem.Block
		block, rest = pem.Decode(rest)
		if block == nil {
			break
		}
		if block.Type == "CERTIFICATE" {
			foundCertBlock = true
			cert, err := x509.ParseCertificate(block.Bytes)
			if err != nil {
				return nil, nil, fmt.Errorf("failed to parse X.509 certificate: %w", err)
			}
			certs = append(certs, cert)
		}
	}

	if !foundCertBlock {
		return nil, nil, fmt.Errorf("no CERTIFICATE PEM blocks found in %s", path)
	}

	return certs, data, nil
}

func formatSubject(cert *x509.Certificate) string {
	var parts []string
	if cert.Subject.CommonName != "" {
		parts = append(parts, "CN="+cert.Subject.CommonName)
	}
	for _, o := range cert.Subject.Organization {
		parts = append(parts, "O="+o)
	}
	if len(parts) == 0 {
		return cert.Subject.String()
	}
	return strings.Join(parts, ",")
}

func runEntityRegister(cmd *cobra.Command, args []string) error {
	entityName := args[0]
	caCertPath, _ := cmd.Flags().GetString("ca-cert")
	force, _ := cmd.Flags().GetBool("force")
	trustDir := resolveTrustDir(cmd)

	if err := validateEntityName(entityName); err != nil {
		return err
	}

	// Parse and validate the CA certificate
	certs, pemData, err := parseCACertFile(caCertPath)
	if err != nil {
		return err
	}

	// Validate the first certificate is a CA
	primaryCert := certs[0]
	if !primaryCert.IsCA {
		return fmt.Errorf("certificate is not a CA certificate (BasicConstraints CA flag not set)")
	}

	// Check expiry
	now := time.Now()
	if now.After(primaryCert.NotAfter) {
		return fmt.Errorf("CA certificate has expired (expired %s)", primaryCert.NotAfter.Format("2006-01-02"))
	}
	if now.Before(primaryCert.NotBefore) {
		return fmt.Errorf("CA certificate is not yet valid (valid from %s)", primaryCert.NotBefore.Format("2006-01-02"))
	}

	// Ensure entities directory exists
	entitiesDir := getEntitiesDir(trustDir)
	if err := os.MkdirAll(entitiesDir, 0755); err != nil {
		return fmt.Errorf("failed to create entities directory: %w", err)
	}

	// Check if entity already exists
	destPath := filepath.Join(entitiesDir, entityName+".pem")
	if _, err := os.Stat(destPath); err == nil && !force {
		return fmt.Errorf("entity '%s' already registered, use --force to overwrite", entityName)
	}

	// Write PEM file
	if err := os.WriteFile(destPath, pemData, 0644); err != nil {
		return fmt.Errorf("failed to write entity CA cert: %w", err)
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Entity '%s' registered\n", entityName)
	fmt.Fprintf(cmd.OutOrStdout(), "  Subject: %s\n", formatSubject(primaryCert))
	fmt.Fprintf(cmd.OutOrStdout(), "  Expires: %s\n", primaryCert.NotAfter.Format("2006-01-02"))
	fmt.Fprintf(cmd.OutOrStdout(), "  CA cert: %s\n", destPath)

	return nil
}

type entityInfo struct {
	Name    string `json:"name"`
	Subject string `json:"subject"`
	Expires string `json:"expires"`
	Source  string `json:"source"`
	IsRoot  bool   `json:"is_root,omitempty"`
}

func runEntityList(cmd *cobra.Command, args []string) error {
	trustDir := resolveTrustDir(cmd)
	jsonOutput, _ := cmd.Flags().GetBool("json")

	var entities []entityInfo

	// Check for root CA
	rootCAPath := filepath.Join(trustDir, "ca.pem")
	if _, err := os.Stat(rootCAPath); err == nil {
		if certs, _, err := parseCACertFile(rootCAPath); err == nil && len(certs) > 0 {
			entities = append(entities, entityInfo{
				Name:    "(root)",
				Subject: formatSubject(certs[0]),
				Expires: certs[0].NotAfter.Format("2006-01-02"),
				Source:  "ca.pem",
				IsRoot:  true,
			})
		}
	}

	// Read entity CAs
	entitiesDir := getEntitiesDir(trustDir)
	entries, err := os.ReadDir(entitiesDir)
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to read entities directory: %w", err)
	}

	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".pem") {
			continue
		}

		pemPath := filepath.Join(entitiesDir, entry.Name())
		certs, _, err := parseCACertFile(pemPath)
		if err != nil || len(certs) == 0 {
			continue
		}

		name := strings.TrimSuffix(entry.Name(), ".pem")
		entities = append(entities, entityInfo{
			Name:    name,
			Subject: formatSubject(certs[0]),
			Expires: certs[0].NotAfter.Format("2006-01-02"),
			Source:  filepath.Join("entities", entry.Name()),
		})
	}

	if len(entities) == 0 {
		fmt.Fprintln(cmd.OutOrStdout(), "No trusted entities registered. Use 'meshctl entity register' to add one.")
		return nil
	}

	if jsonOutput {
		enc := json.NewEncoder(cmd.OutOrStdout())
		enc.SetIndent("", "  ")
		return enc.Encode(entities)
	}

	// Table output
	fmt.Fprintf(cmd.OutOrStdout(), "%-20s %-40s %-12s %s\n", "ENTITY", "SUBJECT", "EXPIRES", "SOURCE")
	for _, e := range entities {
		fmt.Fprintf(cmd.OutOrStdout(), "%-20s %-40s %-12s %s\n", e.Name, e.Subject, e.Expires, e.Source)
	}

	return nil
}

func runEntityRevoke(cmd *cobra.Command, args []string) error {
	entityName := args[0]
	force, _ := cmd.Flags().GetBool("force")
	trustDir := resolveTrustDir(cmd)

	if err := validateEntityName(entityName); err != nil {
		return err
	}

	pemPath := filepath.Join(getEntitiesDir(trustDir), entityName+".pem")

	if _, err := os.Stat(pemPath); os.IsNotExist(err) {
		return fmt.Errorf("entity '%s' not found", entityName)
	}

	if !force {
		fmt.Fprintf(cmd.ErrOrStderr(), "Revoking entity '%s' will:\n", entityName)
		fmt.Fprintln(cmd.ErrOrStderr(), "  - Remove the entity CA from the trust store")
		fmt.Fprintln(cmd.ErrOrStderr(), "  - Cause agents from this entity to be rejected on next registration")
		fmt.Fprintln(cmd.ErrOrStderr(), "")
		return fmt.Errorf("use --force to confirm revocation")
	}

	if err := os.Remove(pemPath); err != nil {
		return fmt.Errorf("failed to remove entity CA: %w", err)
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Entity '%s' revoked\n", entityName)
	fmt.Fprintln(cmd.OutOrStdout(), "Note: Run 'meshctl entity rotate' to evict connected agents immediately")

	return nil
}
