# A2A Examples Gallery

Every A2A-related example in the repo, grouped by runtime, with the scenario each one demonstrates.

## Producer (Python)

| Example                                  | Scenario                                                |
| ---------------------------------------- | ------------------------------------------------------- |
| `examples/a2a/date_a2a_agent.py`         | Sync handler — bridges the `date_service` mesh capability via A2A `tasks/send` |
| `examples/a2a/report_a2a_agent.py`       | Long-running + SSE handler — bridges `generate_report` (`task=True`) via A2A `tasks/send` / `tasks/get` / `tasks/cancel` / `tasks/sendSubscribe` / `tasks/resubscribe` |

## Consumer — Python

| Example                                       | Scenario                                                |
| --------------------------------------------- | ------------------------------------------------------- |
| `examples/a2a/consumer_date_agent.py`         | Sync bridge — re-publishes upstream `get-date` as the mesh `current-date` capability |
| `examples/a2a/consumer_report_agent.py`       | Long-running poll bridge — `_a2a.submit(...)` + `a2a_job.bridge(job)` |
| `examples/a2a/consumer_report_agent_sse.py`   | SSE bridge — `_a2a.subscribe(...)` + `stream.bridge(job)` |

## Consumer — TypeScript

| Example                                                  | Scenario                                       |
| -------------------------------------------------------- | ---------------------------------------------- |
| `examples/typescript/consumer-date-agent/`               | Sync bridge — `addTool({ a2aConfig, ... })` with framework-injected `A2AClient` |
| `examples/typescript/consumer-report-agent/`             | Long-running poll bridge — `task: true` + `a2aJob.bridge(job)` |
| `examples/typescript/consumer-report-agent-sse/`         | SSE bridge — `a2a.subscribe(...)` + `stream.bridge(job)` |

## Consumer — Java

| Example                                                  | Scenario                                       |
| -------------------------------------------------------- | ---------------------------------------------- |
| `examples/java/consumer-date-agent/`                     | Sync bridge — `@A2AConsumer` annotation, Spring-injected `A2AClient` |
| `examples/java/consumer-report-agent/`                   | Long-running poll bridge — `@MeshTool(task = true)` + `a2aJob.bridge((JobController) job)` |
| `examples/java/consumer-report-agent-sse/`               | SSE bridge — try-with-resources `A2AStream` + `stream.bridge((JobController) job)` |

## Cross-runtime polyglot validation

The integration test suites under `tests/integration/` exercise mesh's auto-tag failover across runtimes — by registering the same logical capability from a Python consumer AND a Java consumer (or TS), then having a downstream caller depend on the capability with no tag pin and observing that calls succeed regardless of which consumer is up:

| Suite                                          | What it proves                                                |
| ---------------------------------------------- | ------------------------------------------------------------- |
| `tests/integration/suites/uc25_a2a_consumer_python/` | Python consumer end-to-end: sync, long-running poll, SSE bridges, plus consumer-death failover (tc07) |
| `tests/integration/suites/uc26_a2a_consumer_typescript/` | TypeScript consumer parity with uc25 — same scenarios, same producer |
| `tests/integration/suites/uc27_a2a_consumer_java/`     | Java consumer parity with uc25 — same scenarios, Spring runtime |
| Polyglot smoke (`tc08` patterns)               | Two consumers in different runtimes registering the same capability, downstream caller resolves either; failover transparently rewires when one is killed |

Source layout: each suite has `routines.yaml` (shared bring-up steps) + per-test `test.yaml` files specifying which agents to run.

## Run the simplest case end-to-end

The `consumer_date_agent.py` example end-to-end (4 terminals):

```bash
# 1) Registry
meshctl start --registry-only

# 2) System agent — provides date_service (the underlying capability)
python examples/simple/system_agent.py

# 3) A2A producer — re-publishes date_service via A2A
python examples/a2a/date_a2a_agent.py

# 4) Consumer — bridges the A2A get-date back into the mesh
python examples/a2a/consumer_date_agent.py
```

Then call the bridged capability via `meshctl`:

```bash
meshctl call current_date '{}'
# Returns: {"date": "2026-05-09T..."}
```

Use `meshctl call <tool-name>` to invoke any registered capability — the registry resolves to the right consumer. The `agent:tool` form works too but requires the agent's full UID-suffixed ID (e.g., `date-consumer-7f3a2b:current_date`); the bare-name form is simpler when you just want to hit the capability.

Or chain it from a downstream caller (a separate mesh agent depending on `current-date` with the `date-consumer` tag).

## See also

- [Overview](overview.md)
- [Producer (Python)](producer.md)
- [Consumer Quick Start](consumer-quickstart.md)
- [Failover & Federation](failover.md)
- [Long-Running & SSE](long-running.md)
- [Authentication](authentication.md)
- [Scaffolding](scaffolding.md)
- [Architecture & Decisions](architecture.md)
