# MCP Mesh Release Notes

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.6...v0.9.7)

## v0.9.7 (2026-02-22)

### ✨ New Features

- **Language-agnostic Helm chart** (#580): `mcp-mesh-agent` chart now supports Python, TypeScript, and Java agents natively — added `agent.runtime` field and `isPython` helper for conditional Python env var injection; removed dead `agent.script` and `agent.python` fields; rewrote README with multi-language examples
- **Arbitrary namespace support** (#579): Helm charts deploy into any namespace — replaced hardcoded FQDN hostnames with short names, added `networkPolicy.allowedNamespace` with `| default .Release.Namespace` fallback, documented custom namespace, multi-tenant, and cross-namespace deployment patterns

### 🔧 Improvements

- **ENTRYPOINT/CMD alignment** (#586): TypeScript runtime ENTRYPOINT changed from `node` to `npx tsx`; all scaffold Dockerfiles now set CMD to just the script/jar path (ENTRYPOINT provides the runtime command)
- **NetworkPolicy** (#586): Registry ingress rule now filters by namespace only (not pod label), allowing both agents and APIs to reach the registry

### 🐛 Bug Fixes

- **Distributed tracing** (#585): Fixed `InheritableThreadLocal` trace context leak across Java thread pool reuse; added route handler span publishing to TypeScript `mesh.route()` and Java `@MeshRoute`; added `runtime` field to trace span metadata in all SDKs; fixed NPE in Java `TraceInfo.forPropagation()` when parent span is null
- **Scaffold registry URL** (#586): Fixed `mesh.registryUrl` in scaffold helm-values templates and deployment docs — the chart reads `registry.host`/`registry.port` but docs and templates were using a key the chart ignores, causing cross-namespace registry overrides to silently fail
- **TypeScript runtime tsx availability** (#586): Pinned `tsx@4` as global install in TypeScript runtime Dockerfile — previously relied on `npx` runtime download which fails in airgapped clusters
- **Registry NetworkPolicy port** (#586): Fixed default `ingressPorts` from 8080 to 8000 to match actual registry service port
- **Registry NetworkPolicy namespace label** (#586): Changed from `name:` to `kubernetes.io/metadata.name:` (auto-applied by K8s 1.21+)
- **Image tag consistency** (#586): Bumped all Go handler, scaffold template, and Dockerfile image tags from 0.8 to 0.9

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.5...v0.9.6)

## v0.9.6 (2026-02-19)

### ✨ New Features

- **Per-call custom headers** (#575): Inject headers like `x-audit-id` on individual tool invocations across all three SDKs — `tool(headers={"x-audit-id": "abc"})` (Python), `tool({}, { headers })` (TypeScript), `tool.call(args, headers)` (Java). Per-call headers merge with session-propagated headers (per-call wins)

### 🔧 Improvements

- **Header allowlist prefix matching** (#575): `MCP_MESH_PROPAGATE_HEADERS` now uses case-insensitive prefix matching — `x-audit` matches `x-audit-id`, `x-audit-source`, etc.

### 🐛 Bug Fixes

- **Registry dep_index alignment** (#574): Fixed dependency index positional alignment when dependencies can't be resolved — registry now preserves unresolved placeholder entries instead of empty arrays, ensuring Rust core assigns correct dep_index values
- **Pin fastmcp<3.0.0** (#574): Pinned across all Python source and examples to prevent breakage from FastMCP 3.0.0 breaking API changes
- **Watch mode detach logs** (#576): `meshctl start -w --detach` now writes agent stdout/stderr to per-agent log files (`~/.mcp-mesh/logs/<agent>.log`) instead of mixing everything into `meshctl.log`
- **Python header propagation** (#575): Fixed `decorators.py` middleware to use prefix matching for header allowlist (was exact-only, silently dropping prefixed headers)
- **Stale config warning removed** (#576): Removed noisy `cli_config.json` warning printed on every meshctl invocation since v0.9.5

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.4...v0.9.5)

## v0.9.5 (2026-02-17)

### ✨ New Features

- **Java SDK — `/health` endpoint** (#561): Added `GET` and `HEAD` `/health` endpoint to Java SDK for parity with Python and TypeScript runtimes

### 🔧 Improvements

- **Header propagation decoupled from distributed tracing** (#564): `MCP_MESH_PROPAGATE_HEADERS` now works across all SDKs (Python, Java, TypeScript) even when tracing is disabled — previously gated behind `MCP_MESH_DISTRIBUTED_TRACING_ENABLED`, silently dropping custom headers (auth tokens, tenant IDs)
- **Simplified tracing setup** (#554): Single `MCP_MESH_TRACING=true` env var enables end-to-end distributed tracing
- **Watch mode random port** (#552): Uses `MCP_MESH_HTTP_PORT=0` to eliminate "Address already in use" errors on restarts
- **Compile-before-restart in watch mode** (#556): Java runs `mvn compile` and Python runs `py_compile` before restarting, catching build errors early
- **Built-in retry for `meshctl trace`** (#555): Handles Tempo propagation delay automatically instead of requiring manual retries
- **Removed user-level config file** (#553): Eliminated `~/.mcp-mesh/config.yaml` to prevent cross-project conflicts

### 🐛 Bug Fixes

- **Java SDK** — `MeshEnvironmentPostProcessor` no longer overrides `server.port` for non-mesh Spring Boot apps (#558)
- **TypeScript SDK** — HTTP headers now propagate through `mesh.route()` Express middleware (#559)
- **meshctl** — `--env` flag uses `StringArray` instead of `StringSlice` so comma-separated values are not split (#564)
- **bump_version.py** — Added coverage for Docker image tags in `scaffold/compose.go` and Java pom.xml files in integration test artifacts (#560)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.3...v0.9.4)

## v0.9.4 (2026-02-10)

### 🐛 Bug Fixes

- **Java SDK — `List<Record>` @Param deserialization** (#548)
  - `@MeshTool` methods accepting `List<Record>` parameters (e.g., `List<TeamMember>`) received `List<LinkedHashMap>` at runtime due to Java type erasure — `MeshToolWrapper.ParamInfo` stored erased `Class<?>` instead of the full generic `Type` from `Method.getGenericParameterTypes()`; switched to `Type` and used Jackson `TypeFactory.constructType()` for proper parameterized type deserialization

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.2...v0.9.3)

## v0.9.3 (2026-02-10)

### 🐛 Bug Fixes

- **Java SDK — JavaTimeModule and isError guard in McpHttpClient** (#544)
  - `MeshMcpServerConfiguration` lacked `JavaTimeModule` — `@MeshTool` methods returning `java.time` types (`LocalDate`, `LocalTime`, `LocalDateTime`) threw `InvalidDefinitionException`; registered `JavaTimeModule` with `WRITE_DATES_AS_TIMESTAMPS=false` so java.time types serialize as ISO-8601 strings
  - `McpHttpClient.deserializeResult()` didn't check the MCP `isError` flag before attempting typed deserialization — upstream tool errors (returned as error text) caused `StreamReadException` instead of a proper `MeshToolCallException`; added `isError` check before `deserializeResult()` to convert upstream errors into `MeshToolCallException`

### 🔧 Improvements

- **meshctl man — cross-language links at top of pages**
  - Language variant links ("Also available: --typescript | --java") now appear near the top of man pages instead of at the bottom, making it easier to discover language-specific documentation

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.1...v0.9.2)

## v0.9.2 (2026-02-09)

### 🐛 Bug Fixes

- **meshctl start -w — Go fsnotify watch mode** (#533)
  - Replaced buggy bash-based watch mode with Go-native `AgentWatcher` using fsnotify, eliminating infinite restart cycles for Java agents and removing `watchfiles` pip dependency for Python
  - Event-driven file watching with debounce, process group termination, and automatic subdirectory watching — compiled into meshctl with zero runtime dependencies
  - TypeScript unchanged (`tsx --watch` works natively)

- **Java SDK — @MeshRoute generic type, consumer-only mode, and ObjectMapper centralization** (#532, #535, #536, #537)
  - `@MeshRoute` consumer-only mode: Spring Boot apps with `@MeshRoute` but no `@MeshAgent` now auto-start in consumer-only mode, registering as `agent_type=api`
  - `McpMeshTool<T>` generic type propagation: the full chain (BeanPostProcessor → DependencySpec → Interceptor → Proxy) now extracts and propagates the generic type, enabling typed deserialization instead of raw String
  - ObjectMapper centralization: replaced 8 bare `new ObjectMapper()` instances with `MeshObjectMappers.create()` factory; fixed silent deserialization fallback in `McpHttpClient`

### 🔧 Improvements

- **Version bump automation** — new `scripts/bump_version.py` handles 19 categories of version references across ~120 files with PEP 440 beta support and third-party dependency safety

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.0...v0.9.1)

## v0.9.1 (2026-02-08)

### 🐛 Bug Fixes

- **Release pipeline — PyPI indexing wait** (#526)
  - Docker builds could fail due to a race condition where `mcp-mesh-core` or `mcp-mesh` packages weren't indexed on PyPI yet when `pip install` ran
  - Added PyPI indexing wait steps to `publish-rust-core` and `publish-python` jobs, completing registry wait coverage for all 5 published packages (PyPI, npm, Maven Central)

- **meshctl scaffold — missing Java FreeMarker template** (#528)
  - `meshctl scaffold --lang java --agent-type llm-agent` generated code referencing a `.ftl` prompt template that was never created
  - Root cause: `.gitignore` blanket `prompts/` rule silently prevented the template from being tracked
  - Added gitignore exception and committed the missing template

- **Maven Central — incorrect external resource URLs**
  - Child module POMs inherited the parent `<url>` and Maven appended the `artifactId`, producing broken links on Maven Central
  - Added explicit `<url>` and `<scm>` to all child modules

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.8.1...v0.9.0)

## v0.9.0 (2026-02-07)

### ✨ New Features

- **Java SDK — Full Runtime Support** (#491)
  - New `mcp-mesh-spring-boot-starter` built on Spring Boot 4.0.2 + Spring AI 2.0.0-M2
  - Java agents participate as tool agents, LLM consumers, and LLM providers
  - Full cross-runtime interoperability (Java ↔ Python ↔ TypeScript)
  - Spring Boot auto-configuration for mesh registration, heartbeat, and discovery
  - MCP protocol support (tool listing, invocation, prompt handling)
  - Mesh delegation with `@MeshLlmProvider` and `@MeshRoute`
  - Distributed tracing support
  - 6 Maven modules: core, sdk, native, spring-boot-starter, spring-ai, bom

- **Java SDK — Auto-Port Detection** (#518)
  - Added `mesh_update_port` FFI binding to Rust core, enabling `MCP_MESH_HTTP_PORT=0` for Java agents
  - Java agents can now auto-detect their assigned port and report it to the registry

- **Java SDK — victools JSON Schema Generation** (#514)
  - Replaced manual schema building with victools `SchemaGenerator`
  - Structural parity with Python (Pydantic) and TypeScript (Zod) — produces `$defs`, `anyOf` for nullables, `required` arrays

- **meshctl scaffold — Java Support** (#497)
  - `meshctl scaffold --lang java` generates Spring Boot agent projects
  - 3 agent types: basic tool, LLM agent, LLM provider
  - Full template set: pom.xml, Application.java, application.yml, Dockerfile, helm-values

- **meshctl man — Java Documentation** (#495)
  - `meshctl man` now includes Java-specific guides: prerequisites, quickstart, deployment, capabilities

- **Java SDK on Maven Central** (#499)
  - Published under `io.mcp-mesh` namespace
  - Release pipeline: Rust FFI cross-compilation → fat JAR with native libs → GPG signing → Sonatype Central Portal
  - `mcpmesh/java-runtime` Docker image published to Docker Hub + GHCR

- **Custom Domain** — Documentation site moved from `dhyansraj.github.io/mcp-mesh` to [mcp-mesh.ai](https://mcp-mesh.ai/)

### 🔧 Improvements

- **LLM Provider Handler Refactoring** (all runtimes, #491)
  - Claude handler: TEXT + HINT only (removed unreliable STRICT mode)
  - OpenAI handler: STRICT mode with `response_format` for structured output
  - New base provider handler abstraction in Python and TypeScript

- **OTLP Tracing Flush Latency** (#514)
  - Buffer timeout reduced from 3s → 1s, flush ticker from 1s → 500ms
  - Residual spans now flush within ~1.5s instead of ~4-5s

- **Scaffold Cleanup** (#523)
  - Removed `--add-tool` feature (Python-only, complex, least-used)
  - Default port changed from 9000 to 8080
  - Enhanced basic tool templates with commented dependency injection and parameter examples

### 🐛 Bug Fixes

- **TypeScript SDK — Schema Injection** (#493): Fixed double-injection when provider delegates through mesh
- **meshctl start — Java Agent Name Detection** (#523): `isAgentFile()` now detects directory-based agents; `extractJavaAgentName()` parses `@MeshAgent` annotation instead of pom.xml artifactId
- **Java Native Library** (#511): `mcp-mesh-native` added as transitive dependency — users no longer need to manually manage native libs

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.8.0...v0.8.1)

## v0.8.1 (2026-01-29)

### 🔧 Improvements

- **TypeScript SDK - MESH*LLM*\* environment variables** (#484)
  - `MESH_LLM_PROVIDER`: Override LLM provider (direct mode only)
  - `MESH_LLM_MODEL`: Override model at runtime
  - `MESH_LLM_MAX_ITERATIONS`: Override max iterations
  - `MESH_LLM_FILTER_MODE`: Override tool filter mode

- **Python 3.13/3.14 support** (#485)
  - Updated pyproject.toml classifiers
  - Release workflow now builds wheels for Python 3.14

- Added scaffold test matrix (tc04-tc07) for llm-agent and llm-provider types
- New examples: context-self-dep-ts-direct, context-self-dep-ts-mesh
- Added 12 UC08 LLM prompt template tests

### 🐛 Bug Fixes

- **Scaffold TypeScript templates** (#482): Fixed templates to use `httpPort` instead of `port`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.21...v0.8.0)

## v0.8.0 (2026-01-27)

### ✨ New Features

- **Full TypeScript SDK** with `@mcpmesh/sdk` npm package (#391, #398, #400, #403, #406)
  - Express integration via `mesh.route()` for dependency injection (#396)
  - LLM agent support with `mesh.llm()` and provider plugin architecture (#398, #400)
  - Vercel AI SDK v6 compatibility (#412)
  - meshctl TypeScript support - start, watch, and manage TS agents (#406)

### 🔧 Improvements

- **Rust core runtime** for multi-language FFI support (#388, #394)
- **Agent name prefix matching** (#417) - `meshctl call calc` matches `calculator-agent`
- **AGE and LAST SEEN columns** (#452) - `meshctl list` now shows time since registration/heartbeat, following kubectl conventions
- **Rename McpMeshAgent to McpMeshTool** (#431) - Dependency injection type renamed for clarity
  - `McpMeshTool` is now the primary type for injected tool proxies
  - `McpMeshAgent` remains as deprecated alias for backward compatibility
  - Python: Shows runtime `DeprecationWarning` when `McpMeshAgent` is used
  - TypeScript: `@deprecated` JSDoc annotation for IDE warnings
- **Pre-flight checks before forking** (#444) - Validation errors now shown to user instead of hidden in log files when using `--detach`
- **Shutdown order fix** (#442) - Agents now stop first (in parallel), then registry. Added retry logic with exponential backoff for SQLite lock errors
- **Startup cleanup for stale agents** (#443) - Registry marks agents as unhealthy if no heartbeat within threshold (default 30s). Safe for multi-replica K8s deployments

### 🐛 Bug Fixes

- **Python SDK race condition** (#448) - Fixed `provider_proxy` being wiped by tools update. Now uses field-level updates to preserve data
- **TypeScript SDK template paths** (#449) - `file://` templates now resolve relative to package.json location, not `process.cwd()`
- **Scaffold template cleanup** (#446, #450) - Removed redundant transitive dependencies (`@ai-sdk/*`, `zod`) from TypeScript templates
- **addLlmProviderTool** now respects the `name` parameter (#407)
- **http_port=0 auto-assignment** (#430) - Fixed port auto-assignment in both Python and TypeScript SDKs
  - Python: Port detection now works correctly with uvicorn auto-assigned ports
  - TypeScript: Fixed port=0 being overridden to 8080

### 📚 Documentation

- README refresh with Python/TypeScript dual-language examples (#410)
- Feature comparison table and proxy/LLM documentation updates (#410)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.21...v0.8.0)

## v0.7.21 (2026-01-07)

### 🐛 Bug Fixes

- **Reduce API heartbeat pipeline logging verbosity** (#379): Downgrade routine logs from INFO/DEBUG to TRACE
  - API heartbeat pipeline now consistent with MCP pipeline logging
  - DEBUG mode shows only one summary line per heartbeat
  - INFO mode shows every 10th heartbeat, topology changes, and errors

- **Use parent directory name for main.py log files** (#382): Better log file naming for scaffolded agents
  - When filename is `main`, uses parent directory name for logs
  - `my-api/main.py` → `my-api.log` instead of `main.log`
  - Helps pure FastAPI apps with `@mesh.route` that don't have `@mesh.agent`

### 📚 Documentation

- **Add FAQ section** (#380, #381): New FAQ page in documentation
  - How to use `@mesh.tool` for background tasks (Redis consumers, cron jobs)
  - How to organize `@mesh.tool` functions across multiple files
  - Logging levels and heartbeat verbosity
  - Log file naming conventions

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.19...v0.7.20)

## v0.7.20 (2026-01-05)

### 🐛 Bug Fixes

- **Fix log/PID naming for scaffolded agents** (#376): Extract agent name from `@mesh.agent` decorator
  - Scaffolded agents (which use `main.py`) now correctly use decorator name for logs
  - Log files named by agent: `hello-world.log` instead of `main.log`
  - Uses Python AST for reliable parsing of all decorator syntax variations
  - Thread-safe caching with `sync.Map` for concurrent agent starts
  - Cross-platform support (Windows `.venv\Scripts\python.exe`)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.18...v0.7.19)

## v0.7.19 (2026-01-05)

### ✨ New Features

- **meshctl stop command** (#367): Stop detached agents and registry
  - `meshctl stop [name]` to stop specific agent or all processes
  - Per-agent PID files in `~/.mcp-mesh/pids/` (replaces single global PID)
  - Parallel agent shutdown with configurable timeout (default 10s)
  - Flags: `--registry`, `--agents`, `--keep-registry`, `--force`, `--timeout`, `--quiet`
  - Deprecates `--pid-file` flag (now managed automatically)

- **meshctl logs command** (#368): View agent logs in detached mode
  - Log files stored in `~/.mcp-mesh/logs/` with automatic rotation (5 files per agent)
  - Filtering: `-f` (follow), `-p` (previous), `--tail`, `--since`, `--until`
  - Standardized log format across Go/Python: `2026-01-05 14:24:38 INFO message`

- **meshctl stop --clean flag** (#372): Complete cleanup after stopping
  - Deletes registry database, log files, and PID files
  - Enables fresh start for development/testing

- **Observability documentation** (#370): New `meshctl man observability` page
  - CLI tracing with `meshctl call --trace` and `meshctl trace <id>`
  - Grafana/Tempo setup for Docker Compose and Kubernetes

### 🐛 Bug Fixes

- **Fix --env-file flag** (#369): Fixed completely non-functional `--env-file` flag in `meshctl start`
  - Env vars are now properly loaded and passed to agents

### 🔧 Improvements

- **Full LLM request/response logging** (#370): Enable debug logging at provider level
- **Remove default log truncation** (#370): `format_log_value()` no longer truncates by default
- **Better trace error messages** (#370): Helpful hints when trace not found

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.17...v0.7.18)

## v0.7.18 (2026-01-04)

### 🐛 Bug Fixes

- **Fix trace context propagation** (#326): Fixed flat trace hierarchy in distributed tracing
- **Fix registry URL in Helm values** (#357): Use correct `mcp-core-mcp-mesh-registry:8000` service name
- **Fix scaffold --compose --observability without agents** (#353): Generate infrastructure-only stack
- **Add missing watchfiles dependency** (#351): Added to pyproject.toml

### 📚 Documentation

- **Reorganize man pages** (#354): Improved `meshctl man llm`, `tags`, and `scaffold` documentation
- **Clarify meshctl call syntax** (#355): Use `[agent-ID:]tool_name` with realistic examples
- **Remove deprecated --healthy-only flag** (#352): Cleaned up stale documentation

### 🧹 Cleanup

- **Remove legacy examples/k8s directory** (#358): Replaced by Helm charts and scaffold
- **Consolidate logo files**: Moved to `docs/assets/images/`
- **Remove unused scripts**: Deleted `run-tests.sh`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.16...v0.7.17)

## v0.7.17 (2026-01-03)

### ✨ New Features

- **Add file watch mode for meshctl start** (#347): Auto-restart agents on file changes
  - Add `--watch/-w` flag for development workflows
  - Uses `watchfiles` library for reliable file monitoring
  - Each agent watches its own directory independently
  - Supports both `meshctl start` and direct Python execution

- **Add TRACE log level for SQL query logging** (#347): Separate SQL logging from DEBUG mode
  - `--debug` no longer shows Ent SQL queries
  - Use `MCP_MESH_LOG_LEVEL=TRACE` for SQL debugging

### 🐛 Bug Fixes

- **Fix scaffold llm-agent template issues** (#348):
  - Remove `response_format` parameter (causes LiteLLM TypeError)
  - Use `file://prompts/<name>.jinja2` for system_prompt (makes context_param work)
  - Dynamic file listing shows all generated files including prompts/ directory

- **Fix websockets deprecation warnings** (#347): Add `ws="websockets-sansio"` to uvicorn configs

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.15...v0.7.16)

## v0.7.16 (2026-01-03)

### ✨ New Features

- **Add pre-flight validation to meshctl start** (#338): Validates environment before running agents
  - Requires `.venv` in current directory (no fallback to system Python)
  - Validates Python version >= 3.11

- **Improve scaffold output** (#341): Better feedback after scaffolding
  - Display file tree of generated files
  - Show clear next steps for running the agent

### 🐛 Bug Fixes

- **Fix scaffold --observability missing Grafana provisioning** (#335): Added missing Grafana datasource/dashboard provisioning
- **Fix invalid agent.port in scaffold helm-values.yaml** (#339): Changed to `agent.http.port` with correct default
- **Fix Helm chart image tags to use minor version** (#340): Use `0.7` instead of `0.7.x` to track latest patch automatically

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.14...v0.7.15)

## v0.7.15 (2026-01-02)

### 🐛 Bug Fixes

- **Fix trace context propagation causing flat trace hierarchy** (#326): Fixed distributed tracing bug where all downstream calls incorrectly had the external span as parent
  - Use httpx `event_hooks` to inject trace headers at request time instead of transport construction
  - Ensures correct parent span is propagated to downstream agents
  - Added `examples/observability-test/` with 4-agent setup for trace hierarchy testing

- **Remove redundant mcp-mesh from scaffolded requirements.txt** (#325): Removed duplicate dependency from scaffold templates
  - `mcp-mesh` is already provided by runtime environment (Docker image or local install)
  - Prevents version conflicts and reduces confusion

### ⬆️ Dependencies

- **Update Grafana to 12.3.1 and Tempo to 2.9.0** (#329): Update observability stack versions
  - Grafana: 11.4.0 → 12.3.1
  - Tempo: 2.8.1 → 2.9.0
  - Updated in scaffold templates, Helm charts, k8s deployments, and docker-compose examples

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.13...v0.7.14)

## v0.7.14 (2026-01-02)

### 🐛 Bug Fixes

- **Fix scaffold --compose --observability tracing config** (#320): Fixed incomplete tracing configuration
  - Add missing registry tracing env vars (`TRACE_EXPORTER_TYPE`, `TELEMETRY_ENDPOINT`, `TELEMETRY_PROTOCOL`, `TEMPO_URL`)
  - Generate `tempo.yaml` config file when `--observability` is set
  - Update Tempo version from 2.3.1 to 2.8.1
  - Add `tempo-data` volume for trace persistence

- **Fix registry port default docs** (#322): Corrected `--registry-port` help text from 8080 to 8000

### ✨ New Features

- **Add observability to existing compose** (#320): Support running `--observability` on existing docker-compose files
  - Merge tracing env vars into existing registry and agent services
  - Preserve user-added environment variables when merging

### 📚 Documentation

- **Capability Selector Syntax** (#322): Add unified documentation for dependency selection
  - New "Capability Selector Syntax" section in `meshctl man capabilities`
  - Document AND/OR semantics for tag matching
  - Add cross-references from `di`, `llm`, `tags`, and `scaffold` man pages
  - Add `--filter` flag documentation to `meshctl man scaffold`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.12...v0.7.13)

## v0.7.13 (2026-01-01)

### ✨ New Features

- **LLM response metadata** (#314): Add `_mesh_meta` to LLM results with provider, model, token counts, and latency for cost tracking

  ```python
  result = await llm(question)
  print(result._mesh_meta.model)          # "openai/gpt-4o"
  print(result._mesh_meta.input_tokens)   # 100
  print(result._mesh_meta.output_tokens)  # 50
  print(result._mesh_meta.latency_ms)     # 125.5
  ```

- **Distributed tracing** (#313): Add `meshctl trace <id>` command and `--trace` flag for call tree visualization

  ```bash
  meshctl call smart_analyze '{"query": "test"}' --trace
  meshctl trace abc123  # View call tree
  ```

- **Model override in @mesh.llm** (#312): Allow consumers to specify model override with mesh delegation
  - Request specific model variant from provider (e.g., use haiku instead of default sonnet)
  - Vendor mismatch validation with automatic fallback

- **meshctl UX improvements** (#309):
  - `meshctl list` shows healthy agents by default, use `--all` for all
  - `meshctl status [agent-id]` shows details for specific agent
  - `meshctl list --tools=<name>` displays full input schema via registry proxy

- **Registry proxy** (#307): Add reverse proxy endpoint for external meshctl access
  - Call agents from outside Docker/K8s without exposing individual ports
  - Routes calls through registry by default (`--use-proxy=true`)

- **Decorator-level LLM params** (#305): Pass `max_tokens`, `temperature`, etc. from `@mesh.llm` decorator to provider
  ```python
  @mesh.llm(max_tokens=16000, temperature=0.7)
  def my_tool(llm=None):
      return llm(messages)  # params now respected
  ```

### 🐛 Bug Fixes

- **Normalize HTTP fallback response** (#304): Consistent response format between FastMCP and HTTP transport
- **Connection error hints** (#303): Helpful guidance when `meshctl call` fails from outside Docker/K8s
- **Code review improvements** (#301): Fix connection pooling, session cleanup, thread safety race condition
  - ~3000 lines of duplicate/dead code removed
  - Consolidated MCP proxies, health check logic, and heartbeat setup

### 🗑️ Removed

- **Remove auto-restart/watch-files** (#316): Remove unreliable `--auto-restart` and `--watch-files` flags
  - Features were unreliable due to subprocess/venv management issues
  - Users can reliably use Ctrl+C or kill signals to stop and manually restart agents

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.11...v0.7.12)

## v0.7.12 (2025-12-22)

### 🐛 Bug Fixes

- **scaffold --compose**: Preserve existing service configurations (#281)
  - Merges new agents without overwriting user modifications
  - Added `--force` flag to regenerate all configurations when needed
  - Infrastructure services never overwritten unless `--force` used

- **scaffold --compose**: Install requirements.txt dependencies at container startup (#283)
  - Third-party packages now work in dev mode (beautifulsoup4, pandas, etc.)
  - Packages cached in named volumes for fast subsequent starts

- **Logging cleanup**: Allowlist approach + remove noisy logs (#284)
  - Python: Root logger stays INFO, only mcp-mesh loggers get DEBUG
  - Go: Removed excessive troubleshooting logs from registry

### 📚 Documentation

- Update Helm chart version references to 0.7.11 (#287)
- Add ENTRYPOINT comments to Dockerfile templates for AI assistants
- Clarify FastAPI integration is for existing apps
- Update meshctl --help to emphasize framework over ops tool
- Add port strategy section for local vs Kubernetes
- Improve meshctl call docs for Docker Compose and Kubernetes

### ✨ Branding

- Add cyan logo to README with dark mode support (#285)
- Add YouTube channel link to README and mkdocs (#286)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.10...v0.7.11)

## v0.7.11 (2025-12-16)

### 🐛 Bug Fixes

- **SSE read timeout**: Fixed MCP SDK 1.24.0+ compatibility issue (#268)
  - MCP SDK deprecated `sse_read_timeout` parameter on `StreamableHttpTransport`
  - Now uses `httpx_client_factory` to configure httpx client with custom timeouts
  - Fixes connection timeout errors when agents take longer than default timeout

### 📚 Documentation

- **meshctl man prerequisites**: Clarified that meshctl auto-detects `.venv` (#270)
  - meshctl is a Go binary that auto-detects `.venv` in the current directory
  - Users only need to activate venv for `pip` commands
  - meshctl uses `.venv/bin/python` automatically when running agents

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.9...v0.7.10)

## v0.7.10 (2025-12-16)

### 🐛 Bug Fixes

- **LLM tool resolutions**: Fixed tags-only filters not being stored in registry database (#257)
  - Previously, `filter=[{"tags": ["tools"]}]` was skipped during storage
  - Now all resolved tools are properly stored for tags-only filters

### ✨ Enhancements

- **meshctl status --insecure**: Added `--insecure` flag for self-signed TLS certificates (#259)
  - Consistent with `meshctl list` and `meshctl call` commands
- **Cleaner DEBUG logs**: Suppressed noisy docket task queue logs (#261)
  - Removed spam like "Scheduling due tasks", "Getting redeliveries" in tight loops
  - MCP Mesh DEBUG logs remain visible
- **Anthropic health check**: Use GET /v1/models instead of HEAD /v1/messages (#263)
  - Returns proper 200 status (not hacky 405 workaround)
  - Free endpoint, no tokens consumed
  - Validates API key and confirms API reachability

### 📚 Documentation

- **@mesh.llm response_format**: Clarified that format is determined by return type annotation (#264)
  - `-> str` for text output, `-> PydanticModel` for structured JSON
  - Removed misleading `response_format` parameter from examples
- **Virtual environment**: Clarified venv should be at project root, shared by all agents (#264)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.8...v0.7.9)

## v0.7.9 (2025-12-15)

### 🐛 Bug Fixes

- **meshctl start**: Fixed Ctrl+C to properly stop registry in file watching mode (#251)
  - Previously, pressing Ctrl+C only stopped the agent but left the registry running
  - Now both agent and registry stop cleanly with a single Ctrl+C

### 📚 Documentation

- **meshctl man prerequisites**: New man topic covering system requirements (#249)
  - Local development setup with Python 3.11+ and virtual environments
  - Docker deployment prerequisites
  - Kubernetes deployment with Helm charts
  - Windows WSL2/Git Bash requirement note
- **Python 3.11+**: Updated minimum Python version from 3.9 to 3.11+ across all documentation (#249)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.7...v0.7.8)

## v0.7.8 (2025-12-15)

### 🐛 Bug Fixes

- **meshctl start**: Fixed `mcp-mesh-registry` not found when installed via npm (#245)
  - Registry binary lookup now properly searches the system PATH using `exec.LookPath()`
  - Previously only checked local directories with `os.Stat()`, which doesn't search PATH

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.6...v0.7.7)

## v0.7.7 (2025-12-15)

### 🐛 Bug Fixes

- **@mesh.llm with text mode**: Fixed `AttributeError: type object 'str' has no attribute 'model_json_schema'` when using `response_format="text"` (#239)

### ✨ Features

- **meshctl list --id**: New LLM resolution display sections (#241)
  - LLM Tool Filters - Shows filter configuration from `@mesh.llm` decorator
  - LLM Tool Resolutions - Shows resolved tools with endpoints
  - LLM Providers - Shows provider requirements with preference tags
  - LLM Provider Resolutions - Shows which provider agent was selected
- **Example LLM providers**: Added `claude-provider` and `openai-provider` example agents (#241)
- **Example agent**: Added `llm_with_deps_agent.py` demonstrating both LLM and static dependencies (#241)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.5...v0.7.6)

## v0.7.6 (2025-12-14)

### 🐛 Bug Fixes

- **@mesh.llm_provider**: Preserves original function name to avoid conflicts when multiple providers are used (#227)
- **meshctl scaffold --compose**: Generates correct command without redundant python prefix (#222)
- **Dockerfile templates**: Fixed non-root user permissions in scaffolded Dockerfiles (#226)
- **Registry version**: Fixed double 'v' in version output and updated description (#235)
- **Helm docs**: Removed redundant python from command examples (#225)

### ✨ Features

- **Configurable core release name**: Added `global.coreReleaseName` for flexible Helm service hostnames (#224)

### 📚 Documentation

- **meshctl man scaffold**: New topic for agent scaffolding command (#223)
- **meshctl man cli**: New topic covering call, list, status commands (#234)
- **Deployment docs**: Added Apple Silicon buildx hint and use `--create-namespace` (#236)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.4...v0.7.5)

## v0.7.5 (2025-12-12)

### 📚 Documentation

- **Installation simplification**: npm is now the primary installation method across all docs
- **Component-based organization**: Installation docs reorganized by component (meshctl, Registry, Python Runtime, Docker, Helm)
- **New tagline**: "Production-grade distributed mesh for intelligent agents"
- **Philosophy update**: Added "Why MCP Mesh?" section explaining agent autonomy philosophy
- **Core principles**: Added "LLMs are first-class capabilities" to documentation

### 🧹 Cleanup

- Removed accidentally committed `prompts/` folder
- Updated troubleshooting sections for npm-based installation

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.3...v0.7.4)

## v0.7.4 (2025-12-12)

### 🐛 Bug Fixes

- **npm packages**: Fixed `mcp-mesh-registry` missing from macOS npm packages
  - Now downloads pre-built binaries from GitHub releases instead of cross-compiling
  - All platforms (Linux x64/arm64, macOS x64/arm64) include both `meshctl` and `mcp-mesh-registry`

### 📦 Infrastructure

- Simplified npm build process by reusing release assets
- Removed CGO cross-compilation dependency from npm publish workflow

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.2...v0.7.3)

## v0.7.3 (2025-12-11)

### 📦 npm Package Enhancement

- **mcp-mesh-registry in npm**: Both `meshctl` and `mcp-mesh-registry` binaries are now bundled in the `@mcpmesh/cli` npm package
  - `npm install -g @mcpmesh/cli` installs both tools
  - `meshctl` - CLI for managing MCP Mesh agents and tools
  - `mcp-mesh-registry` - Registry service for service discovery
  - Supported platforms: Linux (x64, arm64), macOS (x64, arm64)

### 📦 Infrastructure

- Added CGO cross-compilation support for registry binary in npm build
- Simplified platform support to Linux and macOS (Windows users should use WSL2 or Docker)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.1...v0.7.2)

## v0.7.2 (2025-12-11)

### 🎯 CLI Tool Invocation & Discovery

- **meshctl call**: New command to invoke MCP tools directly from the CLI
  - `meshctl call <tool_name> '{"arg": "value"}'` - invoke any tool
  - Automatic agent discovery - finds which agent provides the tool
  - Support for `agent:tool` syntax to target specific agents
  - Pretty-printed JSON output

- **meshctl list --tools**: Enhanced tool discovery across all agents
  - `meshctl list --tools` - list all tools from all connected agents
  - `meshctl list --tools=<tool>` - show tool details with input schema
  - Great for LLM discoverability

### 📦 npm Package Distribution

- **@mcpmesh/cli**: Install meshctl via npm for easy LLM integration
  - `npm install -g @mcpmesh/cli`
  - Platform-specific binary packages (linux, darwin, win32 × x64, arm64)
  - Automatic platform detection and binary setup
  - Enables LLMs like Claude to install and use meshctl directly

### 📚 Documentation

- Updated all documentation examples to use `meshctl call` instead of curl
- Improved getting started guides with CLI-first approach

### 📦 Infrastructure

- GitHub Actions workflow for automated npm publishing on release
- Makefile targets: `npm-build`, `npm-publish`, `npm-clean`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.0...v0.7.1)

## v0.7.1 (2025-12-10)

### 📚 Documentation

- Simplified observability documentation with troubleshooting pipeline focus
- Updated Helm documentation to correctly explain mcp-mesh-core umbrella chart
- Streamlined Kubernetes deployment docs to focus on Helm
- Removed broken mike versioning configuration

### 🐛 Bug Fixes

- Fixed documentation version display in header

### 📦 Infrastructure

- Updated all Helm charts to version `0.7.1`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.4...v0.7.0)

## v0.7.0 (2025-12-04)

### 🎯 Agent Scaffolding & Developer Experience

- **Agent Scaffolding**: New `meshctl scaffold` command for generating agent boilerplate code from templates
  - Multiple template types: basic, tool, llm, advanced
  - Interactive prompts or CLI flags for configuration
  - Generates ready-to-run agent code with proper structure

- **Embedded Documentation**: New `meshctl man` command for viewing documentation without leaving the terminal
  - Browse documentation by topic
  - Search functionality for finding specific content
  - Offline-friendly - no network required

### 📊 Features

- **Runtime Context Injection for MeshLlmAgent**: LLM agents can now receive runtime context for dynamic behavior (#186)
  - Pass context at invocation time for agent customization
  - Supports dynamic prompt construction based on runtime state

- **FastAPI Route Dependency Injection**: Fixed `@mesh.route` decorator to properly inject dependencies in FastAPI routes (#188)
  - Uses `METHOD:path` format as unique route identifier (e.g., "GET:/api/v1/time")
  - Works with both direct `@mesh.route` and `APIRouter` patterns
  - Proper function signature preservation

### 🐛 Bug Fixes

- Fixed dependency injection for FastAPI routes when using `@mesh.route` decorator
- Fixed route wrapper registration to use full `METHOD:path` identifier

### 📦 Infrastructure

- Updated all Docker images to use `0.7` tag
- Updated all Helm charts to version `0.7.0`
- Updated Kubernetes manifests and CRDs with new image tags
- Updated Homebrew formula and Scoop manifest

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.3...v0.6.4)

## v0.6.4 (2025-11-30)

### 🐛 Bug Fixes

- **Missing PyPI Dependencies**: Added missing `litellm`, `jinja2`, and `cachetools` dependencies to PyPI package configuration
  - Fixes `jinja2 is required for template rendering` error
  - Fixes `litellm is required for MeshLlmAgent` error
  - Root cause: `packaging/pypi/pyproject.toml` was out of sync with `src/runtime/python/pyproject.toml`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.2...v0.6.3)

## v0.6.3 (2025-11-30)

### 🎯 LLM Provider Handler Enhancements

- **Enhanced Model Name Handling**: Improved model name extraction and validation for direct LiteLLM provider calls
- **Response Format Injection**: Better response format configuration for Claude and OpenAI handlers
- **Provider Handler Support**: Enhanced provider handler selection and configuration
- **LLM Config Improvements**: Refactored LLM configuration handling for cleaner provider integration

### 📊 Features

- Enhanced `ClaudeHandler` and `OpenAIHandler` for more robust response processing
- Improved `MeshLLMAgentInjector` for better dependency injection
- Cleaner `ResponseParser` implementation for LLM responses

### 🐛 Bug Fixes

- Fixed response format injection for various LLM provider configurations
- Improved error handling in provider handlers

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.1...v0.6.2)

## v0.6.2 (2025-11-25)

### 🎯 LLM Provider Handler Fix

- **Vendor Extraction from Model Name**: Extract vendor from LiteLLM model strings (e.g., `anthropic/claude-sonnet-4-5` → `anthropic`) for proper provider handler selection in direct LiteLLM calls
- **Self-Dependency with @mesh.llm**: Fixed self-dependency injection to use wrapper function instead of original, ensuring LLM agent is properly injected

### 📊 Features

- Automatic vendor detection from model name for correct response format injection
- ClaudeHandler now properly used for `anthropic/*` models even with direct `provider="claude"` calls
- Added self-dependency test for `@mesh.llm` decorated functions

### 🐛 Bug Fixes

- Fixed curl syntax in documentation to include proper MCP headers (`Accept: application/json, text/event-stream`)
- Fixed self-dependency injection to use wrapper instead of original function (#169)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.0...v0.6.1)

## v0.6.1 (2025-11-24)

### 🎯 Health Check Support

- **Custom Health Check Decorator**: New `@mesh.health_check()` decorator for defining agent health logic
- **Kubernetes-Compatible Endpoints**: Added `/health`, `/ready`, `/live`, `/startup`, and `/metrics` endpoints
- **TTL-Based Caching**: Per-key TTL support (default 15s) for health check results to reduce overhead
- **Flexible Return Types**: Support for bool, dict, and HealthStatus return types from health check functions

### 📊 Features

- K8s-compatible health endpoints with automatic health status aggregation
- Automatic DEGRADED status on health check exceptions for resilience
- DecoratorRegistry integration for efficient health status storage
- Comprehensive test coverage with 239 new test lines

### 🐛 Bug Fixes

- Fixed TTL cache expiration behavior by implementing manual per-key expiry tracking
- Updated test assertions for DEBUG level logging (was INFO)
- Removed IDE-specific files from version control (.emigo_repomap, .windsurf, .windsurfrules)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.7...v0.6.0)

## v0.6.0 (2025-11-20)

### 🎯 Dependency Resolution Tracking

- **Persistent Dependency Tracking**: Track and persist both resolved and unresolved dependencies in database
- **Enhanced Visibility**: Display dependency status in `meshctl list agents` with clear visual indicators
- **Topology Awareness**: Automatically update dependency status when provider agents go offline
- **Comprehensive Testing**: Full test coverage for dependency persistence and topology changes

### 📊 Features

- New `dependency_resolutions` table storing consumer/provider relationships
- Visual dependency table in meshctl showing: DEPENDENCY | MCP TOOL | ENDPOINT
- Color-coded status indicators (red for unresolved, green for resolved)
- Registry connection flags for meshctl (--registry-host, --registry-port, --registry-url)
- Support for both `[]interface{}` and `[]map[string]interface{}` dependency types

### 🐛 Bug Fixes

- Fixed health check port configuration in Docker Compose
- Updated health checks to use Python urllib instead of wget
- Corrected registry Dockerfile path references

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.6...v0.5.7)

## v0.5.7 (2025-11-06)

### 🎯 Dependency Injection Enhancements

- **Array-based Dependency Injection**: Support for multiple dependencies with the same capability name but different tags/versions
- **Improved Type Support**: Updated warning messages to reflect support for both `McpAgent` and `McpMeshAgent` types

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.5...v0.5.6)

## v0.5.6 (2025-09-21)

### 🔧 Graceful Shutdown and Registry Cleanup

- Implemented clean shutdown architecture with FastAPI lifespan integration
- Added proper DELETE /agents/{agent_id} registry cleanup when agents terminate
- Fixed race conditions between heartbeat and shutdown threads
- Enhanced agent lifecycle management with graceful signal handling
- Improved DNS atexit threading reliability for Kubernetes environments

### 🚀 System Improvements

- Updated environment variable configuration: MCP_MESH_REGISTRY_URL for Docker/K8s compatibility
- Fixed CI test hanging issues with MCP_MESH_AUTO_RUN=false configuration
- Enhanced error handling and logging for production debugging
- Streamlined agent startup and shutdown processes

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.3...v0.5.5)

## v0.5.3 (2025-08-16)

### GitHub Pipeline Fixes

- Fixed Docker registry binary path resolution
- Fixed release artifact checksum generation
- Improved release workflow reliability

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.2...v0.5.3)

## v0.5.2 (2025-08-16)

### 🍎 macOS Support & Platform Improvements

**Native macOS Binary Distribution**

- Added native macOS builds for both Intel (`darwin/amd64`) and Apple Silicon (`darwin/arm64`) architectures
- Implemented automated Homebrew tap distribution via `dhyansraj/homebrew-mcp-mesh`
- Fixed binary naming consistency: standardized on `mcp-mesh-registry` across all platforms
- Enhanced GitHub Actions pipeline with cross-platform build support and automated package manager updates

**Enhanced Installation Experience**

- **Homebrew Support**: `brew tap dhyansraj/mcp-mesh && brew install mcp-mesh`
- **PATH Resolution**: Improved binary discovery for both development and system installations using `exec.LookPath()`
- **Cross-Platform Install Script**: Updated `install.sh` to handle macOS/Linux differences seamlessly

**Distributed Tracing Reliability**

- Fixed silent tracing failures that were preventing proper observability data collection
- Enhanced FastAPI middleware integration for more robust trace capture
- Improved context handling and metadata publishing to Redis streams
- Updated Grafana dashboards with better trace visualization

### 🏷️ Migration Guide

**Upgrading from v0.5.1:**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5.2,<0.6"`
- **macOS Users**: Install via Homebrew: `brew tap dhyansraj/mcp-mesh && brew install mcp-mesh`
- **Docker Images**: Use `mcpmesh/registry:0.5.2` and `mcpmesh/python-runtime:0.5.2`
- **Helm Charts**: All charts now use v0.5.2 for consistent dependency management

**Breaking Changes:**

- None - this release maintains full backward compatibility with v0.5.1
- Binary names are now consistent (`mcp-mesh-registry`) but old references will continue to work

### 📦 Distribution Improvements

- **GitHub Actions**: Native macOS builds with proper Gatekeeper signing preparation
- **Homebrew Automation**: Automatic formula updates with cross-platform checksum verification
- **Enhanced CI/CD**: Improved reliability with disabled Go cache and proper dependency management

---

## v0.5.1 (2025-08-14)

### 🔧 Major Enhancement Release - Unified Telemetry Architecture

**FastMCP Client Integration**

- Replaced custom MCP client with official FastMCP client library for better protocol compliance
- Enhanced error handling and timeout management with official client optimizations

**Unified Telemetry Architecture**

- Moved telemetry from HTTP middleware to dependency injection wrapper for complete coverage
- Added distributed tracing support for FastAPI routes with `@mesh.route()` decorators
- Unified agent ID generation across MCP agents and API services
- Redis stream storage for all telemetry data in `mesh:trace`

**Agent Context Enhancement**

- 3-step agent ID resolution: cached → @mesh.agent config → synthetic defaults
- Environment variable priority: `MCP_MESH_API_NAME` → `MCP_MESH_AGENT_NAME` → `api-{uuid8}`
- Comprehensive metadata collection with performance metrics

### 🏷️ Migration Guide

**Upgrading from v0.5.0:**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5.1,<0.6"`
- **Docker Images**: Use `mcpmesh/registry:0.5.1` and `mcpmesh/python-runtime:0.5.1`
- **Helm Charts**: All charts now use v0.5.1 for consistent dependency management

**Breaking Changes:**

- None - this release maintains full backward compatibility with v0.5.0

---

## v0.5.0 (2025-08-13)

### 🚀 Major Release - FastAPI Dependency Injection Integration

**FastAPI Native Support**

- Complete FastAPI dependency injection system integration with MCP Mesh decorators
- Seamless interoperability between FastAPI's `Depends()` and mesh dependency resolution
- Type-safe dependency injection with automatic provider discovery and lifecycle management
- Introduced new `@mesh.route` decorator exclusively for FastAPI apps to inject MCP Mesh agents

**Advanced Dependency Resolution**

- Added +/- operator support in tags: + means preferred, - means exclude

### 🐛 Bug Fixes & Stability

- Enhanced support for large payload and response handling

### 🏷️ Migration Guide

**Upgrading from v0.4.x**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5,<0.6"`
- **Docker Images**: Use `mcpmesh/registry:0.5` and `mcpmesh/python-runtime:0.5`
- **Helm Charts**: All charts now use v0.5.0 for consistent dependency management
- **Configuration**: Update any hardcoded version references in deployment manifests

**Breaking Changes**

- None - this release maintains full backward compatibility with v0.4.x
- Enhanced FastAPI integration is additive and does not affect existing code
- All existing decorators and patterns continue to work unchanged

---

## v0.4.2 (2025-08-11)

### 🔧 Critical Bug Fixes

**SSE Parsing Reliability**

- Fixed sporadic JSON parsing errors during large file processing (>15KB files)
- Consolidated duplicate SSE parsing logic across 3 proxy classes for improved maintainability
- Enhanced error handling with context-aware debugging for better troubleshooting
- Added shared `SSEParser` utility class with proper JSON accumulation logic

**FastMCP Discovery Stability**

- Fixed `RuntimeError: dictionary changed size during iteration` crashes during agent startup
- Applied thread-safe dictionary iteration patterns to prevent concurrent modification errors
- Improved startup reliability for complex multi-agent environments

**Code Consolidation**

- Eliminated duplicate SSE parsing code across `MCPClientProxy`, `AsyncMCPClient`, and `FullMCPProxy`
- Added `SSEStreamProcessor` for consistent streaming support
- Enhanced debugging capabilities with contextual logging

### 📁 New Files Added

- `src/runtime/python/_mcp_mesh/shared/sse_parser.py` - Consolidated SSE parsing utilities

### 🧪 Enhanced Examples

- Updated LLM chat agent with real Claude API integration and tool calling support
- New comprehensive chat client agent demonstrating advanced dependency injection patterns
- Improved large file processing examples with 100% reliability testing

### 📈 Validation Results

- ✅ **Large file processing**: 100% reliability with 23KB+ files generating 6K+ token responses
- ✅ **Agent startup**: Eliminated intermittent crashes during FastMCP server discovery
- ✅ **Code quality**: Consolidated duplicate logic improving maintainability and reducing technical debt
- ✅ **Testing**: Verified with real-world scenarios including rapid startup/shutdown cycles

---

## v0.4.1 (2025-08-10)

### 🏷️ Enhanced Tag Matching

**Smart Service Discovery**

- Enhanced tag matching with `+` (preferred) and `-` (excluded) operators
- Priority scoring system for intelligent provider selection
- Industry-standard syntax similar to Kubernetes label selectors

**Migration & Compatibility**

- Complete backward compatibility with existing exact tag matching
- Comprehensive migration guide and documentation updates
- Test-driven development with extensive unit test coverage

### 📚 Documentation

- Updated mesh decorators documentation with enhanced tag examples
- Migration guide for upgrading from exact matching to enhanced matching
- Smart LLM provider selection patterns with cost control examples

---

## v0.4.0 (2025-07-31)

### 🔍 Observability & Monitoring

**Complete Observability Stack**

- Full Grafana + Tempo integration for Kubernetes and Helm deployments
- Pre-configured dashboards with MCP Mesh branding and metrics
- Production-ready monitoring with persistent storage support

**Real-Time Trace Streaming**

- Live trace streaming API (`/traces/{trace_id}/stream`) with Server-Sent Events
- Watch multi-agent workflows execute in real-time through web dashboards
- Redis consumer groups for scalable trace data processing

**Distributed Tracing System**

- Redis streams integration for trace data storage (`mesh:trace` stream)
- OTLP export with direct protobuf generation for Tempo/Jaeger compatibility
- Cross-agent context propagation maintaining parent-child span relationships
- Complete observability directory structure with organized assets

### 🏗️ Architecture & Deployment

**Enhanced Kubernetes Support**

- New observability components in `k8s/base/observability/` and `examples/k8s/base/observability/`
- Distributed tracing environment variables for all agent deployments
- Complete Helm chart ecosystem with dedicated observability charts

**Multi-Agent Dependency Injection**

- Complex data processor example with modular tools and utilities
- Advanced agent architecture with parsing, transformation, analysis capabilities
- Comprehensive Docker containerization and development workflows

### ⚙️ Infrastructure Improvements

**Helm Chart Enhancements**

- New `mcp-mesh-grafana` and `mcp-mesh-tempo` charts
- Enhanced agent code deployment methods with improved configuration
- Comprehensive chart ecosystem for full-stack deployments

## v0.3.0 (2025-07-04)

### 🚀 Major Features

**Enhanced Proxy System**

- Automatic proxy configuration from decorator kwargs (timeout, retry_count, custom_headers)
- Smart proxy selection based on capability requirements
- Authentication and streaming auto-configuration

**Redis-Backed Session Management**

- Distributed session storage with graceful in-memory fallback
- Session stickiness for stateful applications
- Automatic routing to same pod instances

**Advanced Agent Types**

- `McpMeshAgent`: Lightweight proxies for simple tool calls
- `McpAgent`: Full MCP protocol support with streaming and session management
- Backward compatibility maintained

**Streaming Support**

- `call_tool_streaming()` for real-time data processing
- FastMCP integration with text/event-stream
- Multihop streaming capabilities

### ⚡ Performance & Infrastructure

**Fast Heartbeat Optimization**

- 5-second heartbeat intervals with HEAD request optimization
- Sub-20 second topology change detection
- Improved fault tolerance and recovery

**Kubernetes Native**

- Comprehensive ingress support eliminates port forwarding
- Agent status management with graceful shutdown
- Enhanced health check endpoints

**Architecture Improvements**

- Registry as facilitator pattern
- Direct agent-to-agent communication
- Background orchestration with minimal overhead

### 📚 Developer Experience

**Enhanced Documentation**

- Comprehensive mesh decorator examples
- Clear distinction between agent types
- Advanced usage patterns and best practices

**Improved CLI**

- Better startup performance
- Enhanced error messages
- Environment variable consistency

### 🔧 Technical Improvements

- Ent migration completion (removed GORM/SQL remnants)
- Dependency resolution optimization
- Tag handling consistency fixes
- Python runtime cleanup

---

## v0.2.1 (2025-07-01)

### 🐛 Bug Fixes

- Fix Python packaging source paths in release workflow
- Resolve version update path issues
- Address DecoratorRegistry gaps and environment variable consistency

### 📦 Infrastructure

- Complete MCP Mesh 0.2.0 release preparation
- Add HEAD method support for efficient health checks
- Optimize CLI startup and FastAPI termination performance

---

## v0.1.0 (2025-06-19)

### 🎯 Initial Release

- Core dependency injection system
- Kubernetes deployment support
- Basic agent discovery and communication
- FastMCP integration
- Docker and Helm chart support
