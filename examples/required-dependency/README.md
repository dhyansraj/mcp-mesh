# Required Dependency Example (Issue #1249)

A minimal, runnable example of a `required=true` dependency edge, mirrored in
Python and Java. It shows the difference between the default **soft-fail**
behavior (an unresolved dependency injects `None`/`null`) and an edge marked
**required**, where the depending capability is only *available* while its
dependency has a healthy provider.

| Agent             | Capability     | Depends on                       |
|-------------------|----------------|----------------------------------|
| `data-provider`   | `data_service` | —                                |
| `report-consumer` | `report`       | `data_service` (**required**)    |

## What `required=true` does

By default a dependency is optional: if it does not resolve, `None`/`null` is
injected and the agent still starts, registers, and serves. Marking an edge
`required` opts that single edge into strictness:

- The registry computes **capability availability** transitively — `report` is
  *available* only while `data_service` has a healthy provider. When the
  provider goes down, `report` is excluded from resolution exactly like an
  unhealthy provider, and any consumer holding a proxy to it sees the proxy
  flip to `None`/`null` through the normal dependency-update channel (no code
  change, no SDK upgrade required).
- For an HTTP `@mesh.route`/`@MeshRoute` perimeter, a required-but-unavailable
  dependency makes the framework return **503** with
  `{"error": "dependency_unavailable", "capability": "data_service"}` before
  your handler runs.

Optional edges never propagate strictness, so the soft-fail default is
preserved everywhere you do not opt in. See `meshctl man dependency-injection`
for the full availability, route-perimeter, and cycle-rule semantics.

## Declaration syntax

**Python** (`dict`-form dependency):

```python
@mesh.tool(
    capability="report",
    dependencies=[{"capability": "data_service", "required": True}],
)
async def build_report(data_service: mesh.McpMeshTool = None) -> dict: ...
```

**Java** (`@Selector`):

```java
@MeshTool(
    capability = "report",
    dependencies = @Selector(capability = "data_service", required = true)
)
public Map<String, Object> buildReport(McpMeshTool<Map<String, Object>> dataService) { ... }
```

## Run it (Python)

```bash
# Terminal 1 — provider
meshctl start python/data-provider/main.py

# Terminal 2 — consumer
meshctl start python/report-consumer/main.py
```

Call `report` once both are healthy — `data_service` is injected and the report
carries the source data. Now stop `data-provider`: after the missed-heartbeat
debounce the registry marks `report` unavailable and the consumer's injected
`data_service` proxy flips to `None`.

## Run it (Java)

```bash
cd java/data-provider   && mvn spring-boot:run   # port 8090
cd java/report-consumer && mvn spring-boot:run   # port 8091
```

Each agent directory also ships the full scaffolded file set (`Dockerfile`,
`helm-values.yaml`, etc.) for Docker/Kubernetes deployment — see
`meshctl man deployment`.
