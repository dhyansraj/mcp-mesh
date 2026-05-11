# Authentication

A2A v1.0 supports several authentication schemes. Phase 1 of the mesh A2A surface ships **bearer** only on both producer and consumer side. OAuth and mTLS are future work.

## Bearer on the consumer side

Each runtime exposes a small bearer-credential type that resolves the token at call time (so a rotated env-var picks up the new value without re-decorating or restarting the agent).

=== "Python"

    ```python
    import mesh

    @app.tool()
    @mesh.a2a_consumer(
        capability="forecast",
        a2a_url="https://upstream.example.com/agents/forecast",
        a2a_skill_id="forecast-7day",
        auth=mesh.A2ABearer(token_env="UPSTREAM_TOKEN"),
    )
    async def forecast(zip: str, _a2a: mesh.A2AClient = None) -> dict:
        ...
    ```

    `mesh.A2ABearer` requires exactly one of `token_env` (env-var name; resolved per call) or `token` (literal) — supplying both raises `RuntimeError`, and supplying neither also raises. Omit the entire `auth=` argument from `@mesh.a2a_consumer` for upstreams that don't require authentication.

=== "TypeScript"

    ```typescript
    agent.addTool({
      name: "forecast",
      capability: "forecast",
      tags: ["a2a-bridge"],
      a2aConfig: {
        url: "https://upstream.example.com/agents/forecast",
        skillId: "forecast-7day",
        auth: { tokenEnv: "UPSTREAM_TOKEN" },
      },
      parameters: z.object({ zip: z.string() }),
      execute: async ({ zip }, ..._injected) => {
        const a2a = _injected[0] as A2AClient;
        ...
      },
    });
    ```

    `auth` accepts `{ tokenEnv: "..." }` or `{ token: "..." }` (literal). Mutually exclusive.

=== "Java"

    ```java
    @MeshTool(capability = "forecast", tags = {"a2a-bridge"})
    @A2AConsumer(
        url = "https://upstream.example.com/agents/forecast",
        skillId = "forecast-7day",
        authBearerEnv = "UPSTREAM_TOKEN"
    )
    public Map<String, Object> forecast(
            @Param("zip") String zip,
            A2AClient a2a) throws Exception {
        ...
    }
    ```

    `@A2AConsumer` exposes `authBearerEnv()` (env-var name) and `authBearerToken()` (literal). Mutually exclusive — set zero or one, never both. Boot fails with a clear error if both are set.

## Resolution at call time, not decoration time

All three runtimes resolve the env var at header-build time, NOT at decorator / annotation processing. Rotation flow:

1. Set `UPSTREAM_TOKEN=v1` and start the consumer agent.
2. Issue a few calls — the consumer's outbound A2A requests carry `Authorization: Bearer v1`.
3. Update `UPSTREAM_TOKEN=v2` (e.g. via a Kubernetes secret reload, a Vault sidecar, or `export`).
4. Next call — the consumer's outbound request carries `Authorization: Bearer v2`. No restart needed.

If the env var is unset and no literal token was supplied, the consumer raises a clear error at call time (`A2ABearer: no token available ...`) instead of silently sending an unauthenticated request.

## Mutual exclusion

Across all three runtimes: literal token and env-var token are mutually exclusive. If you opt into bearer auth, supply exactly one — never both. To declare a no-auth upstream, omit the auth parameter entirely (`@mesh.a2a_consumer(...)` without `auth=`, `@A2AConsumer` without `authBearerEnv`/`authBearerToken`, `a2aConfig` without `auth`).

| Runtime    | Validation site                                          |
| ---------- | -------------------------------------------------------- |
| Python     | Constructor of `mesh.A2ABearer`                          |
| TypeScript | `addTool` registration validation                        |
| Java       | Spring starter at boot (`A2AConsumerBeanPostProcessor`)  |

Misuse surfaces at startup, not at first call.

## Card-driven auth detection (scaffolding)

When you scaffold a consumer from an upstream card with `meshctl scaffold a2a-consumer --url ...`, the scaffolder reads `card.authentication.schemes` and:

- Wires the bearer auth block into the generated code if bearer is advertised.
- Sets the env-var name to the `--auth-env` flag value (defaults to `A2A_BEARER_TOKEN`).
- Generates a TODO comment in the README directing the operator to `export A2A_BEARER_TOKEN=...` before running the agent.

If the card declares no authentication scheme, no auth block is generated. See [Scaffolding](scaffolding.md).

## Producer-side bearer

On the producer side, all three runtimes accept the literal string `"bearer"` — Python `mesh.a2a.mount(..., auth="bearer")`, Java `@MeshA2A(auth = "bearer")`, TypeScript `mesh.a2a.mount(app, { auth: "bearer", ... })`. This advertises the bearer scheme on the published agent card and gates the JSON-RPC entry route — incoming requests must carry an `Authorization: Bearer ...` header to pass the gate. Phase 1 does NOT validate the token value itself: the producer-side `auth` parameter takes only the string `"bearer"` (or unset for no auth), and downstream verification of the token is left to the user (e.g., a FastAPI dependency, a Spring Security filter, an Express middleware, a sidecar, or the broader auth stack). The full token-resolution model — `token` literal vs `token_env` — lives on the **consumer** side via `mesh.A2ABearer` / `@A2AConsumer(authBearerEnv = ...)` / `a2aConfig.auth`. Card auth schemes are auto-published in `/.well-known/agent.json` so external scaffolders (mesh's own or third-party A2A tooling) can detect bearer requirements automatically. Token-value validation on the producer side is deferred to a future phase. See [Producer](producer.md).

## Phase 1 scope and deferred work

| Scheme   | Phase 1 status         |
| -------- | ---------------------- |
| Bearer   | Shipped                |
| OAuth 2  | Future work            |
| mTLS     | Future work            |
| API key  | Future work            |

For non-bearer schemes today the workaround is to handle the auth headers in your own outbound request and bypass `A2AClient` — but that loses the framework injection / lifecycle / caching benefits. Track the A2A consumer arc on GitHub for the auth scheme expansion.

## See also

- [Producer](producer.md) — producer-side bearer enforcement
- [Scaffolding](scaffolding.md) — card-driven auth wiring
