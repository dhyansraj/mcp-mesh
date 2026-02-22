# Troubleshooting (Java)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">&#x1F40D;</span>
  <span>Looking for Python? See <a href="../../../python/local-development/troubleshooting/">Python Troubleshooting</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">&#x1F4D8;</span>
  <span>Looking for TypeScript? See <a href="../../../typescript/local-development/troubleshooting/">TypeScript Troubleshooting</a></span>
</div>

> Common issues and solutions for MCP Mesh Java development

## Quick Diagnostics

```bash
# Check CLI is installed
meshctl --version

# Check registry is running
curl http://localhost:8000/health

# List agents and their status
meshctl list --all

# Check agent logs
meshctl logs <agent-name> --since 5m
```

## Maven Build Issues

### Build Fails: Cannot Resolve mcp-mesh-spring-boot-starter

**Symptom:** `Could not find artifact io.mcp-mesh:mcp-mesh-spring-boot-starter`

Ensure the dependency version matches an available release:

```xml
<dependency>
    <groupId>io.mcp-mesh</groupId>
    <artifactId>mcp-mesh-spring-boot-starter</artifactId>
    <version>0.9.8</version>
</dependency>
```

```bash
# Force re-download of dependencies
mvn clean install -U
```

### Build Fails: Incompatible Java Version

**Symptom:** `source release 17 requires target release 17`

```bash
# Check Java version
java -version

# Ensure JAVA_HOME points to JDK 17+
echo $JAVA_HOME

# On macOS with multiple JDKs
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
```

### Build Fails: Spring Boot Parent Version Mismatch

**Symptom:** Dependency conflicts or `NoSuchMethodError` at runtime

Ensure you are using the correct Spring Boot parent version:

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>4.0.2</version>
    <relativePath/>
</parent>
```

## Native Library Issues

### UnsatisfiedLinkError for mcp-mesh-native

**Symptom:** `java.lang.UnsatisfiedLinkError: no mcpmesh in java.library.path`

The `mcp-mesh-spring-boot-starter` includes a native library that is loaded automatically. If it fails:

```bash
# Check that the native dependency is present
mvn dependency:tree | grep mcp-mesh-native

# Force clean rebuild
mvn clean package -DskipTests

# If using a non-standard OS/arch, check supported platforms
meshctl man java-native-platforms
```

### Native Library on Apple Silicon

If running on Apple Silicon (M1/M2/M3/M4):

```bash
# Verify architecture
uname -m  # Should show arm64

# The starter includes aarch64 binaries; ensure you're using an ARM JDK
java -XshowSettings:all 2>&1 | grep os.arch
```

## Dependency Injection Issues

### McpMeshTool Parameter is Null

**Symptom:** `NullPointerException` when calling a `McpMeshTool` dependency

The dependency might not be available in the mesh yet. Always check before calling:

```java
@MeshTool(
    capability = "my_tool",
    dependencies = @Selector(capability = "remote_service")
)
public Result doWork(
        @Param(value = "input", description = "Input data") String input,
        McpMeshTool<RemoteResult> remoteService) {

    // Always check availability
    if (remoteService == null || !remoteService.isAvailable()) {
        return new Result("Remote service unavailable");
    }

    RemoteResult result = remoteService.call("data", input);
    return new Result(result.value());
}
```

Also verify the providing agent is running:

```bash
meshctl list
meshctl status my-agent
```

### Wrong Capability Matched

**Symptom:** Dependency resolves to an unexpected agent

Use `meshctl status <agent>` to see which agents are wired to which capabilities. Refine selection with tag filters:

```java
@Selector(capability = "llm", tags = {"+claude", "-deprecated"})
```

## Spring Boot Startup Issues

### Port Already in Use

**Symptom:** `Web server failed to start. Port 8080 was already in use.`

```bash
# Find what's using the port
lsof -i :8080

# Kill it
kill $(lsof -t -i:8080)

# Or let meshctl assign a port (recommended for local dev)
meshctl start hello/
```

When running via `meshctl start`, port assignment is handled automatically. Hardcoded ports in `@MeshAgent(port = ...)` can cause conflicts when running multiple agents.

### Application Context Fails to Load

**Symptom:** `ApplicationContextException` or `BeanCreationException`

```bash
# Run with debug to see full Spring context loading
meshctl start --debug hello/

# Or via Maven with Spring debug
cd hello/
mvn spring-boot:run -Dspring-boot.run.arguments=--debug
```

Common causes:

- Missing `@SpringBootApplication` on the main class
- Missing `@MeshAgent` annotation
- Duplicate bean definitions (multiple `@MeshAgent` classes)

### Agent Starts But Does Not Register

**Symptom:** Agent logs show it's running, but `meshctl list` does not show it

```bash
# Check registry is running
curl http://localhost:8000/health

# Check agent is pointing to the right registry
# Default is http://localhost:8000 -- override with:
export MCP_MESH_REGISTRY_URL=http://localhost:8000
```

## Tool Call Issues

### Tool Not Found

```bash
# List all available tools
meshctl list --tools

# Check tool details
meshctl list --tools=greeting
```

### Call Timeout

```bash
# Increase timeout (default 30s)
meshctl call --timeout 60 slow_operation

# Check if agent is healthy
meshctl list
```

### Schema Mismatch

**Symptom:** `Invalid arguments` error when calling a tool

```bash
# Check tool's expected schema
meshctl list --tools=greeting

# Shows parameter types and required fields
```

Ensure `@Param` annotations match the expected parameter names and types.

## Logging & Debugging

### Enable Debug Logging

```bash
# Via CLI flag
meshctl start --debug hello/

# Or via log level
meshctl start --log-level DEBUG hello/

# TRACE level for detailed request/response logging
meshctl start --log-level TRACE hello/
```

### Attach IDE Debugger

To use breakpoints and step-through debugging:

```bash
# 1. Start registry
meshctl start --registry-only

# 2. Run the agent from your IDE with remote debug enabled, or:
cd hello/
mvn spring-boot:run -Dspring-boot.run.jvmArguments="-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5005"

# 3. Attach your IDE debugger to port 5005
```

## Getting Help

```bash
# Built-in documentation
meshctl man --list
meshctl man <topic>

# Command help
meshctl <command> --help
```

## Still Stuck?

1. Check [GitHub Issues](https://github.com/dhyansraj/mcp-mesh/issues)
2. Enable `--debug` and share the logs
3. Create a minimal reproduction case
