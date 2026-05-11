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

    `mesh.A2ABearer` accepts either `token_env` (env-var name; resolved per call) or `token` (literal). They are mutually exclusive — supplying both raises `RuntimeError`.

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

Across all three runtimes: literal token and env-var token are mutually exclusive. Set zero or one.

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

The producer side enforces bearer on the JSON-RPC entry route via the `auth=` parameter on `mesh.a2a.mount(...)` (Python). The same token model — env var or literal — applies. Card auth schemes are auto-published in `/.well-known/agent.json` so external scaffolders (mesh's own or third-party A2A tooling) can detect bearer requirements automatically. See [Producer (Python)](producer.md).

## Phase 1 scope and deferred work

| Scheme   | Phase 1 status         |
| -------- | ---------------------- |
| Bearer   | Shipped                |
| OAuth 2  | Future work            |
| mTLS     | Future work            |
| API key  | Future work            |

For non-bearer schemes today the workaround is to handle the auth headers in your own outbound request and bypass `A2AClient` — but that loses the framework injection / lifecycle / caching benefits. Track the A2A consumer arc on GitHub for the auth scheme expansion.

## See also

- [Producer (Python)](producer.md) — producer-side bearer enforcement
- [Scaffolding](scaffolding.md) — card-driven auth wiring
