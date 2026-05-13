package scaffold

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/spf13/cobra"
)

// defaultA2AAuthEnvVar is the env var name suggested for bearer-token auth
// when the producer's card advertises bearer in authentication.schemes.
const defaultA2AAuthEnvVar = "A2A_BEARER_TOKEN"

// ScaffoldSkill is the per-skill template view emitted to the renderer.
// One entry per card.skills[] (or one placeholder in --offline mode).
type ScaffoldSkill struct {
	ID           string
	Name         string
	Description  string
	Tags         []string
	Capability   string
	FunctionName string // snake_case (Python)
	ClassName    string // PascalCase (Java/TS class names)
	MethodName   string // camelCase, sanitized (Java method names)
}

// newScaffoldA2AConsumerCommand builds `meshctl scaffold a2a-consumer`.
//
// It fetches the producer's /.well-known/agent.json, expands the card's
// skills[] into one mesh capability per skill, and renders the matching
// language-specific template tree.
//
// With --offline a single placeholder skill is emitted so users can fill
// in producer URL / skill IDs / auth manually.
func newScaffoldA2AConsumerCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "a2a-consumer",
		Short: "Generate a mesh A2A consumer agent from an external producer's agent card",
		Long: `Generate a runnable A2A consumer agent that bridges an external A2A
producer's skills onto the mesh as ordinary capabilities.

The producer URL is fetched at scaffold time and every skill in the card's
skills[] becomes a mesh capability in the generated agent. If the card
declares bearer authentication, the generated code wires up an env-var
based bearer token placeholder (default A2A_BEARER_TOKEN).

Examples:
  # Fetch a producer's card and generate a Python consumer
  meshctl scaffold a2a-consumer --url http://localhost:9090/agents/date \
    --lang python --name date-bridge --port 9201

  # TypeScript consumer
  meshctl scaffold a2a-consumer --url https://weather.com/agents/forecast \
    --lang typescript --name weather-bridge

  # Java consumer
  meshctl scaffold a2a-consumer --url https://weather.com/agents/forecast \
    --lang java --name weather-bridge

  # Offline placeholder (no fetch) — user fills in URL / skill / auth
  meshctl scaffold a2a-consumer --offline --lang python --name placeholder`,
		RunE: runScaffoldA2AConsumer,
	}

	cmd.Flags().String("url", "",
		"Producer URL (base or with /.well-known/agent.json). Required unless --offline.")
	cmd.Flags().Bool("offline", false,
		"Generate a single-skill placeholder skeleton without fetching a card")
	cmd.Flags().StringP("lang", "l", "python", "Language: python, typescript, java")
	cmd.Flags().StringP("name", "n", "", "Agent name (required)")
	cmd.Flags().StringP("output", "o", ".", "Output directory")
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the generated agent")
	cmd.Flags().String("description", "", "Agent description (defaults to the card's description)")
	cmd.Flags().String("auth-env", defaultA2AAuthEnvVar,
		"Env var name for bearer token (used when the card advertises bearer auth)")
	cmd.Flags().String("package", "", "Java package name (default: com.example.<agent-name>)")
	cmd.Flags().Bool("dry-run", false, "Preview generated files without creating them")
	// --no-interactive is registered for v1.4.1 script compatibility.
	// TODO: wire to actual prompt-suppression once interactive prompts are added.
	cmd.Flags().Bool("no-interactive", false, "Disable interactive prompts (for scripting)")
	cmd.Flags().Bool("allow-private-network", false,
		"Allow card fetch (and any redirect) to resolve to a private/loopback/link-local IP. "+
			"Default off to block SSRF; enable for local-dev producers on localhost or RFC1918.")

	return cmd
}

// runScaffoldA2AConsumer drives the a2a-consumer subcommand end-to-end.
func runScaffoldA2AConsumer(cmd *cobra.Command, _ []string) error {
	urlFlag, _ := cmd.Flags().GetString("url")
	offline, _ := cmd.Flags().GetBool("offline")
	lang, _ := cmd.Flags().GetString("lang")
	name, _ := cmd.Flags().GetString("name")
	output, _ := cmd.Flags().GetString("output")
	port, _ := cmd.Flags().GetInt("port")
	description, _ := cmd.Flags().GetString("description")
	authEnv, _ := cmd.Flags().GetString("auth-env")
	javaPackage, _ := cmd.Flags().GetString("package")
	dryRun, _ := cmd.Flags().GetBool("dry-run")
	allowPrivate, _ := cmd.Flags().GetBool("allow-private-network")

	if name == "" {
		return fmt.Errorf("--name is required")
	}
	if !offline && urlFlag == "" {
		return fmt.Errorf("--url is required (or use --offline)")
	}
	if authEnv == "" {
		authEnv = defaultA2AAuthEnvVar
	}

	// Auto-increment port if --port wasn't explicitly set (issue #957 fix 2).
	port = AutoAssignScaffoldPort(cmd, port, output, name)

	language := NormalizeLanguage(lang)
	if !IsValidLanguage(language) {
		return fmt.Errorf("unsupported language: %s (supported: %v)", lang, supportedLanguages)
	}

	var (
		card    *AgentCard
		baseURL string
	)
	if offline {
		baseURL = "TODO-set-producer-url"
	} else {
		c, err := FetchAgentCard(urlFlag, FetchOptions{AllowPrivateNetwork: allowPrivate})
		if err != nil {
			return fmt.Errorf("failed to fetch A2A agent card: %w (use --offline to generate placeholder)", err)
		}
		card = c
		baseURL = ProducerBaseURL(urlFlag)
	}

	skills := buildScaffoldSkills(card)
	authBearer := card != nil && card.hasBearerAuth()
	cardName := ""
	cardDescription := ""
	if card != nil {
		cardName = card.Name
		cardDescription = card.Description
	}
	if description == "" {
		if cardDescription != "" {
			description = cardDescription
		} else if cardName != "" {
			description = "A2A consumer bridge for " + cardName
		}
	}

	ctx := &ScaffoldContext{
		Name:        name,
		Description: description,
		Language:    language,
		OutputDir:   output,
		Port:        port,
		AgentType:   "a2a-consumer",
		Template:    "a2a-consumer",
		JavaPackage: javaPackage,
		Cmd:         cmd,
		DryRun:      dryRun,
	}

	provider := NewStaticProvider()
	if err := validateA2AConsumerContext(ctx); err != nil {
		return err
	}

	data := TemplateDataFromContext(ctx)
	data["A2AURL"] = baseURL
	data["A2ACardName"] = cardName
	data["A2ACardDescription"] = cardDescription
	data["AuthBearer"] = authBearer
	data["AuthEnvVar"] = authEnv
	data["Offline"] = offline
	data["Skills"] = skills

	if err := executeA2AConsumerScaffold(provider, ctx, data); err != nil {
		return err
	}

	if !dryRun {
		printA2AConsumerFollowup(cmd, ctx, skills, baseURL, offline, authBearer, authEnv)
	}
	return nil
}

// validJavaPackagePattern restricts --package to standard Java package
// identifier syntax (lowercase letters/digits/underscores, dot-separated)
// so producer-supplied or user-supplied values cannot escape the output
// directory via path traversal segments like "../../etc".
var validJavaPackagePattern = regexp.MustCompile(`^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$`)

// validateA2AConsumerContext reuses the common name/language validation but
// skips the static provider's template enum check (a2a-consumer isn't in the
// classic template list).
func validateA2AConsumerContext(ctx *ScaffoldContext) error {
	if err := ctx.Validate(); err != nil {
		return err
	}
	if ctx.Language == "java" && ctx.JavaPackage == "" {
		sanitized := strings.ReplaceAll(strings.ReplaceAll(ctx.Name, "-", ""), "_", "")
		ctx.JavaPackage = "com.example." + strings.ToLower(sanitized)
	}
	if ctx.JavaPackage != "" && !validJavaPackagePattern.MatchString(ctx.JavaPackage) {
		return fmt.Errorf("--package must be a valid Java package identifier (lowercase letters, digits, underscores, dot-separated): got %q", ctx.JavaPackage)
	}
	return nil
}

// sanitizeIdentifier ensures the result is a safe identifier across
// Python/TypeScript/Java: starts with a letter or underscore, contains
// only [A-Za-z0-9_]. Used for function/method/class names derived from
// arbitrary producer-supplied skill IDs.
func sanitizeIdentifier(raw string) string {
	var b strings.Builder
	for _, r := range raw {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' {
			b.WriteRune(r)
		} else {
			b.WriteRune('_')
		}
	}
	cleaned := b.String()
	if cleaned == "" {
		return "skill"
	}
	// Identifiers cannot start with a digit — prefix with underscore.
	first := cleaned[0]
	if first >= '0' && first <= '9' {
		return "_" + cleaned
	}
	return cleaned
}

// buildScaffoldSkills converts card.skills[] into the per-skill template
// view. With a nil card (offline mode) it emits a single TODO placeholder
// so the generated file still compiles after the user fills in the gaps.
func buildScaffoldSkills(card *AgentCard) []ScaffoldSkill {
	if card == nil {
		return []ScaffoldSkill{{
			ID:           "TODO-skill-id",
			Name:         "TODO Skill",
			Description:  "TODO: describe this skill",
			Tags:         []string{},
			Capability:   "TODO-capability",
			FunctionName: "todo_skill",
			ClassName:    "TodoSkill",
			MethodName:   "todoSkill",
		}}
	}

	out := make([]ScaffoldSkill, 0, len(card.Skills))
	for _, s := range card.Skills {
		// Sanitize BEFORE the case-conversion helpers so digit-prefixed
		// or special-char-bearing skill IDs cannot produce uncompilable
		// identifiers in the generated source. Re-apply sanitization
		// AFTER PascalCase too — splitWords() drops empty leading
		// fragments, which strips a sanitizer-added underscore prefix
		// (e.g., "_123_x" -> PascalCase -> "123X").
		safeID := sanitizeIdentifier(s.ID)
		fname := toSnakeCase(safeID)
		if fname == "" {
			fname = "todo_skill"
		}
		cname := sanitizeIdentifier(toPascalCase(safeID))
		if cname == "" {
			cname = "TodoSkill"
		}
		mname := sanitizeIdentifier(toCamelCase(safeID))
		if mname == "" {
			mname = "todoSkill"
		}
		desc := s.Description
		if desc == "" {
			desc = s.Name
		}
		out = append(out, ScaffoldSkill{
			ID:           s.ID,
			Name:         s.Name,
			Description:  desc,
			Tags:         s.Tags,
			Capability:   s.ID,
			FunctionName: fname,
			ClassName:    cname,
			MethodName:   mname,
		})
	}
	return out
}

// executeA2AConsumerScaffold renders the a2a-consumer template tree using
// the static provider's renderer machinery, with the pre-computed
// per-skill template data.
func executeA2AConsumerScaffold(p *StaticProvider, ctx *ScaffoldContext, data map[string]interface{}) error {
	if ctx.DryRun {
		return p.executeA2AConsumerDryRun(ctx, data)
	}

	outputDir := filepath.Join(ctx.OutputDir, ctx.Name)
	entryFile := getAgentEntryFile(outputDir, ctx.Language)
	if FileExists(entryFile) {
		if ctx.Cmd != nil {
			ctx.Cmd.Printf("Agent '%s' already exists at %s\n", ctx.Name, outputDir)
		}
		return fmt.Errorf("agent already exists at %s", outputDir)
	}

	renderer := NewTemplateRenderer()
	if !embeddedTemplatesSet {
		return fmt.Errorf("scaffold templates not embedded; rebuild meshctl with embedded templates")
	}
	embeddedPath := fmt.Sprintf("templates/%s/a2a-consumer", ctx.Language)
	if err := renderer.RenderEmbeddedDirectory(embeddedTemplates, embeddedPath, outputDir, data); err != nil {
		return fmt.Errorf("failed to render a2a-consumer templates: %w", err)
	}

	if ctx.Cmd != nil {
		ctx.Cmd.Printf("\nCreated A2A consumer agent '%s' in %s/\n\n", ctx.Name, outputDir)
		ctx.Cmd.Printf("Generated files:\n")
		printGeneratedFiles(ctx.Cmd, outputDir, ctx.Name)
		ctx.Cmd.Println()
	}
	return nil
}

// executeA2AConsumerDryRun renders into a temp dir and prints each file to
// stdout, mirroring StaticProvider.executeDryRun for the a2a-consumer flow.
func (p *StaticProvider) executeA2AConsumerDryRun(ctx *ScaffoldContext, data map[string]interface{}) error {
	if !embeddedTemplatesSet {
		return fmt.Errorf("scaffold templates not embedded; rebuild meshctl with embedded templates")
	}

	tempDir, err := os.MkdirTemp("", "meshctl-dryrun-a2a-*")
	if err != nil {
		return fmt.Errorf("failed to create temp directory: %w", err)
	}
	defer os.RemoveAll(tempDir)

	renderer := NewTemplateRenderer()
	embeddedPath := fmt.Sprintf("templates/%s/a2a-consumer", ctx.Language)
	if err := renderer.RenderEmbeddedDirectory(embeddedTemplates, embeddedPath, tempDir, data); err != nil {
		return fmt.Errorf("failed to render a2a-consumer templates: %w", err)
	}

	if ctx.Cmd != nil {
		ctx.Cmd.Println("# Dry-run: Preview of generated files")
		ctx.Cmd.Printf("# Agent: %s\n", ctx.Name)
		ctx.Cmd.Printf("# Type: a2a-consumer\n")
		ctx.Cmd.Printf("# Language: %s\n", ctx.Language)
		ctx.Cmd.Println("#")
		ctx.Cmd.Println("# Files would be created in:", filepath.Join(ctx.OutputDir, ctx.Name))
		ctx.Cmd.Println()
	}

	return filepath.Walk(tempDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		relPath, err := filepath.Rel(tempDir, path)
		if err != nil {
			return err
		}
		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if ctx.Cmd != nil {
			ctx.Cmd.Printf("# ═══════════════════════════════════════════════════════════════\n")
			ctx.Cmd.Printf("# File: %s/%s\n", ctx.Name, relPath)
			ctx.Cmd.Printf("# ═══════════════════════════════════════════════════════════════\n")
			ctx.Cmd.Println(string(content))
			ctx.Cmd.Println()
		}
		return nil
	})
}

// printA2AConsumerFollowup prints next-steps after generation.
func printA2AConsumerFollowup(cmd *cobra.Command, ctx *ScaffoldContext, skills []ScaffoldSkill, baseURL string, offline, authBearer bool, authEnv string) {
	cmd.Printf("\n──────────────────────────────────────────────────────────────\n")
	if offline {
		cmd.Printf("A2A consumer skeleton (offline) created: ./%s/\n\n", ctx.Name)
		cmd.Printf("Fill in the TODO placeholders for producer URL and skill IDs\n")
		cmd.Printf("before running.\n\n")
	} else {
		cmd.Printf("A2A consumer agent created: ./%s/\n\n", ctx.Name)
		cmd.Printf("Bridges %d skill(s) from %s:\n", len(skills), baseURL)
		for _, s := range skills {
			cmd.Printf("  - %s -> capability %q\n", s.ID, s.Capability)
		}
		cmd.Println()
	}
	if authBearer {
		cmd.Printf("Auth: producer advertises bearer authentication.\n")
		cmd.Printf("Set the bearer token via the env var:\n")
		cmd.Printf("  export %s=<your-token>\n\n", authEnv)
	}
	switch ctx.Language {
	case "typescript":
		cmd.Printf("Run the consumer:\n  cd %s && npm install && npx tsx src/index.ts\n", ctx.Name)
	case "java":
		cmd.Printf("Run the consumer:\n  cd %s && mvn spring-boot:run\n", ctx.Name)
	default:
		cmd.Printf("Run the consumer:\n  cd %s && python main.py\n", ctx.Name)
	}
	cmd.Printf("──────────────────────────────────────────────────────────────\n")
}

// AttachA2AConsumerSubcommand registers `meshctl scaffold a2a-consumer`
// onto the scaffold root command. Called from cli.NewScaffoldCommand.
func AttachA2AConsumerSubcommand(parent *cobra.Command) {
	parent.AddCommand(newScaffoldA2AConsumerCommand())
}
