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
