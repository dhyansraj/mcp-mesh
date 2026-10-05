---
title: Authorization
description: Controlling access to mesh capabilities
---

# Authorization

MCP Mesh provides identity infrastructure (mTLS) and header propagation. Authorization decisions are made at the application layer using the frameworks your team already knows.

## Header Propagation

MCP Mesh propagates HTTP headers end-to-end through the mesh. This enables bearer tokens, OIDC tokens, and custom auth headers to flow from the initial request through all inter-agent calls.

```bash
# Configure headers to propagate
export MCP_MESH_PROPAGATE_HEADERS=authorization,x-request-id,x-tenant-id
```

When Agent A calls Agent B, any headers matching the propagation list are forwarded automatically.

A plain entry is an exact match (`authorization` matches only `authorization`); an entry ending in `*` is a prefix match (`x-audit-*` matches `x-audit-id`). A bare `*` is rejected. Matching is case-insensitive.

### The allowlist is not access control

`MCP_MESH_PROPAGATE_HEADERS` is a capture-and-relay setting scoped to the agent it is set on:

- It decides which inbound headers this agent captures and then sends on every outbound mesh call. It never looks at the destination, so a captured header goes to every dependency the agent calls.
- A callee cannot refuse a header. Leaving `authorization` out of agent B's allowlist means B does not relay it to C; B still receives it on the wire and holds it for the whole call.
- A credential that enters the chain therefore reaches every downstream agent, at every hop whose allowlist relays it.

Trace headers (`X-Trace-ID`, `X-Parent-Span`) travel separately, so withholding business headers does not break tracing.

### Withholding headers from one call

There is no per-dependency setting, and per-call headers can only add. To keep a header away from one downstream, run that call under a reduced propagated set. Remove only the names you mean to withhold: keys are lowercase, and the set also carries mesh infrastructure headers such as `x-mesh-timeout`, which carries the inbound call budget downstream.

=== "Python"

    ```python
    from mesh import TraceContext

    saved = TraceContext.get_propagated_headers()
    TraceContext.set_propagated_headers(
        {k: v for k, v in saved.items() if k != "authorization"}
    )
    try:
        result = await untrusted_svc(query=query)
    finally:
        TraceContext.set_propagated_headers(saved)
    ```

=== "TypeScript"

    ```typescript
    import { getCurrentPropagatedHeaders, runWithPropagatedHeaders } from "@mcpmesh/sdk";

    const { authorization, ...withoutAuth } = getCurrentPropagatedHeaders();
    const result = await runWithPropagatedHeaders(withoutAuth, () =>
      untrustedSvc({ query }),
    );
    ```

=== "Java"

    ```java
    import io.mcpmesh.spring.tracing.TraceContext;

    Map<String, String> saved = TraceContext.getPropagatedHeaders();
    Map<String, String> withoutAuth = new HashMap<>(saved);
    withoutAuth.remove("authorization");
    TraceContext.setPropagatedHeaders(withoutAuth);
    try {
        return untrustedSvc.call(Map.of("query", query));
    } finally {
        TraceContext.setPropagatedHeaders(saved);
    }
    ```

    The set is read on the calling thread when the request is built, so make the withheld call with `call`, inside the `try`.

## Application-Layer Authorization

Use your platform's native auth framework to enforce access control:

=== "Python (FastAPI)"

    ```python
    from fastapi import Depends, HTTPException, Security
    from fastapi.security import HTTPBearer

    security = HTTPBearer()

    @app.post("/api/admin")
    @mesh.route(dependencies=["admin_tool"])
    async def admin_endpoint(
        request: Request,
        admin_tool: mesh.McpMeshTool = None,
        token = Security(security),
    ):
        # Validate token against your OIDC provider
        claims = verify_jwt(token.credentials)
        if "admin" not in claims.get("roles", []):
            raise HTTPException(403, "Insufficient permissions")
        return await admin_tool()
    ```

=== "Java (Spring Security)"

    Controller-level check (the common case):

    ```java
    @RestController
    @RequestMapping("/api")
    public class AdminController {

        @MeshTool(capability = "admin_action",
                  dependencies = @Selector(capability = "audit_log"))
        @PreAuthorize("hasRole('ADMIN')")
        public String adminAction(McpMeshTool<String> auditLog) {
            auditLog.call("action", "admin_operation");
            return "done";
        }
    }
    ```

    Filter-level work (auth side-effects that must run before MVC
    dispatch — first-login user linking, audit emission, principal
    hydration). Declare the capabilities your filter needs with
    `@MeshDependsOn` and inject via `@Qualifier`:

    ```java
    @Component
    @MeshDependsOn({
        @MeshDependency(capability = "resolve_user_principal"),
        @MeshDependency(capability = "audit_log")
    })
    public class AuthFilter extends OncePerRequestFilter {
        private final McpMeshTool<Map<String, Object>> resolveTool;
        private final McpMeshTool<Object> auditTool;

        public AuthFilter(
            @Qualifier("resolve_user_principal") McpMeshTool<Map<String, Object>> resolveTool,
            @Qualifier("audit_log") McpMeshTool<Object> auditTool) {
            this.resolveTool = resolveTool;
            this.auditTool = auditTool;
        }
        // doFilterInternal calls resolveTool.call(...) / auditTool.call(...)
    }
    ```

    The same pattern works for `@Service`, `@Scheduled`, `@Aspect`, and
    any other Spring bean. See
    [`meshctl man dependency-injection --java`](../java/dependency-injection.md)
    for the full `@MeshDependsOn` reference.

=== "TypeScript (Express)"

    ```typescript
    import { authenticateJWT } from "./middleware/auth";

    app.post("/api/admin", authenticateJWT, async (req, res) => {
      if (!req.user.roles.includes("admin")) {
        return res.status(403).json({ error: "Forbidden" });
      }
      // ... use mesh tools
    });
    ```

## What MCP Mesh Provides vs. What You Implement

| Concern            | MCP Mesh                           | Your Application          |
| ------------------ | ---------------------------------- | ------------------------- |
| **Identity**       | mTLS certificates (who is calling) | —                         |
| **Authentication** | Cert chain validation              | OIDC/JWT token validation |
| **Header flow**    | Propagates auth headers end-to-end | Issues/validates tokens   |
| **Authorization**  | —                                  | Access control rules      |
| **Audit trail**    | Distributed tracing for every call | Business audit logging    |

!!! note "Why not built-in authorization?"
Authorization rules are business logic — they vary by organization, compliance regime, and use case. Frameworks like Spring Security, FastAPI middleware, and Express middleware are mature, battle-tested, and already used by your teams. MCP Mesh focuses on the infrastructure layer (identity, routing, mTLS) and lets you own the policy layer.
