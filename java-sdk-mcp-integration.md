# Java SDK MCP Integration Design

## Overview

This document captures the design for integrating the official MCP Java SDK with MCP Mesh,
based on detailed analysis of Python SDK's FastMCP integration.

## Architecture Comparison

| Component            | Python                   | Java                                             |
| -------------------- | ------------------------ | ------------------------------------------------ |
| MCP Protocol         | FastMCP                  | MCP Java SDK (`io.modelcontextprotocol.sdk:mcp`) |
| Mesh Coordination    | Rust core (pyo3)         | Rust core (JNR-FFI)                              |
| Tool Annotation      | `@mesh.tool`             | `@MeshTool`                                      |
| Dependency Injection | `McpMeshTool` parameter  | `McpMeshTool` parameter                          |
| LLM Injection        | `MeshLlmAgent` parameter | `MeshLlmAgent` parameter                         |

---

## Python SDK Analysis (Reference Implementation)

### 1. Decorator Processing Flow

```python
@mesh.tool(capability="calculator", dependencies=["add-service"])
@server.tool()  # FastMCP decorator
def calc(a: int, b: int, add_svc: McpMeshTool) -> int:
    return add_svc.invoke({"x": a, "y": b})
```

**Decorator execution order (bottom-up in Python):**

1. `@server.tool()` executes first - FastMCP prepares to register
2. `@mesh.tool()` executes second - creates wrapper, returns wrapper to FastMCP
3. FastMCP caches the **wrapper** (not original function)

**Key insight**: FastMCP holds a reference to our wrapper. We can update the wrapper's
internal state (dependency proxies) and FastMCP will use the updated values on next call.

### 2. Wrapper Creation (`dependency_injector.py`)

The `create_injection_wrapper()` method:

```python
# Step 1: Analyze injection positions
mesh_positions = analyze_injection_strategy(func, dependencies)
# Returns: [2] = position where McpMeshTool parameter is (0-indexed)

# Step 2: Create dependency tracking with composite keys
dep_key = f"{func.__module__}.{func.__qualname__}:dep_0"
# e.g., "mymodule.calc:dep_0"

# Step 3: Create array-based storage ON THE WRAPPER
dependency_wrapper._mesh_injected_deps = [None]  # One slot per dependency

# Step 4: Create update callback stored ON THE WRAPPER
def update_dependency(dep_index: int, instance: Any) -> None:
    dependency_wrapper._mesh_injected_deps[dep_index] = instance

dependency_wrapper._mesh_update_dependency = update_dependency

# Step 5: Register wrapper in function registry
function_registry[func_id] = dependency_wrapper
```

### 3. Wrapper Execution (Call Time)

```python
@functools.wraps(func)
async def dependency_wrapper(*args, **kwargs):
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())  # ["a", "b", "add_svc"]
    final_kwargs = kwargs.copy()  # {"a": 5, "b": 3}

    # Inject dependencies by position
    for dep_index, param_position in enumerate(mesh_positions):
        param_name = params[param_position]  # "add_svc"

        # Get from wrapper's array (already updated by heartbeat)
        dependency = dependency_wrapper._mesh_injected_deps[dep_index]

        final_kwargs[param_name] = dependency

    # Call original: calc(a=5, b=3, add_svc=<proxy>)
    return await func(*args, **final_kwargs)
```

### 4. Heartbeat Cycle Updates

```python
# When registry returns resolved dependencies:
async def register_dependency(self, composite_key: str, instance: Any):
    # composite_key = "mymodule.calc:dep_0"

    # Find wrapper in registry
    func_id = composite_key.split(":dep_")[0]  # "mymodule.calc"
    wrapper = self._function_registry[func_id]

    # Extract index
    dep_index = int(composite_key.split(":dep_")[1])  # 0

    # Update wrapper's array IN-PLACE
    wrapper._mesh_update_dependency(dep_index, instance)
```

### 5. Schema Filtering

McpMeshTool parameters are HIDDEN from MCP schema:

```python
def extract_input_schema_excluding_mesh_agents(function):
    schema = get_full_schema(function)

    # Find McpMeshTool typed parameters
    mesh_positions = get_mesh_agent_positions(function)
    param_names = list(inspect.signature(function).parameters.keys())
    mesh_param_names = {param_names[i] for i in mesh_positions}

    # Remove from schema
    for param_name in mesh_param_names:
        schema["properties"].pop(param_name, None)
        if param_name in schema.get("required", []):
            schema["required"].remove(param_name)

    return schema
```

Result: MCP clients see `{"a": "integer", "b": "integer"}` - no `add_svc`.

### 6. Type Detection

```python
def _is_mesh_tool_type(param_type: Any) -> bool:
    # Direct type check
    if param_type == McpMeshTool:
        return True

    # Union type: McpMeshTool | None
    if hasattr(param_type, "__args__"):
        for arg in param_type.__args__:
            if arg == McpMeshTool:
                return True

    return False
```

---

## Key Design Patterns from Python

### Pattern 1: Wrapper Object Identity

```
Original function:  calc at 0x7f1234567890
                         ↓
@mesh.tool creates: dependency_wrapper at 0x7f1234567abc
                         ↓
FastMCP caches:     dependency_wrapper at 0x7f1234567abc
                         ↓
Heartbeat updates:  dependency_wrapper._mesh_injected_deps = [new_proxy]
                         ↓
Next call:          FastMCP calls 0x7f1234567abc → uses new_proxy
```

**Critical**: Same wrapper object is cached by FastMCP. We update its internal state.
No re-registration needed.

### Pattern 2: Composite Dependency Keys

```
Function: "com.example.Calculator.calc"
Dependencies: ["add-service", "multiply-service"]

Keys:
- "com.example.Calculator.calc:dep_0" → add-service proxy
- "com.example.Calculator.calc:dep_1" → multiply-service proxy

Reverse mapping (for heartbeat updates):
- "com.example.Calculator.calc:dep_0" → ["com.example.Calculator.calc"]
- "com.example.Calculator.calc:dep_1" → ["com.example.Calculator.calc"]
```

### Pattern 3: Array-Based Indexed Storage

```python
# NOT: {"add-service": proxy1, "multiply-service": proxy2}
# YES: [proxy1, proxy2]  # Indexed by declaration order

dependencies = ["add-service", "add-service", "multiply-service"]
_mesh_injected_deps = [proxy1, proxy2, proxy3]  # Same service can appear twice
```

**Why array?** Same capability can be declared multiple times with different tags.

### Pattern 4: Update Callback on Wrapper

```python
# Store callback ON the wrapper itself
wrapper._mesh_update_dependency = lambda idx, val: ...

# Heartbeat can update without knowing wrapper internals
wrapper._mesh_update_dependency(0, new_proxy)
```

---

## Java Implementation Design

### 1. Wrapper Class

```java
public class MeshToolWrapper implements BiFunction<McpServerExchange, Map<String, Object>, CallToolResult> {

    private final Object bean;
    private final Method originalMethod;
    private final List<String> mcpParamNames;      // ["a", "b"] - exposed to MCP
    private final List<Integer> meshPositions;      // [2] - positions of McpMeshTool params
    private final List<String> meshParamNames;      // ["add_svc"] - for injection

    // Mutable dependency array (updated by heartbeat)
    private final AtomicReferenceArray<McpMeshTool> injectedDeps;

    public MeshToolWrapper(Object bean, Method method, List<String> dependencies) {
        this.bean = bean;
        this.originalMethod = method;
        this.meshPositions = analyzeMeshPositions(method);
        this.injectedDeps = new AtomicReferenceArray<>(dependencies.size());
        // ... initialize param names
    }

    // Called by heartbeat to update cached proxy
    public void updateDependency(int depIndex, McpMeshTool proxy) {
        injectedDeps.set(depIndex, proxy);
    }

    // Called by MCP SDK on tool invocation
    @Override
    public CallToolResult apply(McpServerExchange exchange, Map<String, Object> mcpArgs) {
        // Build full argument array
        Object[] fullArgs = new Object[originalMethod.getParameterCount()];

        // Fill MCP args (a, b)
        int mcpIdx = 0;
        for (int i = 0; i < fullArgs.length; i++) {
            if (!meshPositions.contains(i)) {
                fullArgs[i] = convertArg(mcpArgs.get(mcpParamNames.get(mcpIdx++)), ...);
            }
        }

        // Fill injected dependencies
        for (int depIdx = 0; depIdx < meshPositions.size(); depIdx++) {
            int paramPos = meshPositions.get(depIdx);
            fullArgs[paramPos] = injectedDeps.get(depIdx);  // From cached array
        }

        // Invoke original method
        Object result = originalMethod.invoke(bean, fullArgs);
        return new CallToolResult(serialize(result), false);
    }
}
```

### 2. Wrapper Registry

```java
public class MeshToolWrapperRegistry {

    // func_id → wrapper (for MCP SDK registration)
    private final Map<String, MeshToolWrapper> wrappers = new ConcurrentHashMap<>();

    // composite_key → set of func_ids (for heartbeat updates)
    private final Map<String, Set<String>> dependencyMapping = new ConcurrentHashMap<>();

    public void registerWrapper(String funcId, MeshToolWrapper wrapper, List<String> dependencies) {
        wrappers.put(funcId, wrapper);

        for (int i = 0; i < dependencies.size(); i++) {
            String compositeKey = funcId + ":dep_" + i;
            dependencyMapping.computeIfAbsent(compositeKey, k -> ConcurrentHashMap.newKeySet())
                .add(funcId);
        }
    }

    // Called by heartbeat event handler
    public void updateDependency(String compositeKey, McpMeshTool proxy) {
        String funcId = compositeKey.split(":dep_")[0];
        int depIndex = Integer.parseInt(compositeKey.split(":dep_")[1]);

        MeshToolWrapper wrapper = wrappers.get(funcId);
        if (wrapper != null) {
            wrapper.updateDependency(depIndex, proxy);
        }
    }
}
```

### 3. Schema Generation (Filter McpMeshTool)

```java
public class MeshToolSchemaGenerator {

    public static Map<String, Object> generateSchema(Method method) {
        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();

        for (Parameter param : method.getParameters()) {
            // Skip McpMeshTool and MeshLlmAgent parameters
            if (McpMeshTool.class.isAssignableFrom(param.getType()) ||
                MeshLlmAgent.class.isAssignableFrom(param.getType())) {
                continue;  // Don't include in schema
            }

            Param annotation = param.getAnnotation(Param.class);
            if (annotation != null) {
                properties.put(annotation.value(), buildParamSchema(param));
                if (annotation.required()) {
                    required.add(annotation.value());
                }
            }
        }

        return Map.of(
            "type", "object",
            "properties", properties,
            "required", required
        );
    }
}
```

### 4. MCP SDK Integration

```java
@Configuration
public class MeshMcpServerConfiguration {

    @Bean
    public McpSyncServer mcpServer(
            HttpServletStreamableServerTransportProvider transport,
            MeshToolWrapperRegistry wrapperRegistry) {

        McpSyncServer server = McpServer.sync(transport)
            .serverInfo(agentName, agentVersion)
            .capabilities(ServerCapabilities.builder().tools(true).build())
            .build();

        // Register all wrappers with MCP SDK
        for (var entry : wrapperRegistry.getAllWrappers().entrySet()) {
            String capability = entry.getKey();
            MeshToolWrapper wrapper = entry.getValue();

            var spec = new McpServerFeatures.SyncToolSpecification(
                new Tool(capability, wrapper.getDescription(), wrapper.getSchema()),
                wrapper::apply  // MCP SDK calls our wrapper
            );

            server.addTool(spec);
        }

        return server;
    }
}
```

### 5. Event Handler (Heartbeat Updates)

```java
@Component
public class MeshEventProcessor {

    private final MeshToolWrapperRegistry wrapperRegistry;
    private final McpMeshToolProxyFactory proxyFactory;

    public void processEvent(MeshEvent event) {
        switch (event.getEventType()) {
            case DEPENDENCY_RESOLVED:
                String compositeKey = event.getRequestingFunction() + ":dep_" + event.getDepIndex();
                String endpoint = event.getEndpoint();
                String functionName = event.getFunctionName();

                // Create or update proxy
                McpMeshTool proxy = proxyFactory.createProxy(endpoint, functionName);

                // Update wrapper's cached dependency
                wrapperRegistry.updateDependency(compositeKey, proxy);
                break;
            // ... other events
        }
    }
}
```

---

## Execution Flow Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STARTUP                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. @MeshTool annotation scanned by BeanPostProcessor                        │
│  2. MeshToolWrapper created for each tool                                    │
│  3. Wrapper registered in MeshToolWrapperRegistry                            │
│  4. Wrapper registered with MCP Java SDK (McpServer.addTool)                 │
│  5. MCP SDK caches wrapper reference                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      HEARTBEAT CYCLE (Background)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. HEAD request to registry                                                 │
│  2. If topology changed → POST with full dependency payload                  │
│  3. Registry returns: { "calc:dep_0": {endpoint, functionName} }             │
│  4. MeshEventProcessor receives DEPENDENCY_RESOLVED event                    │
│  5. Create McpMeshTool proxy pointing to resolved endpoint                   │
│  6. wrapperRegistry.updateDependency("calc:dep_0", proxy)                    │
│  7. Wrapper's injectedDeps[0] = proxy (in-place update)                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      CALL TIME (Fast Path)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. MCP request: tools/call { name: "calculator", args: {a:5, b:3} }         │
│  2. MCP SDK calls wrapper.apply(exchange, {a:5, b:3})                        │
│  3. Wrapper reads injectedDeps[0] → proxy (already resolved)                 │
│  4. Wrapper invokes: calc(5, 3, proxy)                                       │
│  5. Original method executes: proxy.call({x:5, y:3})                         │
│  6. Proxy makes MCP HTTP call to resolved endpoint                           │
│  7. Result returned to MCP SDK                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Thread Safety Considerations

1. **AtomicReferenceArray** for `injectedDeps` - safe concurrent reads during calls
2. **ConcurrentHashMap** for registries - safe concurrent updates during heartbeat
3. **Volatile or synchronized** for proxy endpoint updates
4. **Copy-on-read** if needed for complex proxy state

---

## MCP Transport Selection: SSE vs Stateless

### The Problem

The initial implementation used `HttpServletSseServerTransportProvider` which is **session-based**:

```bash
# This fails with "Session ID missing in message endpoint"
curl -X POST http://localhost:9000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

SSE transport requires:

1. Client first establishes SSE connection via GET
2. Server returns a session ID
3. Client includes session ID in subsequent POST requests

However, Python's FastMCP uses a **stateless** protocol where clients can POST directly without session establishment. This is also how `meshctl` and the MCP Mesh registry communicate with agents.

### Available Transports in MCP Java SDK (v0.17.2+)

The MCP Java SDK provides multiple transport options:

| Transport                                      | Type                           | Module               | Use Case                                |
| ---------------------------------------------- | ------------------------------ | -------------------- | --------------------------------------- |
| `HttpServletSseServerTransportProvider`        | SSE, Session-based             | `mcp` (core)         | Interactive clients needing server push |
| `HttpServletStreamableServerTransportProvider` | Streamable-HTTP, Session-based | `mcp` (core)         | Bidirectional streaming                 |
| `HttpServletStatelessServerTransport`          | **Stateless**                  | `mcp` (core)         | Microservices, cloud-native ✅          |
| `WebMvcSseServerTransportProvider`             | SSE                            | `mcp-spring-webmvc`  | Spring WebMvc + SSE                     |
| `WebMvcStreamableServerTransportProvider`      | Streamable-HTTP                | `mcp-spring-webmvc`  | Spring WebMvc + streaming               |
| `WebMvcStatelessServerTransport`               | **Stateless**                  | `mcp-spring-webmvc`  | Spring WebMvc + stateless ✅            |
| `WebFluxSseServerTransportProvider`            | SSE                            | `mcp-spring-webflux` | Reactive SSE                            |
| `WebFluxStatelessServerTransport`              | **Stateless**                  | `mcp-spring-webflux` | Reactive stateless                      |

### Recommended: Stateless Transport

For MCP Mesh agents, use **stateless transport** because:

1. **Protocol compatibility** - Matches FastMCP (Python) behavior
2. **Simpler deployment** - No session state to manage
3. **Horizontal scaling** - No sticky sessions required
4. **Cloud-native** - Works well with load balancers and Kubernetes

### Configuration: Servlet-based Stateless (No extra dependency)

```java
@Configuration
@EnableWebMvc
public class MeshMcpServerConfiguration {

    @Bean
    public HttpServletStatelessServerTransport mcpStatelessTransport(ObjectMapper mapper) {
        return HttpServletStatelessServerTransport.builder()
            .objectMapper(mapper)
            .mcpEndpoint("/mcp")
            .build();
    }

    @Bean
    public ServletRegistrationBean<HttpServlet> mcpServletRegistration(
            HttpServletStatelessServerTransport transport) {
        ServletRegistrationBean<HttpServlet> registration =
            new ServletRegistrationBean<>(transport, "/mcp/*");
        registration.setName("mcpServlet");
        registration.setLoadOnStartup(1);
        return registration;
    }

    @Bean
    public McpStatelessSyncServer mcpServer(
            HttpServletStatelessServerTransport transport,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshProperties properties) {

        McpStatelessSyncServer server = McpServer.sync(transport)
            .serverInfo(properties.getAgent().getName(), properties.getAgent().getVersion())
            .capabilities(ServerCapabilities.builder().tools(true).build())
            .build();

        // Register all tools
        for (MeshToolWrapper wrapper : wrapperRegistry.getAllWrappers()) {
            server.addTool(new McpServerFeatures.SyncToolSpecification(
                new Tool(wrapper.getCapability(), wrapper.getDescription(), wrapper.getSchemaJson()),
                (exchange, args) -> wrapper.invoke(args)
            ));
        }

        return server;
    }
}
```

### Configuration: Spring WebMvc Stateless (Alternative)

If using Spring WebMvc's RouterFunction approach:

```java
@Configuration
@EnableWebMvc
public class MeshMcpServerConfiguration {

    @Bean
    public WebMvcStatelessServerTransport webMvcStatelessTransport(ObjectMapper mapper) {
        return WebMvcStatelessServerTransport.builder()
            .objectMapper(mapper)
            .messageEndpoint("/mcp")
            .build();
    }

    @Bean
    public RouterFunction<ServerResponse> mcpRouterFunction(
            WebMvcStatelessServerTransport transport) {
        return transport.getRouterFunction();
    }

    @Bean
    public McpStatelessSyncServer mcpServer(
            WebMvcStatelessServerTransport transport,
            MeshToolWrapperRegistry wrapperRegistry) {
        // ... same as above
    }
}
```

**Note**: This requires adding the `mcp-spring-webmvc` dependency:

```xml
<dependency>
    <groupId>io.modelcontextprotocol.sdk</groupId>
    <artifactId>mcp-spring-webmvc</artifactId>
    <version>${mcp-sdk.version}</version>
</dependency>
```

### Key Differences: McpSyncServer vs McpStatelessSyncServer

| Aspect               | `McpSyncServer`              | `McpStatelessSyncServer`     |
| -------------------- | ---------------------------- | ---------------------------- |
| Session state        | Maintains session per client | No session state             |
| Server notifications | Can push to clients          | Cannot push to clients       |
| Protocol             | Full MCP (SSE/Streamable)    | Subset (JSON responses only) |
| Response format      | `text/event-stream`          | `application/json`           |
| Use case             | Interactive clients          | Microservices, mesh agents   |

### Version Requirements

The stateless transports were added in later versions of the MCP Java SDK:

```xml
<!-- Minimum version for stateless support -->
<mcp-sdk.version>0.17.2</mcp-sdk.version>
```

Current implementation uses `0.10.0` which only has SSE transport.

### Migration Checklist (PENDING)

To switch from SSE to stateless:

- [ ] **PENDING**: Update MCP SDK version: `0.10.0` → `0.17.2`
- [ ] **PENDING**: Change transport: `HttpServletSseServerTransportProvider` → `HttpServletStatelessServerTransport`
- [ ] **PENDING**: Change server type: `McpSyncServer` → `McpStatelessSyncServer`
- [ ] **PENDING**: Update servlet registration (endpoint pattern may differ)
- [ ] **PENDING**: Test with `curl` direct POST (should work without session)
- [ ] **PENDING**: Test with `meshctl call` (should work end-to-end)

**Note**: Current SSE transport works for basic functionality. Stateless migration is optional but recommended for full compatibility with Python/meshctl.

---

## Review Feedback & Refinements

### 1. Parameter Name Discovery

Java doesn't preserve parameter names by default. Options:

- Use `-parameters` compiler flag (recommended in pom.xml)
- Rely on `@Param("name")` annotation (already required)

```xml
<!-- In pom.xml -->
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-compiler-plugin</artifactId>
    <configuration>
        <parameters>true</parameters>  <!-- Preserve parameter names -->
    </configuration>
</plugin>
```

### 2. Exception Handling

Unwrap `InvocationTargetException` in wrapper:

```java
@Override
public CallToolResult apply(McpServerExchange exchange, Map<String, Object> mcpArgs) {
    try {
        Object result = originalMethod.invoke(bean, fullArgs);
        return new CallToolResult(serialize(result), false);
    } catch (InvocationTargetException e) {
        Throwable cause = e.getCause();
        log.error("Tool execution failed: {}", cause.getMessage(), cause);
        return new CallToolResult("Error: " + cause.getMessage(), true);  // isError=true
    } catch (IllegalAccessException e) {
        return new CallToolResult("Access error: " + e.getMessage(), true);
    }
}
```

### 3. Async Method Support

Handle `CompletableFuture<T>` returns:

```java
Object result = originalMethod.invoke(bean, fullArgs);

// Unwrap CompletableFuture if present
if (result instanceof CompletableFuture<?> future) {
    try {
        result = future.get(30, TimeUnit.SECONDS);  // Configurable timeout
    } catch (TimeoutException e) {
        return new CallToolResult("Timeout waiting for async result", true);
    } catch (ExecutionException e) {
        return new CallToolResult("Async error: " + e.getCause().getMessage(), true);
    }
}

return new CallToolResult(serialize(result), false);
```

### 4. Null Dependency Handling (Graceful Degradation)

Dependencies may be null if not yet resolved:

```java
// Option A: Check and fail gracefully
McpMeshTool dep = injectedDeps.get(depIdx);
if (dep == null) {
    return new CallToolResult(
        "Dependency not available: " + dependencyNames.get(depIdx),
        true
    );
}
fullArgs[paramPos] = dep;

// Option B: Support Optional<McpMeshTool> in signature
@MeshTool(capability = "example")
public String example(
    @Param("input") String input,
    Optional<McpMeshTool> optionalDep  // Null-safe
) {
    if (optionalDep.isEmpty()) {
        return "Dependency not available";
    }
    return optionalDep.get().call(...);
}
```

### 5. Transport Type Selection

MCP Java SDK has multiple transports. For HTTP-based mesh agents:

| Transport                                      | Use Case                                        |
| ---------------------------------------------- | ----------------------------------------------- |
| `HttpServletStreamableServerTransportProvider` | Bidirectional, stateful sessions                |
| `HttpServletStatelessServerTransport`          | Stateless, microservices (recommended for mesh) |
| `HttpServletSseServerTransportProvider`        | SSE-based streaming                             |

**Recommendation**: Use `HttpServletStatelessServerTransport` for mesh agents - matches
how Python FastMCP exposes HTTP endpoints and is simpler for load balancing.

```java
@Bean
public HttpServletStatelessServerTransport mcpTransport(ObjectMapper mapper) {
    return HttpServletStatelessServerTransport.builder()
        .objectMapper(mapper)
        .mcpEndpoint("/mcp")
        .build();
}
```

### 6. Proxy Caching

Reuse proxies for same endpoint+function (like Python):

```java
public class McpMeshToolProxyFactory {
    private final Map<String, McpMeshToolProxy> proxyCache = new ConcurrentHashMap<>();
    private final OkHttpClient httpClient;

    public McpMeshTool getOrCreateProxy(String endpoint, String functionName) {
        String cacheKey = endpoint + ":" + functionName;
        return proxyCache.computeIfAbsent(cacheKey, k ->
            new McpMeshToolProxy(httpClient, endpoint, functionName)
        );
    }

    // Called when topology changes to invalidate stale proxies
    public void invalidateProxy(String endpoint, String functionName) {
        proxyCache.remove(endpoint + ":" + functionName);
    }
}
```

### 7. MeshLlmAgent Detection (By Type)

Detection is purely by parameter type, not annotation attribute:

```java
@MeshTool(capability = "chat")
@MeshLlm(provider = "claude", filter = @Selector(capability = "tools"))
public String chat(
    @Param("message") String message,
    MeshLlmAgent llm  // Detected by type: MeshLlmAgent.class
) {
    return llm.generate(message);
}

// In wrapper creation:
private List<Integer> analyzeLlmAgentPositions(Method method) {
    List<Integer> positions = new ArrayList<>();
    Parameter[] params = method.getParameters();
    for (int i = 0; i < params.length; i++) {
        if (MeshLlmAgent.class.isAssignableFrom(params[i].getType())) {
            positions.add(i);
        }
    }
    return positions;
}
```

### 8. Simplified Dependency Mapping

Claude Web noted the mapping seems inverted. Simplified approach:

```java
public class MeshToolWrapperRegistry {
    // funcId → wrapper (for MCP SDK registration and updates)
    private final Map<String, MeshToolWrapper> wrappers = new ConcurrentHashMap<>();

    public void registerWrapper(String funcId, MeshToolWrapper wrapper) {
        wrappers.put(funcId, wrapper);
    }

    // Called by heartbeat - extract funcId from compositeKey
    public void updateDependency(String compositeKey, McpMeshTool proxy) {
        // compositeKey = "com.example.Calc.calc:dep_0"
        int depSeparator = compositeKey.lastIndexOf(":dep_");
        String funcId = compositeKey.substring(0, depSeparator);
        int depIndex = Integer.parseInt(compositeKey.substring(depSeparator + 5));

        MeshToolWrapper wrapper = wrappers.get(funcId);
        if (wrapper != null) {
            wrapper.updateDependency(depIndex, proxy);
        }
    }
}
```

No separate `dependencyMapping` needed - funcId is embedded in compositeKey.

---

## MeshLlmAgent Integration

Same pattern as McpMeshTool but for LLM agent injection:

```java
@MeshTool(capability = "chat")
@MeshLlm(provider = "claude", filter = @Selector(capability = "tools"))
public String chat(
    @Param("message") String message,
    MeshLlmAgent llm           // Injected by @MeshLlm processing
) {
    return llm.generate(message);
}
```

Wrapper handles both:

- `McpMeshTool` dependencies (from `@MeshTool(dependencies=...)`)
- `MeshLlmAgent` (from `@MeshLlm`)

---

## Config Resolution: Rust Core as Single Source of Truth

### The Problem

The Java SDK currently implements its own config resolution in `MeshConfigResolver.java`, which:

1. Does NOT auto-detect external IP for `http_host`
2. Defaults to `"localhost"` when no explicit value is provided
3. Causes agents to register with unreachable addresses

This violates the architecture principle: **Rust core is the single communication interface for mesh registry**.

### How Other SDKs Do It (Correct Pattern)

**Python SDK** (`host_resolver.py`):

```python
def get_external_host() -> str:
    # Delegates to Rust core
    host = mcp_mesh_core.resolve_config_py("http_host", None)
    return host
```

**TypeScript SDK** (`config.ts`):

```typescript
// Delegates to Rust core via NAPI
resolvedHost = rustResolveConfig("http_host", config.httpHost ?? null);
```

**Rust Core** (`config.rs`):

```rust
pub fn resolve_config(key: ConfigKey, param_value: Option<&str>) -> Option<String> {
    // Priority 1: Environment variable (MCP_MESH_HTTP_HOST)
    if let Ok(value) = env::var(key.env_var()) {
        return Some(value);
    }

    // Priority 2: Parameter value from code
    if let Some(v) = param_value {
        return Some(v.to_string());
    }

    // Priority 3: Special case for HttpHost - AUTO-DETECT IP
    if key == ConfigKey::HttpHost {
        let ip = auto_detect_external_ip();  // UDP socket trick
        return Some(ip);
    }

    // Other defaults...
}
```

### Current Java SDK (Incorrect Pattern)

**Java SDK** (`MeshConfigResolver.java`):

```java
// Does NOT delegate to Rust - reinvents the wheel incorrectly
public String resolve(String key, String annotationValue, String propertiesValue) {
    // Check ENV, System Props, properties file, annotation
    // Returns null if nothing found → defaults to "localhost"
    return null;  // ❌ No auto-detect IP!
}
```

### Root Cause: C FFI Missing Config Functions

The C FFI (`mcp_mesh_core.h`) does not expose config resolution functions:

| Function             | Python (PyO3)              | TypeScript (NAPI)     | C FFI (Java) |
| -------------------- | -------------------------- | --------------------- | ------------ |
| `resolve_config`     | ✅ `resolve_config_py`     | ✅ `resolveConfig`    | ❌ Missing   |
| `resolve_config_int` | ✅ `resolve_config_int_py` | ✅ `resolveConfigInt` | ❌ Missing   |
| `auto_detect_ip`     | ✅ `auto_detect_ip_py`     | ✅ `autoDetectIp`     | ❌ Missing   |

### Solution: Extend C FFI

#### Step 1: Add Functions to Rust FFI (`src/runtime/core/src/ffi.rs`)

```rust
/// Resolve configuration value with priority: ENV > param > default.
/// For http_host, auto-detects external IP if no value provided.
///
/// # Arguments
/// * `key_name` - Config key (e.g., "http_host", "registry_url", "namespace")
/// * `param_value` - Optional value from code/config (NULL for none)
///
/// # Returns
/// Resolved value (caller must free with mesh_free_string)
#[no_mangle]
pub extern "C" fn mesh_resolve_config(
    key_name: *const c_char,
    param_value: *const c_char,
) -> *mut c_char {
    let key = unsafe { CStr::from_ptr(key_name).to_str().unwrap_or("") };
    let param = if param_value.is_null() {
        None
    } else {
        unsafe { CStr::from_ptr(param_value).to_str().ok() }
    };

    let result = crate::config::resolve_config_by_name(key, param);
    CString::new(result).unwrap().into_raw()
}

/// Resolve integer configuration value.
///
/// # Arguments
/// * `key_name` - Config key (e.g., "http_port", "heartbeat_interval")
/// * `param_value` - Value from code/config (-1 for none)
///
/// # Returns
/// Resolved value, or -1 if unknown key
#[no_mangle]
pub extern "C" fn mesh_resolve_config_int(
    key_name: *const c_char,
    param_value: i64,
) -> i64 {
    let key = unsafe { CStr::from_ptr(key_name).to_str().unwrap_or("") };
    let param = if param_value < 0 { None } else { Some(param_value) };

    match crate::config::ConfigKey::from_name(key) {
        Some(k) => crate::config::resolve_config_int(k, param).unwrap_or(-1),
        None => -1,
    }
}

/// Auto-detect external IP address.
/// Uses UDP socket trick to find IP that routes to external networks.
///
/// # Returns
/// IP address string (caller must free with mesh_free_string)
#[no_mangle]
pub extern "C" fn mesh_auto_detect_ip() -> *mut c_char {
    let ip = crate::config::auto_detect_external_ip();
    CString::new(ip).unwrap().into_raw()
}
```

#### Step 2: Update C Header (`include/mcp_mesh_core.h`)

```c
// Resolve configuration value with priority: ENV > param > default.
// For http_host, auto-detects external IP if no value provided.
//
// # Arguments
// * key_name - Config key (e.g., "http_host", "registry_url")
// * param_value - Optional value from code/config (NULL for none)
//
// # Returns
// Resolved value (caller must free with mesh_free_string)
char *mesh_resolve_config(const char *key_name, const char *param_value);

// Resolve integer configuration value.
//
// # Arguments
// * key_name - Config key (e.g., "http_port", "heartbeat_interval")
// * param_value - Value from code/config (-1 for none)
//
// # Returns
// Resolved value, or -1 if unknown key
int64_t mesh_resolve_config_int(const char *key_name, int64_t param_value);

// Auto-detect external IP address.
//
// # Returns
// IP address string (caller must free with mesh_free_string)
char *mesh_auto_detect_ip(void);
```

#### Step 3: Add JNR-FFI Bindings (`MeshCore.java`)

```java
/**
 * Resolve configuration value with priority: ENV > param > default.
 * For http_host, auto-detects external IP if no value provided.
 *
 * @param keyName Config key (e.g., "http_host", "registry_url", "namespace")
 * @param paramValue Optional value from code/config (may be null)
 * @return Resolved value (caller must free with mesh_free_string)
 */
Pointer mesh_resolve_config(String keyName, String paramValue);

/**
 * Resolve integer configuration value.
 *
 * @param keyName Config key (e.g., "http_port", "heartbeat_interval")
 * @param paramValue Value from code/config (-1 for none)
 * @return Resolved value, or -1 if unknown key
 */
long mesh_resolve_config_int(String keyName, long paramValue);

/**
 * Auto-detect external IP address.
 *
 * @return IP address string (caller must free with mesh_free_string)
 */
Pointer mesh_auto_detect_ip();
```

#### Step 4: Update Java Config Resolution

**New `MeshConfigResolver.java`**:

```java
public class MeshConfigResolver {

    private final MeshCore core;

    public MeshConfigResolver() {
        this.core = MeshCore.load();
    }

    /**
     * Resolve a string configuration value via Rust core.
     * Follows priority: ENV > param > default (with auto-detect for http_host).
     */
    public String resolve(String key, String paramValue) {
        Pointer result = core.mesh_resolve_config(key, paramValue);
        if (result == null) {
            return null;
        }
        try {
            return result.getString(0);
        } finally {
            core.mesh_free_string(result);
        }
    }

    /**
     * Resolve an integer configuration value via Rust core.
     */
    public int resolveInt(String key, int paramValue) {
        long result = core.mesh_resolve_config_int(key, paramValue);
        return (int) result;
    }

    /**
     * Auto-detect external IP address via Rust core.
     */
    public String autoDetectIp() {
        Pointer result = core.mesh_auto_detect_ip();
        if (result == null) {
            return "localhost";
        }
        try {
            return result.getString(0);
        } finally {
            core.mesh_free_string(result);
        }
    }
}
```

**Updated `MeshAutoConfiguration.buildAgentSpec()`**:

```java
private AgentSpec buildAgentSpec(...) {
    AgentSpec spec = new AgentSpec();

    // Delegate to Rust core for all config resolution
    spec.setName(configResolver.resolve("agent_name",
        agentAnnotation != null ? agentAnnotation.name() : null));

    spec.setHttpHost(configResolver.resolve("http_host",
        agentAnnotation != null ? agentAnnotation.host() : null));

    spec.setHttpPort(configResolver.resolveInt("http_port",
        agentAnnotation != null ? agentAnnotation.port() : -1));

    spec.setNamespace(configResolver.resolve("namespace",
        agentAnnotation != null ? agentAnnotation.namespace() : null));

    spec.setRegistryUrl(configResolver.resolve("registry_url", null));

    // ... rest of spec building
}
```

### Config Key Mapping

| Key Name             | ENV Variable               | Auto-Detect             |
| -------------------- | -------------------------- | ----------------------- |
| `http_host`          | `MCP_MESH_HTTP_HOST`       | ✅ External IP          |
| `http_port`          | `MCP_MESH_HTTP_PORT`       | ❌                      |
| `registry_url`       | `MCP_MESH_REGISTRY_URL`    | ❌                      |
| `namespace`          | `MCP_MESH_NAMESPACE`       | ❌ (default: "default") |
| `agent_name`         | `MCP_MESH_AGENT_NAME`      | ❌                      |
| `heartbeat_interval` | `MCP_MESH_HEALTH_INTERVAL` | ❌ (default: 5)         |

---

## Registry: Add "java" Runtime Support

### The Problem

The Go registry's Ent schema only accepts `"python"` and `"typescript"` as valid runtime values. Java agents will be **rejected** during registration.

### Current Schema

**File**: `src/core/ent/schema/agent.go` (lines 28-32)

```go
field.Enum("runtime").
    Values("python", "typescript").  // ❌ No "java"!
    Default("python").
    Optional().
    Comment("SDK runtime: python or typescript"),
```

### Generated Validator

**File**: `src/core/ent/agent/agent.go` (auto-generated)

```go
const (
    RuntimePython     Runtime = "python"
    RuntimeTypescript Runtime = "typescript"
    // ❌ No RuntimeJava constant!
)

func RuntimeValidator(r Runtime) error {
    switch r {
    case RuntimePython, RuntimeTypescript:
        return nil
    default:
        return fmt.Errorf("agent: invalid enum value for runtime field: %q", r)
    }
}
```

### What Happens When Java Agent Registers

1. Java agent sends registration with `"runtime": "java"`
2. Registry handler accepts the HTTP request
3. Ent ORM attempts to save agent to database
4. `RuntimeValidator` is called, rejects "java"
5. **Error**: `agent: invalid enum value for runtime field: "java"`
6. Registration fails

### Solution

**Step 1**: Update OpenAPI spec (`api/mcp-mesh-registry.openapi.yaml`)

Two locations need updating:

**Line ~304** (AgentMetadata):

```yaml
runtime:
  type: string
  enum: [python, typescript, java] # ✅ Add "java"
  default: "python"
  example: "python"
  description: SDK runtime language (python, typescript, or java)
```

**Line ~1160** (AgentInfo):

```yaml
runtime:
  type: string
  enum: [python, typescript, java] # ✅ Add "java"
  example: "python"
  description: SDK runtime language (python, typescript, or java)
```

**Step 2**: Regenerate Go server stubs from OpenAPI

```bash
make generate-go
```

This regenerates `src/core/registry/generated/server.go` with updated types including the new `RuntimeJava` enum value.

**Step 3**: Update Ent schema (`src/core/ent/schema/agent.go`)

```go
field.Enum("runtime").
    Values("python", "typescript", "java").  // ✅ Add "java"
    Default("python").
    Optional().
    Comment("SDK runtime: python, typescript, or java"),
```

**Step 4**: Regenerate Ent ORM code

```bash
make generate-ent
```

This auto-generates:

- `RuntimeJava Runtime = "java"` constant in `src/core/ent/agent/agent.go`
- Updated `RuntimeValidator` accepting "java"

**Step 5**: Rebuild registry

```bash
make build
```

**Or use the combined command:**

```bash
# After updating OpenAPI spec and Ent schema:
make generate && make build
```

---

### Implementation Checklist

- [x] **Registry**: Add "java" to runtime enum in `src/core/ent/schema/agent.go`
- [x] **Registry**: Regenerate Ent code with `go generate ./ent`
- [x] **OpenAPI**: Update runtime enum in `api/mcp-mesh-registry.openapi.yaml` (2 locations)
- [x] **Registry**: Rebuild and test registration
- [x] **Rust Core**: Add `mesh_resolve_config` to `ffi.rs`
- [x] **Rust Core**: Add `mesh_resolve_config_int` to `ffi.rs`
- [x] **Rust Core**: Add `mesh_auto_detect_ip` to `ffi.rs`
- [x] **Rust Core**: Rebuild with `cargo build --features ffi`
- [x] **C Header**: Update `mcp_mesh_core.h` with new function declarations
- [x] **Java Core**: Add function signatures to `MeshCore.java`
- [x] **Java Spring**: Update `MeshConfigResolver` to delegate to Rust
- [x] **Java Spring**: Update `MeshAutoConfiguration.buildAgentSpec()`
- [x] **Test**: Verify agent registers with correct external IP (10.0.0.44)
- [x] **Java Spring**: Add UUID suffix to agent name (matches Python/TypeScript)
- [x] **Java Spring**: Fix heartbeat interval (use Rust core default of 5 seconds)
- [x] **meshctl**: Add Java runtime formatting (magenta color, capitalized "Java")

---

## Next Steps

### Phase 0: Infrastructure Prerequisites (Blocking) ✅ COMPLETE

**Registry Changes:**

1. [x] Add "java" to runtime enum in `src/core/ent/schema/agent.go`
2. [x] Regenerate Ent code: `cd src/core && go generate ./ent`
3. [x] Update OpenAPI spec: `api/mcp-mesh-registry.openapi.yaml` (2 locations)
4. [x] Rebuild registry and verify Java agents can register

**Rust FFI Extension:** 5. [x] Add config resolution functions to C FFI (`ffi.rs`) 6. [x] Update C header (`mcp_mesh_core.h`) 7. [x] Add JNR-FFI bindings to `MeshCore.java` 8. [x] Update `MeshConfigResolver` to delegate to Rust core

### Phase 1: Core Wrapper Infrastructure ✅ COMPLETE

1. [x] Implement `MeshToolWrapper` class with:
   - Dependency injection via `AtomicReferenceArray`
   - Exception unwrapping (`InvocationTargetException`)
   - Async support (`CompletableFuture` handling)
   - Null dependency graceful degradation

2. [x] Implement `MeshToolWrapperRegistry` (simplified version)

3. [x] Implement `McpMeshToolProxyFactory` with caching

### Phase 2: MCP SDK Integration (Partial - SSE working, stateless pending)

4. [ ] **PENDING**: Upgrade to stateless transport (`HttpServletStatelessServerTransport`)
   - Current: Using SSE transport (v0.10.0) - works but session-based
   - Target: Stateless transport (v0.17.2+) - matches Python/meshctl expectations
5. [x] Implement `MeshMcpServerConfiguration` for MCP SDK setup
6. [x] Register wrappers with MCP SDK (`McpServer.addTool`)

### Phase 3: Schema & Type Detection (Needs verification)

7. [x] Update schema generation to filter `McpMeshTool`/`MeshLlmAgent` params
8. [x] Implement type-based detection for injection positions
9. [ ] **VERIFY**: Add `-parameters` compiler flag to pom.xml

### Phase 4: Event Processing (Partial)

10. [x] Update `MeshEventProcessor` for `DEPENDENCY_RESOLVED` events
11. [ ] **PENDING**: Handle `LLM_TOOLS_AVAILABLE` for `MeshLlmAgent` injection
12. [ ] **VERIFY**: Proxy invalidation on topology changes

### Phase 5: Testing

13. [ ] **PENDING**: Unit tests for wrapper invocation
14. [ ] **PENDING**: Integration tests with registry
15. [ ] **PENDING**: Test dependency resolution flow
16. [ ] **PENDING**: Test graceful degradation when deps unavailable

### Dependencies to Add

```xml
<!-- MCP Java SDK - update to latest for stateless transport support -->
<mcp-sdk.version>0.17.2</mcp-sdk.version>

<!-- Core MCP module (includes HttpServletStatelessServerTransport) -->
<dependency>
    <groupId>io.modelcontextprotocol.sdk</groupId>
    <artifactId>mcp</artifactId>
</dependency>

<!-- Optional: Spring WebMvc integration (for WebMvcStatelessServerTransport) -->
<dependency>
    <groupId>io.modelcontextprotocol.sdk</groupId>
    <artifactId>mcp-spring-webmvc</artifactId>
    <optional>true</optional>
</dependency>
```

---

_Document created: 2026-01-30_
_Last updated: 2026-01-30_
_Status: Phase 0-1 COMPLETE, Phase 2-5 partially complete_
_Based on: Python SDK analysis (decorators.py, dependency_injector.py, signature_analyzer.py)_
_Reviewed by: Claude Web (feedback incorporated)_

_Updates:_

- _2026-01-30: Added "MCP Transport Selection" section with stateless transport details_
- _2026-01-30: Updated MCP SDK version requirement to 0.17.2 for stateless support_
- _2026-01-30: Added "Config Resolution" section - Rust FFI must expose config functions for Java_
- _2026-01-30: Added "Registry: Add java Runtime Support" section - Go registry and OpenAPI spec must accept "java" runtime_
- _2026-01-30: **IMPLEMENTED** - Phase 0 complete: Registry accepts "java", Rust FFI config functions, Java bindings_
- _2026-01-30: **IMPLEMENTED** - Phase 1 complete: MeshToolWrapper, MeshToolWrapperRegistry, McpMeshToolProxyFactory_
- _2026-01-30: **IMPLEMENTED** - Agent registers with auto-detected IP (10.0.0.44), UUID suffix, 5s heartbeat_
- _2026-01-30: **IMPLEMENTED** - meshctl shows Java in magenta with capitalized "Java"_
- _2026-01-30: **PENDING** - Stateless transport migration (currently using SSE v0.10.0)_
- _2026-01-30: **PENDING** - MeshLlmAgent injection support_
- _2026-01-30: **PENDING** - Automated tests_
