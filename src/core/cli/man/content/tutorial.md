# The TripPlanner Tutorial

> The TripPlanner Tutorial -- 10 days from scaffold to Kubernetes.
> Build a 13-agent trip-planning application, from a single tool agent
> to a Kubernetes-deployed system with LLM planning, specialist committees,
> chat history, and distributed tracing.

## Overview

MCP Mesh has a lot of surface area -- decorators, dependency injection,
capability-based discovery, LLM provider abstraction, tag routing, structured
outputs, and thirty-odd more concepts beyond those. Reading about each one in
isolation will only take you so far. At some point you need to see how they
compose inside a real application, the kind of multi-user, cloud-deployable
system that an enterprise-grade agent framework was built to support.

That's what this tutorial is. Over ten chapters you'll build **TripPlanner**, a
multi-agent trip-planning application that is decidedly not a chatbot demo or a
"hello, world." It has tool agents for domain logic, LLM-driven planning, a
committee of specialists that refine results, a chat API for end users, and a
full deployment to Kubernetes with observability baked in. You'll start on Day 1
with a single agent running locally, and by Day 10 every one of those pieces will
be live -- built by you, understood by you.

## What you'll have built by Day 10

By the end of the tutorial, TripPlanner consists of:

- **Five tool agents** -- flight search, hotel search, weather forecast, points of
  interest, and user preferences. Each runs as a standalone mesh agent and exposes
  one or more tools.
- **An LLM planner** -- an `@mesh.llm` agent driven by Jinja prompt templates. It
  uses the tool agents as dependencies and orchestrates an end-to-end trip plan.
- **Multiple LLM providers** -- Claude, GPT, and Gemini running simultaneously,
  with preference-based routing and automatic failover if one goes down.
- **A committee of three specialists** -- flight specialist, hotel specialist, and
  itinerary specialist -- each an `@mesh.llm` agent, coordinated to refine the plan.
- **A FastAPI chat gateway** -- a stateless HTTP endpoint that accepts user messages
  and returns planner responses.
- **A cross-language gateway swap** -- a demonstration of replacing the FastAPI
  gateway with a Spring Boot gateway mid-tutorial. Same agents, same mesh,
  different language, everything works.
- **Redis-backed chat history** -- persistent, resumable conversations indexed by
  user and session.
- **Kubernetes deployment via Helm** -- the same agents running on a real cluster,
  with the registry as a service and agents as deployments.
- **An observability stack** -- Tempo for traces, Grafana dashboards, metrics on
  tool call latency, queue depth, and error rates.

[Diagram: The Day 10 architecture -- User -> Gateway -> Planner -> Committee (Flight/Hotel/Itinerary Specialists) -> Tool agents, with Observability (Tempo, Grafana) connected via traces]

Everything in that diagram runs on Kubernetes in the final chapter. The agents
themselves are plain Python functions -- no k8s-specific code, no sidecars, no
framework-specific wiring.

## The arc

The tutorial is ten chapters long, split into two parts.

**Part 1 -- Build and run (Days 1-5)** starts from nothing and ends with a working
TripPlanner running locally. You scaffold your first agent, learn how dependency
injection works between tools, introduce tag-based routing, plug in an LLM with
prompt templates, put a FastAPI gateway in front of it all, and then swap that
gateway for Spring Boot to see cross-language interop in action.

**Part 2 -- Grow and scale (Days 6-10)** takes the working system and grows it into
something production-shaped. You add a committee of specialists to refine plans,
wire Redis into the chat for persistent history, instrument everything with traces
and metrics, deploy to Kubernetes via Helm, and finish with production hardening.

> All ten chapters are available. Days 1-10 are complete. Work through them at
> your own pace -- each chapter builds on the previous one, from a single tool
> agent to a 13-agent system running on Kubernetes.

> This tutorial uses Python throughout. The patterns and concepts apply equally
> to TypeScript and Java -- see the TypeScript SDK and Java SDK documentation
> for language-specific syntax.

## Prerequisites

Before starting Day 1, you'll need Python 3.11+, `meshctl` on your `PATH`, and a few
minutes to set up a virtual environment. See the Prerequisites section below
for platform-specific install instructions.

## Things worth noticing along the way

As you work through the tutorial, keep an eye out for a few things:

- **One codebase, every environment.** The agent you write on Day 1 runs locally,
  in Docker, and on Kubernetes without any configuration changes.
- **mesh runs in-process.** There are no sidecars or proxy containers to manage --
  your agent code is all you need to deploy.
- **Distributed calls feel like local function calls.** Declare your dependencies,
  then call them -- mesh injects the real implementations at runtime, whether they
  live in the same process or across the network. No REST clients, no MCP wiring,
  no response parsing. Your code reads like a plain Python script, which is why
  a complex multi-agent application can go from zero to running in half a day.
- **Day 1 code is Day 9 code.** The function you write in the first tutorial is the
  same function that runs on Kubernetes later. Same file, same decorators, same types.
- **Switching LLM providers is zero code changes.** Your agent declares a
  dependency on the `llm` capability -- no vendor SDK, no provider-specific code.
  Swap Claude for GPT by bringing up a different provider agent; mesh abstracts
  away the API differences and your consumer auto-switches. With preference tags
  like `+claude`, you also get automatic failover -- if Claude goes down, traffic
  routes to the next available provider with no downtime. Day 4 shows this in
  practice.

## Tutorial contents

| Day | Topic | Key concept |
|-----|-------|-------------|
| 1 | Scaffold and first tool agent | `meshctl scaffold`, `@mesh.tool` |
| 2 | More tools and dependency injection | DI, capabilities |
| 3 | Observability and LLM integration | `@mesh.llm`, tracing |
| 4 | Multiple providers and dependency tiers | Tag routing, failover |
| 5 | HTTP gateway | `@mesh.route`, REST API |
| 6 | Chat history | Redis, sessions |
| 7 | Committee of specialists | Structured outputs, fan-out |
| 8 | Docker Compose | Containerized deployment |
| 9 | Kubernetes | Helm charts, production |
| 10 | What you built and where to go | Production readiness |

---

# Prerequisites

What you need before starting Day 1 of the TripPlanner tutorial.

## Supported platforms

- macOS (Intel or Apple Silicon)
- Linux (x86_64 or ARM64)
- Windows via WSL2

## meshctl

`meshctl` is the command-line tool you'll use to start, inspect, and call agents.

```bash
npm install -g @mcpmesh/cli
```

### Verify

```bash
meshctl --version
```

## Language runtime

### Python 3.11 or later

```bash
# Check your version
python3 --version

# Install if needed
brew install python@3.11          # macOS (Homebrew)
sudo apt install python3.11       # Ubuntu/Debian
```

### Virtual environment

Create a `.venv` in your project root and install `mcp-mesh` into it. `meshctl`
auto-detects `.venv` when starting an agent -- you only need to activate it when
running `pip`.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install mcp-mesh
deactivate
```

### Verify

```bash
.venv/bin/python -c "import mesh; print('mesh OK')"
```

> This tutorial uses Python. For TypeScript or Java setup, see the TypeScript
> prerequisites and Java prerequisites documentation.

## Ready to start

Once `meshctl --version` prints a version and `.venv/bin/python -c "import mesh"`
succeeds, you're ready for Day 1.

---

# Day 1 -- Scaffold and First Tool Agent

Today you'll scaffold your first tool agent, run it locally, and call it from your
terminal. By the end you'll have used every core `meshctl` command. No LLMs yet --
just the basics: build, start, inspect, call.

## What we're building today

[Diagram: flight-agent registers with Registry, you discover and call it via meshctl]

A local registry and one agent. The agent registers with the registry so it can
be discovered. When you run `meshctl call`, it looks up the agent's endpoint via
the registry and then calls the agent directly. The agent exposes a single tool,
`flight_search`, that takes an origin, destination, and date and returns stub
flight data. That's the complete Day 1 mesh.

## Step 1: Scaffold the agent

`meshctl scaffold` generates a ready-to-run agent from a built-in template. For
a basic Python tool agent, the flags you need are `--name`, `--agent-type tool`,
and `--lang python` (which is the default, so you can omit it).

```shell
$ meshctl scaffold --name flight-agent --agent-type tool --port 9101

Created agent 'flight-agent' in flight-agent/

Generated files:
  flight-agent/
  |-- .dockerignore
  |-- Dockerfile
  |-- README.md
  |-- __init__.py
  |-- __main__.py
  |-- helm-values.yaml
  |-- main.py
  |-- requirements.txt

Next steps:
  meshctl start flight-agent/main.py

For Docker/K8s deployment, see: meshctl man deployment
```

Everything mesh needs is in `flight-agent/main.py`. The scaffold also generates
Docker and Helm files -- you won't need them today, but they'll come in handy on
Day 8 (Docker) and Day 9 (Kubernetes). The scaffold gives you a starting function
named `hello` -- you're going to replace it with `flight_search`.

## Step 2: Write the tool

A mesh tool is a plain Python function with two decorators: `@app.tool()` from
FastMCP (which exposes it as an MCP tool) and `@mesh.tool(...)` from MCP Mesh
(which registers it with the mesh and handles dependency injection).

[Note: See the tutorial source files in examples/tutorial/trip-planner/day-01/ for full code listings]

Three parameters, a list of dicts back. The `capability` on `@mesh.tool` is how
other agents will look this tool up once there are other agents -- you'll see that
on Day 2. The `tags` are how the registry narrows matches when multiple agents
advertise the same capability.

The `@mesh.agent` class at the bottom is what mesh uses to run the FastMCP server
and register the agent with the registry. `auto_run=True` means you don't need a
`main()` -- mesh starts the server when the module is imported by `meshctl start`.

> **meshctl DX: prerequisite detection** -- Before `meshctl start` actually runs
> anything, it checks that the language runtime and required packages are present.
> If something's missing, it prints the exact commands you need to fix it and then
> exits -- it won't half-start a broken agent.

## Step 3: Start the agent

With a `.venv` in place and `mcp-mesh` installed, start the agent in detached mode.
If no registry is running, `meshctl` starts one automatically on port 8000.

```shell
$ meshctl start flight-agent/main.py -d
Validating prerequisites...
  Using virtual environment: /tmp/trip-planner-day1/.venv/bin/python
  All prerequisites validated successfully
   Python: 3.11.14 (/tmp/trip-planner-day1/.venv/bin/python)
   Virtual environment: .venv
Started 'flight-agent' in detach
Logs: ~/.mcp-mesh/logs/flight-agent.log
Use 'meshctl logs flight-agent' to view or 'meshctl stop flight-agent' to stop
```

`meshctl` auto-detected the `.venv` and started the agent in detached mode. The
registry was started automatically -- no separate command needed. Logs are stored
at `~/.mcp-mesh/logs/flight-agent.log` and viewable with `meshctl logs flight-agent`.

## Step 4: Start the UI

meshctl ships a web dashboard for inspecting agents, tools, and traces. Start it
alongside your agent:

```shell
$ meshctl start --ui -d
Started in detach
Use 'meshctl logs <agent>' to view logs or 'meshctl stop' to stop
```

The dashboard is available at http://localhost:3080. Open
it in your browser and you'll see flight-agent listed with its status and
capabilities.

[Image: Mesh UI showing flight-agent on the Topology page]

## Step 5: Inspect the mesh

`meshctl list` shows you what's running:

```shell
$ meshctl list
Registry: running (http://localhost:8000) - 1 healthy

NAME                    RUNTIME        TYPE    STATUS       DEPS     ENDPOINT                AGE      LAST SEEN
--------------------------------------------------------------------------------------------------------------------------
flight-agent-ba2b3bc8   Python         Agent   healthy      0/0      10.0.0.74:9101          53s      3s
```

The agent registers as `flight-agent-ba2b3bc8` -- mesh appends a short hash to
ensure uniqueness when multiple instances of the same agent run. All meshctl
commands accept the prefix `flight-agent` for convenience, so you never need to
type the hash.

The `DEPS` column is `0/0` because `flight-agent` doesn't depend on any other
agent. When you add hotel and weather agents on Day 2, this column will show
resolved-over-declared dependencies and turn green when all dependencies are
satisfied.

`meshctl list --tools` shows every tool registered across all agents:

```shell
$ meshctl list --tools
TOOL                      AGENT                   CAPABILITY           TAGS
----------------------------------------------------------------------------------------
flight_search             flight-agent-ba2b3bc8   flight_search        flights,travel

1 tool(s) found
```

And `meshctl status flight-agent` gives you a detailed breakdown -- capabilities,
endpoint, version, uptime:

```shell
$ meshctl status flight-agent
Agent Details: flight-agent-ba2b3bc8
================================================================================
Name                : flight-agent-ba2b3bc8
Type                : Agent
Runtime             : Python
Status              : healthy
Endpoint            : http://10.0.0.74:9101
Version             : 1.0.0
Dependencies        : 0/0
Last Seen           : 2026-04-12 05:29:01 (3s ago)
Created             : 2026-04-12 01:28:06

Capabilities (1):
--------------------------------------------------------------------------------
CAPABILITY                MCP TOOL                       VERSION    TAGS
--------------------------------------------------------------------------------
flight_search             flight_search                  1.0.0      flights,travel
```

## Step 6: Call the tool

`meshctl call` discovers the agent via the registry and sends an MCP JSON-RPC
`tools/call` to it. You pass the tool name and a JSON object with the arguments:

```shell
$ meshctl call flight_search '{"origin":"SFO","destination":"NRT","date":"2026-06-01"}'
```

```json
{
  "structuredContent": {
    "result": [
      {
        "carrier": "MH",
        "flight": "MH007",
        "origin": "SFO",
        "destination": "NRT",
        "date": "2026-06-01",
        "depart": "09:15",
        "arrive": "14:40",
        "price_usd": 842
      },
      {
        "carrier": "SQ",
        "flight": "SQ017",
        "origin": "SFO",
        "destination": "NRT",
        "date": "2026-06-01",
        "depart": "11:50",
        "arrive": "17:05",
        "price_usd": 901
      }
    ]
  },
  "isError": false
}
```

The response is a standard MCP tool result envelope. The flight data you care
about is under `structuredContent.result`. When other agents call this tool via
dependency injection, mesh parses `structuredContent` automatically -- they
receive the Python list directly.

meshctl call discovers the agent's endpoint via the registry and calls it. By
default it proxies through the registry for convenience -- this is especially
useful in Kubernetes where you only need to port-forward the registry.

## Stop and clean up

One command stops the registry, the agent, and any other background processes
`meshctl` is tracking:

```shell
$ meshctl stop
Stopping 1 agent(s) in parallel...
Stopping agent 'flight-agent' (PID: 14560)...
Agent 'flight-agent' stopped
Stopping UI server (PID: 15245)...
UI server stopped
Stopping registry (PID: 14555)...
Registry stopped

Stopped 3 process(es)
```

## Troubleshooting

**Agent name has a hash suffix.** Your agent registers as
`flight-agent-XXXXXXXX` (name plus a random hash). This ensures uniqueness when
you run multiple instances. All meshctl commands accept just the prefix
(`flight-agent`) -- you never need to type the hash.

**Warning about McpMeshTool parameters in logs.** If you check
`meshctl logs flight-agent`, you may see a warning about function parameters.
This is harmless -- it means your tool has no mesh dependencies to inject, which
is expected on Day 1. The warning disappears once you add dependencies on Day 2.

**meshctl stop reports a failed UI process.** If `meshctl stop` reports
`Failed to stop UI server`, it usually means a previous UI process is still
running. Run `ps aux | grep meshui` to find it and `kill <PID>` to clean it up.

**Port 8000 already in use.** If `meshctl start` fails because port 8000 is
taken, another service (or a previous registry) is using it. Stop the other
service, or set a different port with
`MCP_MESH_REGISTRY_PORT=9000 meshctl start ...`.

## Recap

You built, started, inspected, and called an agent using six `meshctl` commands
and a dozen lines of Python. The `flight_search` function you wrote today is the
same function that will run on Kubernetes on Day 9 -- same file, same decorators,
same types, no wrapper code or deployment-specific edits. That's DDDI: the agent
doesn't know or care where it's running, and you get dev-to-production with
nothing in between.

## See also

- `meshctl man scaffold` -- the full scaffold CLI reference
- `meshctl man decorators` -- the `@mesh.tool`, `@mesh.agent`, `@mesh.llm`, and
  `@mesh.llm_provider` reference
- `meshctl man quickstart` -- a condensed version of this tutorial
- `meshctl man cli` -- full CLI reference for `start`, `list`, `call`, `status`, `stop`

---

# Day 2 -- More Tools and Dependency Injection

Yesterday you built one agent. Today you'll build four more, connect them via
dependency injection, and see mesh resolve dependencies at runtime. By the end
you'll have five agents working together -- and you won't have written a single
line of networking code.

## What we're building today

[Diagram: flight-agent depends on user-prefs-agent, poi-agent depends on weather-agent, hotel-agent standalone]

Five agents. Two dependency arrows. `flight-agent` calls `user-prefs-agent` to
personalize results. `poi-agent` calls `weather-agent` to recommend indoor or
outdoor activities. The other three -- `hotel-agent`, `weather-agent`, and
`user-prefs-agent` -- are standalone tools with no dependencies.

## Step 1: Scaffold the new agents

You know `meshctl scaffold` from Day 1. Scaffold four new agents:

```shell
$ meshctl scaffold --name hotel-agent --agent-type tool --port 9102
$ meshctl scaffold --name weather-agent --agent-type tool --port 9103
$ meshctl scaffold --name poi-agent --agent-type tool --port 9104
$ meshctl scaffold --name user-prefs-agent --agent-type tool --port 9105
```

Each command creates the same set of files you saw on Day 1: `main.py`,
`Dockerfile`, `helm-values.yaml`, and the rest. You'll replace the generated
`main.py` in each directory with the tool implementations below.

## Step 2: Write the tools

### Standalone tools: hotel, weather, user-prefs

These three agents have no dependencies. Each registers a single tool with the
mesh.

[Note: See the tutorial source files in examples/tutorial/trip-planner/day-02/ for full code listings]

All three follow the same pattern from Day 1: `@app.tool()` + `@mesh.tool()`
with a `capability` name and `tags`. No dependencies, no injected parameters.

### DI tools: flight-agent (updated) and poi-agent (new)

These two agents depend on other agents' capabilities. This is where dependency
injection comes in.

Three things changed from Day 1:

1. **`dependencies=["user_preferences"]`** on `@mesh.tool` declares that this
   tool needs the `user_preferences` capability at runtime.
2. **`user_prefs: mesh.McpMeshTool = None`** is the injected parameter. At
   startup, mesh resolves the dependency by finding an agent that advertises
   `user_preferences`, creates a proxy, and injects it here.
3. **`await user_prefs(user_id="demo-user")`** calls the injected tool like a
   regular async function. No URL, no REST client, no serialization code -- mesh
   handles all of that behind the proxy.

The function also changed from `def` to `async def` -- dependency injection
calls are async because they cross process boundaries.

## Step 3: Start all agents

Start all five with one command:

```shell
$ meshctl start --debug -d -w flight-agent/main.py hotel-agent/main.py weather-agent/main.py poi-agent/main.py user-prefs-agent/main.py
```

The `-w` flag means mesh is watching your agent files -- edit any `main.py`, save
it, and mesh restarts that agent automatically. Combined with `-d` (detach) and
`--debug` (verbose logs), this gives you a tight development loop: edit, save,
call, see results.

Here's what each flag does:

- **`--debug`** -- verbose logging. Useful for seeing dependency resolution.
- **`-d`** -- detach mode. All five agents run in the background.
- **`-w`** -- watch mode. Monitors agent directories and auto-restarts on changes.

If no registry is running, `meshctl` starts one automatically, same as Day 1.

## Step 4: Start the UI

```shell
$ meshctl start --ui -d
```

The dashboard is at http://localhost:3080. You'll see all five agents listed.

[Image: Mesh UI Topology showing five agents with dependency edges]

## Step 5: Inspect the mesh

```shell
$ meshctl list
Registry: running (http://localhost:8000) - 5 healthy

NAME                        RUNTIME   TYPE    STATUS    DEPS   ENDPOINT           AGE   LAST SEEN
flight-agent-835864a0       Python    Agent   healthy   1/1    10.0.0.74:63297    5s    5s
hotel-agent-eb0eb637        Python    Agent   healthy   0/0    10.0.0.74:63298    5s    5s
poi-agent-5923d848          Python    Agent   healthy   1/1    10.0.0.74:63295    5s    5s
user-prefs-agent-950b70c3   Python    Agent   healthy   0/0    10.0.0.74:63294    5s    5s
weather-agent-1760466a      Python    Agent   healthy   0/0    10.0.0.74:63296    5s    5s
```

Notice the `DEPS` column. `flight-agent` shows `1/1` -- one dependency declared,
one resolved. `poi-agent` also shows `1/1`. The others show `0/0`. When all
dependencies are resolved, the agent is fully operational.

```shell
$ meshctl list --tools
TOOL              AGENT                       CAPABILITY         TAGS
flight_search     flight-agent-835864a0       flight_search      flights,travel
get_user_prefs    user-prefs-agent-950b70c3   user_preferences   preferences,travel
get_weather       weather-agent-1760466a      weather_forecast   weather,travel
hotel_search      hotel-agent-eb0eb637        hotel_search       hotels,travel
search_pois       poi-agent-5923d848          poi_search         poi,travel

5 tool(s) found
```

Five tools across five agents. Each tool's capability name is how other agents
find it via dependency injection.

## Step 6: Call a tool with dependency injection

Call `flight_search`. This triggers a cross-agent call -- `flight-agent` calls
`user-prefs-agent` behind the scenes to fetch user preferences:

```shell
$ meshctl call flight_search '{"origin":"SFO","destination":"NRT","date":"2026-06-01"}'
```

The response includes personalized results. The stub preferences set a budget of
$1000 and prefer SQ and MH airlines, so the $1150 AA flight is filtered out, and
the preferred carriers sort first.

Now call `search_pois`. This triggers `poi-agent` calling `weather-agent`:

```shell
$ meshctl call search_pois '{"location":"Tokyo"}'
```

The 30% rain chance is below the 50% threshold, so `poi-agent` recommends
outdoor activities. Change the stub data in `weather-agent` to return 80% rain
chance, save the file (watch mode restarts it automatically), and call again --
you'll get indoor recommendations instead.

> **What is DDDI?** Your `flight_search` function calls `user_prefs()` like a
> local function. It has no idea that `user_prefs` lives in a different process,
> possibly on a different machine. mesh resolved the dependency by matching the
> `user_preferences` capability name, injected a proxy that handles the network
> call, and your code stayed clean. That's Distributed Dynamic Dependency
> Injection -- DDDI.

## Stop and clean up

```shell
$ meshctl stop
```

On Day 3 you'll restart with distributed tracing enabled.

## Troubleshooting

**"Dependency not resolved" -- agent shows 0/1 in DEPS column.** This means the
agent that provides the required capability hasn't registered yet. mesh doesn't
crash -- the dependent agent starts and waits.

**DI call returns empty dict instead of preferences.** Check that `user_prefs`
is not `None`. The `if user_prefs else {}` guard in the function handles the
case where the dependency wasn't resolved.

**Watch mode doesn't pick up changes.** Verify that the file you edited is in
the same directory that `meshctl start` is watching.

**Agent ports change on every restart.** When using `-w` (watch mode), meshctl
starts agents with the HTTP port set to `0` -- the OS assigns a random available
port. This is intentional: mesh discovers agents by capability name through the
registry (not by URL), so the actual port number doesn't matter.

## Recap

You built five agents, connected two of them via dependency injection, and called
tools that trigger cross-agent calls. The total networking code you wrote: zero
lines. The dependency injection, service discovery, and proxy creation all
happened at runtime -- declared in decorators, resolved by mesh.

## See also

- `meshctl man dependency-injection` -- the full DI reference
- `meshctl man capabilities` -- how capabilities and tags work together
- `meshctl man cli` -- full CLI reference

---

# Day 3 -- Observability and LLM Integration

On Day 2 you built five tool agents with dependency injection. Today you'll
restart them with distributed tracing enabled, add an LLM provider, and build
your first agent that can reason -- a trip planner that generates itineraries
from natural language.

## What we're building today

[Diagram: Five tool agents plus claude-provider and planner-agent]

Seven agents. The five you already know plus two new ones: `claude-provider`
wraps the Claude API as a mesh capability, and `planner-agent` consumes that
capability to generate trip itineraries. The planner connects to the provider
through the same capability-based discovery that `flight-agent` uses to find
`user-prefs-agent`.

Today has five parts:

1. **Set up distributed tracing** -- Redis, Tempo, Grafana via Docker Compose
2. **Register an LLM provider** -- wrap Claude as a mesh capability
3. **Build the planner agent** -- consume the LLM via prompt templates
4. **Call the planner** -- generate a Kyoto itinerary
5. **Walk the trace** -- see the full call tree across agents

## Part 1: Set up distributed tracing

Mesh agents publish trace events to Redis. The registry consumes those events
and exports them to Tempo. You view traces with `meshctl trace` or in Grafana.
Before any of that works, you need the observability stack running.

### Generate the compose file

```shell
$ meshctl scaffold --observability
```

This generates a `docker-compose.observability.yml` with Redis, Tempo, and Grafana.

### Start the stack

```shell
$ docker compose -f docker-compose.observability.yml up -d
```

Three containers. Redis collects trace events on port 6379, Tempo stores traces
on ports 3200 (HTTP) and 4317 (OTLP gRPC), and Grafana serves dashboards on
port 3000.

## Part 2: Register an LLM provider

> **API key required** -- The LLM provider needs an `ANTHROPIC_API_KEY`
> environment variable. Export it: `export ANTHROPIC_API_KEY=sk-ant-...`

An LLM provider wraps an external LLM API -- Claude, GPT, Gemini -- as a mesh
capability. The provider agent is zero-code: the `@mesh.llm_provider` decorator
handles the LiteLLM integration, request parsing, and response formatting.

### Scaffold the provider

```shell
$ meshctl scaffold --name claude-provider --agent-type llm-provider --model anthropic/claude-sonnet-4-5 --port 9106
```

[Note: See the tutorial source files in examples/tutorial/trip-planner/day-03/ for full code listings]

The decorator does all the work:

- **`model="anthropic/claude-sonnet-4-5"`** -- the LiteLLM model identifier.
- **`capability="llm"`** -- the capability name other agents use to discover
  this provider.
- **`tags=["claude"]`** -- tags for filtering.

The function body is `pass` -- the decorator generates the full implementation.

### Start the provider with all Day 2 agents

```shell
$ meshctl start --dte --debug -d -w flight-agent/main.py hotel-agent/main.py weather-agent/main.py poi-agent/main.py user-prefs-agent/main.py claude-provider/main.py
```

Six agents running. The `--dte` flag enables distributed tracing for all of them.

## Part 3: Build the planner agent

The planner agent uses `@mesh.llm` to consume an LLM capability from the mesh.
It takes a destination, dates, and budget, feeds them into a Jinja prompt
template, and returns an LLM-generated itinerary.

### The prompt template

Create `planner-agent/prompts/plan_trip.j2` with the template variables
`{{ destination }}`, `{{ dates }}`, `{{ budget }}` -- populated from the context
model at call time.

### The planner code

```shell
$ meshctl scaffold --name planner-agent --agent-type llm-agent --port 9107
```

Three things to note:

1. **`TripRequest(MeshContextModel)`** defines the context fields that map to
   template variables. Each field becomes a tool parameter and a template
   variable.
2. **`system_prompt="file://prompts/plan_trip.j2"`** loads the Jinja template
   from disk.
3. **`provider={"capability": "llm"}`** tells mesh to find any agent that
   advertises the `llm` capability.

### Start the planner

```shell
$ meshctl start --dte --debug -d -w planner-agent/main.py
```

Seven agents running.

## Part 4: Call the planner

```shell
$ meshctl call plan_trip '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$2000"}' --trace
```

The response is an LLM-generated itinerary with a trace ID for inspection.

## Part 5: Walk the trace

```shell
$ meshctl trace <trace-id>
```

```
Call Tree for trace 2bb20ffe16ff3e03ff356aada9d11947

  plan_trip (planner-agent) [21835ms]
    claude_provider (claude-provider) [21812ms]

Summary: 3 spans across 2 agents | 21.84s
```

The trace tree shows the planner delegated to Claude. The total time is
almost entirely Claude's inference time. The mesh overhead is in the low
milliseconds.

> **Trace propagation** -- Trace context propagates automatically across mesh
> calls. You don't need to pass trace IDs manually.

> **LLM provider abstraction** -- The planner declares a dependency on the
> `llm` capability -- it has no idea it's talking to Claude. On Day 4 you'll
> add GPT and swap between them by changing a tag.

## Leave it running

From here on, your agents stay running between chapters.

## Troubleshooting

**Docker not running / compose fails.** Make sure Docker Desktop is running.

**`ANTHROPIC_API_KEY` not set.** The provider will start but LLM calls will fail.

**Traces not appearing.** Check that agents were started with `--dte` and
Redis is reachable at `redis://localhost:6379`.

**`meshctl trace` returns "trace not found".** Traces take a few seconds to
propagate. Wait 5-10 seconds after the call completes, then try again.

## Recap

You stood up an observability stack, registered a zero-code LLM provider, built
a planner agent that generates itineraries via prompt templates, and traced the
full call tree across agents.

## See also

- `meshctl man llm` -- the full LLM integration reference
- `meshctl man observability` -- distributed tracing setup
- `meshctl man decorators` -- the complete decorator reference

---

# Day 4 -- Multiple Providers and Dependency Tiers

Your planner works, but it's locked to one LLM provider and generates plans
from imagination. Today you'll add a second LLM provider, introduce
preference-based routing with automatic failover, and connect the planner to
your tool agents so it plans with real flight and hotel data.

## What we're building today

[Diagram: Eight agents with Claude and OpenAI providers, planner connected to tool agents via tier-1 and tier-2 dependencies]

Eight agents. The five tool agents, two LLM providers (Claude and OpenAI), and
the planner -- now connected to everything.

Today has six parts:

1. **Add a second LLM provider** -- wrap OpenAI as a mesh capability
2. **Provider tags and preference routing** -- teach `+`/`-` tag operators
3. **Provider swap -- zero code changes** -- stop Claude, watch failover
4. **Connect the planner to tool agents** -- tier-1 prefetch and tier-2 tools
5. **Call the enhanced planner** -- generate a plan with real data
6. **Walk the trace** -- see the full call tree across all eight agents

## Part 1: Add a second LLM provider

> **API keys required** -- You need both `ANTHROPIC_API_KEY` and
> `OPENAI_API_KEY` set in your environment.

```shell
$ meshctl scaffold --name openai-provider --agent-type llm-provider --model openai/gpt-4o-mini --port 9108
```

[Note: See the tutorial source files in examples/tutorial/trip-planner/day-04/ for full code listings]

The only differences from `claude-provider`: the model string and the tags.
The capability name is still `"llm"` -- both providers advertise the same
capability.

## Part 2: Provider tags and preference routing

MCP Mesh tags support three operators for consumer-side selection:

| Prefix | Meaning   | Example                               |
| ------ | --------- | ------------------------------------- |
| (none) | Required  | `"api"` -- must have this tag         |
| `+`    | Preferred | `"+claude"` -- bonus if present       |
| `-`    | Excluded  | `"-deprecated"` -- reject if present  |

The matching algorithm:

1. **Filter** -- remove candidates with any excluded tag (`-`)
2. **Require** -- keep only candidates with all required tags (no prefix)
3. **Score** -- add bonus points for each preferred tag (`+`) present
4. **Select** -- return the highest-scoring candidate

Update the planner's provider selection to use `+claude`:

`+claude` means: "prefer a provider tagged `claude`. If one is available, route
there. If not, fall back to any other provider with capability `llm`." The `+`
makes it a preference, not a requirement.

## Part 3: Provider swap -- zero code changes

### Call 1: Claude is preferred and available

```shell
$ meshctl call plan_trip '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$2000"}' --trace
```

The trace shows the planner routed to `claude_provider`.

### Call 2: Stop Claude, watch failover

```shell
$ meshctl stop claude-provider
```

Call the planner again -- same code, same arguments:

```shell
$ meshctl call plan_trip '{"destination":"Tokyo","dates":"June 10-14, 2026","budget":"$3000"}' --trace
```

The trace shows `openai_provider` -- automatic failover with no code change.

### Call 3: Restart Claude, verify preference

```shell
$ meshctl start --dte --debug -d -w claude-provider/main.py
```

Call again -- the trace shows `claude_provider` is back. The `+claude`
preference kicks in again because Claude is healthy and has the highest tag
score.

Three calls, three traces, two different providers. The planner's code didn't
change once.

## Part 4: Connect the planner to tool agents

### Tier-1: prefetch dependencies

Tier-1 dependencies are fetched **before** the LLM call. Your code calls them
explicitly and injects the results into the prompt context. For the planner,
that's `user_preferences`.

### Tier-2: LLM-discoverable tools

Tier-2 tools are made available to the LLM during its reasoning loop. The LLM
discovers them via their schemas and decides which to call based on the user's
question. You don't call them -- the LLM does.

The `filter` parameter tells the registry which tools to expose to the LLM:

- `{"capability": "flight_search"}` -- flights
- `{"capability": "hotel_search"}` -- hotels
- `{"capability": "weather_forecast"}` -- weather
- `{"capability": "poi_search"}` -- points of interest

### The two tiers together

The execution flow:

1. **Tier-1**: `user_prefs` is called explicitly. The result is formatted
   and passed as context to the LLM call.
2. **Tier-2**: `flight_search`, `hotel_search`, `get_weather`, `search_pois`
   are presented to the LLM as callable tools. The LLM decides which to call.

## Part 5: Call the enhanced planner

With all eight agents running:

```shell
$ meshctl call plan_trip '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$2000"}' --trace
```

The response now includes real data from your tool agents.

## Part 6: Walk the trace

```
  plan_trip (planner-agent) [18349ms]
    get_user_prefs (user-prefs-agent) [1ms]
    claude_provider (claude-provider) [18308ms]
      search_pois (poi-agent) [31ms]
        get_weather (weather-agent) [1ms]
      get_weather (weather-agent) [0ms]
      get_weather (weather-agent) [0ms]
      hotel_search (hotel-agent) [1ms]
```

The full call tree across eight agents. The mesh overhead adds single-digit
milliseconds.

> **Trace depth** -- The trace tree can go multiple levels deep. Each hop is
> a separate span, linked by trace context that propagates automatically.

## Leave it running

Your eight agents are running in watch mode. On Day 5 you'll add an HTTP
gateway.

## Troubleshooting

**`OPENAI_API_KEY` not set.** The provider will start but LLM calls will fail.

**Provider swap doesn't work.** Both providers must have the same capability
name (`"llm"`). Check with `meshctl list --tools`.

**Tool calls not appearing in trace.** Check the planner's `filter` parameter
and `max_iterations`.

**Planner returns a generic plan without real data.** The LLM didn't call
the tier-2 tools. Check `filter` capabilities and the system prompt.

## Recap

You added a provider, swapped it with zero code changes, and connected the
planner to real data sources. Failover, tool discovery, and trace propagation
all happened at runtime.

## See also

- `meshctl man tags` -- the full tag matching reference
- `meshctl man llm` -- the `@mesh.llm` decorator reference
- `meshctl man capabilities` -- capability selectors

---

# Day 5 -- HTTP Gateway

Your trip planner works from the terminal via `meshctl call`. But real users
need an HTTP API. Today you'll wrap the planner in a FastAPI gateway -- a thin
REST endpoint that bridges HTTP requests to mesh tool calls.

## What we're building today

[Diagram: Nine agents -- User -> gateway -> planner -> LLM -> tools]

Nine agents. Everything from Day 4 plus the gateway. The user sends an HTTP
request to the gateway. The gateway calls the planner through mesh dependency
injection. The planner calls the LLM provider, which calls the tool agents.

Today has four parts:

1. **Build the gateway** -- a FastAPI app with `@mesh.route`
2. **Start the gateway** -- add it to your running mesh
3. **Call the API** -- `curl` the gateway
4. **Walk the trace** -- see the full call tree from HTTP to tool agents

## Part 1: Build the gateway

### Scaffold the gateway

```shell
$ meshctl scaffold --name gateway --agent-type api --lang python --port 8080
```

[Note: See the tutorial source files in examples/tutorial/trip-planner/day-05/ for full code listings]

That's the entire gateway. Three imports, a health check, and one route handler.

### How @mesh.route works

`@mesh.route` is a decorator for FastAPI handlers that injects mesh
capabilities as function parameters -- the same dependency injection that
`@mesh.tool` uses, but for HTTP endpoints instead of MCP tools.

The key line is `@mesh.route(dependencies=["trip_planning"])`. This tells mesh:
"Before this handler runs, resolve the `trip_planning` capability and inject it
as a callable."

The handler is five lines of code:

1. Parse the JSON body.
2. Check that the tool was injected.
3. Call the injected tool with the request parameters.
4. Return the result.

The gateway doesn't import the planner. It doesn't know the planner's URL.

## Part 2: Start the gateway

```shell
$ meshctl start --dte --debug -d -w gateway/main.py
```

Nine agents running. The gateway shows type `API` and its dependency `1/1`
resolved.

## Part 3: Call the API

### Via curl

```shell
$ curl -s -X POST http://localhost:8080/plan \
    -H "Content-Type: application/json" \
    -d '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$2000"}'
```

A full trip itinerary, personalized with the user's preferences, built from
real data returned by your tool agents.

## Part 4: Walk the trace

```
  plan_trip (planner-agent) [17842ms]
    get_user_prefs (user-prefs-agent) [1ms]
    claude_provider (claude-provider) [17803ms]
      flight_search (flight-agent) [15ms]
        get_user_prefs (user-prefs-agent) [0ms]
      hotel_search (hotel-agent) [1ms]
      get_weather (weather-agent) [0ms]
      search_pois (poi-agent) [22ms]
        get_weather (weather-agent) [0ms]
      get_weather (weather-agent) [0ms]

Summary: 14 spans across 7 agents | 17.84s
```

> **The thin wrapper pattern** -- The gateway has no business logic. It
> translates HTTP to mesh and mesh to HTTP. When you add a new tool agent, the
> gateway doesn't change.

## Cross-language gateway swap

One of mesh's strengths is that any agent -- including the gateway -- can be
swapped for a different language without changing anything else. The planner,
providers, and tool agents don't care what language the gateway is written in.

Options: Spring Boot (Java), Express (TypeScript), or continue with FastAPI.

## Part 1 complete

That's Part 1. You have a working trip planner: nine agents, two LLM providers
with automatic failover, dependency injection across tools and providers,
prompt templates, distributed traces, and an HTTP API.

Part 2 grows this into something production-shaped.

## Leave it running

Your nine agents are running in watch mode.

## Troubleshooting

**Port 8080 already in use.** Change the port in `gateway/main.py`.

**FastAPI not installed.** Install in your venv: `pip install fastapi uvicorn`

**Gateway starts but curl fails.** Check that the gateway is healthy with
`meshctl list` and the planner is running.

**curl returns empty or truncated response.** Trip planning calls take 15-20
seconds. Increase the timeout: `curl -s --max-time 60 ...`

## Recap

You wrapped your trip planner in a five-line FastAPI handler, bridging HTTP to
mesh with `@mesh.route`. The gateway is a thin entry point -- no business
logic, no planner imports, no hardcoded URLs.

## See also

- `meshctl man api` -- the full `@mesh.route` reference
- `meshctl man decorators` -- the complete decorator reference
- `meshctl man capabilities` -- capability selectors

---

# Day 6 -- Chat History

Your trip planner generates great itineraries, but every call starts from
scratch. Real users iterate -- "make it cheaper," "add a beach day," "what
about hotels near the train station." Today you add conversation memory so the
planner remembers what you have discussed.

## What we're building today

[Diagram: Ten agents -- everything from Day 5 plus chat-history-agent]

Ten agents. Everything from Day 5 plus `chat-history-agent`. The planner
fetches prior turns from chat history before calling the LLM, and saves both
the user message and the response afterward.

Today has four parts:

1. **Build the chat history agent** -- a tool agent backed by Redis
2. **Update the planner** -- add history fetch and save around the LLM call
3. **Update the gateway** -- add session ID passthrough
4. **Walk the trace** -- see history calls in the distributed trace

## Part 1: Build the chat history agent

Chat history is just another mesh tool agent. There is no special framework
primitive for state -- you write an agent that wraps a data store, and other
agents call it like any other tool.

```shell
$ meshctl scaffold --name chat-history-agent --agent-type tool --port 9109
```

[Note: See the tutorial source files in examples/tutorial/trip-planner/day-06/ for full code listings]

Two tools, one capability. `save_turn` appends a JSON-encoded turn to a Redis
list keyed by session ID. `get_history` reads the most recent turns from that
list. Both tools share the `chat_history` capability.

### Why this works

Swap Redis for Postgres by editing one agent. Add encryption by extending one
agent. The gateway and planner do not move.

## Part 2: Update the planner

The planner gains chat history as a tier-1 dependency alongside user
preferences. It fetches history before the LLM call and saves turns after.

The `@mesh.tool` decorator now declares two dependencies instead of one.

When history is present, the planner passes the full message list to the LLM
instead of a single string. The `@mesh.llm` decorator handles multi-turn
natively -- pass a list of `{"role": "...", "content": "..."}` dicts.

## Part 3: Update the gateway

The gateway gains a `session_id` parameter. If the client sends `X-Session-Id`,
the gateway uses it. Otherwise it generates a UUID and returns it in the
response.

### Start and test

Install redis-py if needed: `pip install redis`

Start the chat history agent:

```shell
$ meshctl start --dte --debug -d -w chat-history-agent/main.py
```

Ten agents running. The planner shows `2/2` dependencies.

### Multi-turn demo

Turn 1 -- plan a trip:

```shell
$ curl -s -X POST http://localhost:8080/plan \
    -H "Content-Type: application/json" \
    -H "X-Session-Id: test-session-1" \
    -d '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$2000"}'
```

Turn 2 -- iterate on the plan:

```shell
$ curl -s -X POST http://localhost:8080/plan \
    -H "Content-Type: application/json" \
    -H "X-Session-Id: test-session-1" \
    -d '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$1500","message":"Can you make it cheaper? I want to stay under $1500."}'
```

The second response references the first plan -- it knows about the previous
hotel choice, the original budget, and the itinerary structure.

## Part 4: Walk the trace

```
  plan_trip (planner-agent) [18542ms]
    get_history (chat-history-agent) [2ms]
    get_user_prefs (user-prefs-agent) [1ms]
    claude_provider (claude-provider) [18451ms]
      flight_search (flight-agent) [14ms]
        get_user_prefs (user-prefs-agent) [0ms]
      hotel_search (hotel-agent) [1ms]
      get_weather (weather-agent) [0ms]
      search_pois (poi-agent) [21ms]
        get_weather (weather-agent) [0ms]
    save_turn (chat-history-agent) [1ms]
    save_turn (chat-history-agent) [1ms]
```

> **Stateful concerns are just agents** -- Redis-backed chat history, user
> profiles, booking state, audit logs -- they are all the same pattern: a mesh
> tool agent wrapping a data store. The general abstraction handles them all.

## Leave it running

Your ten agents are running in watch mode.

## Troubleshooting

**Redis connection refused.** Make sure the observability stack is running:
`docker compose -f docker-compose.observability.yml up -d`

**History not persisting across calls.** Verify you are sending the same
`X-Session-Id` header in both requests.

**Second turn does not reference the first.** Check the `chat_history`
dependency resolved (planner shows `2/2`), Redis contains the turns, and
the trace shows `get_history` returning a non-empty list.

## Recap

You added multi-turn chat history by building one new agent and updating two
existing ones. No framework changes, no special chat primitives -- just
another mesh tool agent wired through dependency injection.

## See also

- `meshctl man decorators` -- the `@mesh.tool` and `@mesh.route` reference
- `meshctl man dependency-injection` -- how DI resolves multi-tool capabilities
- `meshctl man llm` -- multi-turn message format

---

# Day 7 -- Committee of Specialists

Your planner generates solid itineraries, but a single LLM perspective has
blind spots. A budget-conscious traveler needs cost analysis. An adventurous
one needs hidden gems. Everyone needs logistics that actually work. Today you
add three specialist agents -- each with its own expertise -- and have the
planner consult all of them before producing the final plan.

## What we're building today

[Diagram: Thirteen agents -- planner fans out to budget-analyst, adventure-advisor, logistics-planner]

Thirteen agents. Everything from Day 6 plus three specialists. The planner
generates a base itinerary, then fans out to three specialist LLM agents in
parallel. Each specialist returns structured data -- a Pydantic model -- which
the planner synthesizes into the final response.

Today has five parts:

1. **Structured outputs** -- Pydantic return types on `@mesh.llm` agents
2. **Build the specialists** -- scaffold three LLM agents
3. **Update the planner** -- add committee dependencies and parallel fan-out
4. **Start and test** -- launch 13 agents, call the planner
5. **Walk the trace** -- fan-out trace

## Part 1: Structured outputs

When an `@mesh.llm` function returns `str`, the LLM's text response passes
through as-is. When it returns a Pydantic `BaseModel`, mesh instructs the LLM
to produce JSON matching the schema and validates the response automatically.

> **Use typed models, not dict** -- Define typed Pydantic sub-models instead
> of bare `dict` for list fields. Typed models produce explicit JSON schemas
> that work across all LLM providers.

## Part 2: Build the specialists

### Budget analyst

```shell
$ meshctl scaffold --name budget-analyst --agent-type llm-agent --port 9110
```

[Note: See the tutorial source files in examples/tutorial/trip-planner/day-07/ for full code listings]

The function takes `destination`, `plan_summary`, and `budget` as input. The
return type `BudgetAnalysis` tells mesh to validate the response as structured
JSON.

### Adventure advisor

```shell
$ meshctl scaffold --name adventure-advisor --agent-type llm-agent --port 9111
```

Returns `AdventureAdvice` with `unique_experiences`, `local_gems`, and
`off_beaten_path`.

### Logistics planner

```shell
$ meshctl scaffold --name logistics-planner --agent-type llm-agent --port 9112
```

Returns `LogisticsPlan` with `daily_schedule`, `transit_tips`, and
`time_optimization`.

## Part 3: Update the planner

### Add dependencies

The `@mesh.tool` decorator now lists four dependencies. Mesh resolves each
capability to an `McpMeshTool` proxy.

### Fan out with asyncio.gather

After the LLM generates a base plan, the planner calls all three specialists
in parallel. Each specialist receives the destination and the base plan summary.
Because each specialist is an independent LLM call with `max_iterations=1`,
they run concurrently without interference.

## Part 4: Start and test

```shell
$ meshctl start --dte --debug -d -w \
    budget-analyst/main.py \
    adventure-advisor/main.py \
    logistics-planner/main.py
```

Thirteen agents. The planner now shows `5/5` dependencies.

### Call the planner

```shell
$ curl -s -X POST http://localhost:8080/plan \
    -H "Content-Type: application/json" \
    -H "X-Session-Id: test-session-day7" \
    -d '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$2000"}'
```

The response includes the base itinerary followed by specialist insights:
budget analysis, adventure recommendations, and logistics planning.

## Part 5: Walk the trace

```
  plan_trip (planner-agent) [42871ms]
    get_history (chat-history-agent) [2ms]
    get_user_prefs (user-prefs-agent) [1ms]
    claude_provider (claude-provider) [18451ms]
      flight_search (flight-agent) [14ms]
        get_user_prefs (user-prefs-agent) [0ms]
      hotel_search (hotel-agent) [1ms]
      get_weather (weather-agent) [0ms]
      search_pois (poi-agent) [21ms]
        get_weather (weather-agent) [0ms]
    budget_analysis (budget-analyst) [8204ms]       <- parallel
    adventure_advice (adventure-advisor) [7891ms]   <- parallel
    logistics_planning (logistics-planner) [8102ms] <- parallel
    save_turn (chat-history-agent) [1ms]
    save_turn (chat-history-agent) [1ms]
```

The planner first generates the base plan (18s), then fans out to the three
specialists in parallel (~8s each, overlapping). Total wall-clock time for the
specialists is about 8 seconds, not 24.

> **Structured outputs are validated at the edge** -- Each specialist's Pydantic
> model acts as a contract. If a specialist's LLM response does not match the
> schema, mesh retries automatically.

## Stop and clean up

```shell
$ meshctl stop
```

On Day 8 you'll containerize the entire mesh with Docker Compose.

## Troubleshooting

**Specialist dependency not resolved.** Make sure all three specialist agents
started successfully. Check logs: `meshctl logs budget-analyst`

**Specialist returns raw text instead of JSON.** The Pydantic return type
requires the LLM to produce valid JSON. Check that the prompt asks for JSON.

**asyncio.gather raises an exception.** If one specialist fails,
`asyncio.gather` raises the first exception and cancels the others. Consider
using `return_exceptions=True` for production.

**Timeouts on specialist calls.** Three parallel LLM calls may hit rate limits.
Check your API key's rate limits.

## Recap

You added a committee of three specialist agents. Each specialist is an
independent `@mesh.llm` agent with a Pydantic return type for structured
output. The planner calls them in parallel with `asyncio.gather`.

## See also

- `meshctl man decorators` -- the `@mesh.tool` and `@mesh.llm` reference
- `meshctl man dependency-injection` -- multi-capability dependencies

---

# Day 8 -- Docker Compose

Until now you have been running agents individually with `meshctl start`.
That is great for development. But for integration testing and demo
environments, you want one command that brings up the entire mesh. Today you
will generate a Docker Compose file from your agent code and start everything
with `docker compose up`.

## What we're building today

[Diagram: docker compose up -- Infrastructure (postgres, registry, mesh-ui), Observability (redis, tempo, grafana), 13 Agents]

One Docker Compose file. Thirteen agents, a registry, a database, the Mesh
UI dashboard, and a full observability stack.

Today has five parts:

1. **Generate the compose file** -- `meshctl scaffold --compose --observability`
2. **Start the containerized mesh** -- `docker compose up -d`
3. **Verify** -- `meshctl list`, curl the gateway, check health
4. **Mesh UI tour** -- agents, topology, traces at `localhost:3080`
5. **Stop and clean up** -- `docker compose down`

## Part 1: Generate the compose file

```shell
$ meshctl scaffold --compose --observability
```

The scaffold scanned every subdirectory, found `@mesh.agent` decorators in
twelve Python files, extracted each agent's name and port, and generated a
complete `docker-compose.yml` with infrastructure services, health checks,
and networking.

> **meshctl DX** -- The compose file was generated from your agent code.
> When you add a new agent, re-run `meshctl scaffold --compose` and the
> compose file updates automatically.

## Part 2: Start the containerized mesh

```shell
$ docker compose up -d
```

Docker pulls the images (first run only), starts the infrastructure, waits
for health checks, and then starts all agents.

## Part 3: Verify

```shell
$ meshctl list
```

All thirteen agents should appear. The output is the same as when you ran
them locally -- `meshctl` does not know or care whether agents are containers.

```shell
$ curl -s -X POST http://localhost:8080/plan \
    -H "Content-Type: application/json" \
    -H "X-Session-Id: compose-test-1" \
    -d '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$2000"}'
```

The same functionality as Day 7, now running entirely in containers.

## Part 4: Mesh UI tour

Open http://localhost:3080 in your browser.

### Dashboard

Agent count, health status, and a traffic summary table. Real-time events
stream in the sidebar.

### Topology

The full agent dependency graph. Nodes represent agents, edges represent
dependencies.

### Traffic

Inter-agent call metrics: total calls, success rate, token usage, and data
transferred.

### Live

Real-time trace streaming. Make a `/plan` call and watch spans appear.

### Agents

Table of all registered agents with name, type, runtime, version, dependency
resolution status, and last seen time.

## Part 5: Stop

```shell
$ docker compose down
```

## Troubleshooting

**Docker build fails with missing requirements.** Check that `requirements.txt`
exists in the agent directory.

**Agent cannot connect to registry.** Check that the agent's
`MCP_MESH_REGISTRY_URL` is set to `http://registry:8000` (Docker hostname).

**Port conflict on startup.** Change the host port mapping in
`docker-compose.yml`.

**API keys not passed to containers.** Set them in your shell or in a `.env`
file next to `docker-compose.yml`.

## Recap

You generated a Docker Compose file from your agent code with a single
command. The scaffold detected agents, extracted names and ports, and
produced a complete compose file.

## See also

- `meshctl man deployment` -- deployment patterns
- `meshctl scaffold --compose --help` -- all scaffold compose flags

---

# Day 9 -- Kubernetes

Your trip planner runs in Docker Compose. Today you deploy it to
Kubernetes -- the same agents, the same code, the same mesh.

## What we're building today

[Diagram: Kubernetes namespace with mcp-mesh-core Helm chart and 13 agent deployments]

One namespace. Two Helm charts (`mcp-mesh-core` for infrastructure,
`mcp-mesh-agent` for each agent). Thirteen agents, a registry, a database,
and a full observability stack.

Today has five parts:

1. **The DDDI payoff** -- same code, new platform
2. **Create the namespace and secrets** -- one-time setup
3. **Deploy the registry and infrastructure** -- `helm install mcp-core`
4. **Deploy the agents** -- one `helm install` per agent
5. **Verify** -- `kubectl get pods`, `meshctl list`, `curl` the gateway

## The DDDI payoff

The `flight_search` function from Day 1 is the same function running on
Kubernetes. One line changed: the description string.

The `helm-values.yaml` file from Day 1 is the Kubernetes deployment manifest.
No env-specific config files. No sidecars. No wrapper code.

## Prerequisites

- A Kubernetes cluster (minikube, kind, EKS, GKE, AKS)
- `kubectl` configured for your cluster
- Helm 3.8+ (OCI registry support)
- Agent images built and available to the cluster

## Part 1: Build agent images

Each agent has a `Dockerfile` (generated by `meshctl scaffold`). Build all
thirteen agents:

```shell
$ for agent in flight-agent hotel-agent weather-agent poi-agent \
    user-prefs-agent chat-history-agent claude-provider openai-provider \
    planner-agent gateway budget-analyst adventure-advisor logistics-planner
do
  echo "Building $agent..."
  docker build -t "trip-planner/${agent}:latest" "$agent/"
done
```

## Part 2: Create the namespace and secrets

```shell
$ kubectl create namespace trip-planner
```

LLM agents need API keys. Create a Kubernetes Secret:

```shell
$ kubectl -n trip-planner create secret generic llm-keys \
    --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
    --from-literal=OPENAI_API_KEY=$OPENAI_API_KEY
```

## Part 3: Deploy the registry

```shell
$ helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
    --version 1.3.4 \
    -n trip-planner \
    -f helm/values-core.yaml \
    --wait --timeout 5m
```

## Part 4: Deploy the agents

```shell
$ AGENTS=(
    flight-agent hotel-agent weather-agent poi-agent user-prefs-agent
    chat-history-agent claude-provider openai-provider planner-agent
    gateway budget-analyst adventure-advisor logistics-planner
  )

$ for agent in "${AGENTS[@]}"; do
    echo "Installing $agent..."
    helm install "$agent" \
      oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
      --version 1.3.4 \
      -n trip-planner \
      -f "helm/values-${agent}.yaml"
  done
```

### Port strategy

In Kubernetes, each pod has its own IP address, so every agent listens on port
`8080`. The Helm chart sets `MCP_MESH_HTTP_PORT=8080` as an environment
variable. Your code does not change.

## Part 5: Verify

### Check pods

```shell
$ kubectl -n trip-planner get pods
```

Eighteen pods: five infrastructure, thirteen agents. All `1/1 Running`.

### Check agent registration

```shell
$ kubectl -n trip-planner port-forward svc/mcp-core-mcp-mesh-registry 8000:8000 &
$ meshctl list --registry-url http://localhost:8000
```

Thirteen agents, all healthy. Endpoints use Kubernetes DNS names.

### Call the gateway

```shell
$ kubectl -n trip-planner port-forward svc/gateway-mcp-mesh-agent 8080:8080 &

$ curl -s -X POST http://localhost:8080/plan \
    -H "Content-Type: application/json" \
    -H "X-Session-Id: k8s-test-1" \
    -d '{"destination":"Kyoto","dates":"June 1-5, 2026","budget":"$2000"}'
```

The same output you saw on Day 7 and Day 8, now served from Kubernetes pods.

## What changed from Day 8

| Aspect | Day 8 (Docker Compose) | Day 9 (Kubernetes) |
| --- | --- | --- |
| **Agent code** | Identical | Identical |
| **Orchestrator** | `docker compose up` | `helm install` |
| **Port strategy** | Unique ports (9101, 9102...) | All agents on 8080 |
| **Secrets** | `.env` file | Kubernetes Secret |
| **Networking** | Docker bridge network | Kubernetes DNS |
| **Health probes** | Docker health checks | k8s liveness/readiness |
| **Scaling** | Manual | `kubectl scale` or HPA |

The agent code column says "Identical" twice.

## Clean up

```shell
$ ./helm/teardown.sh
```

## Troubleshooting

**Image pull errors.** On minikube, build images inside minikube's Docker
daemon and set `image.pullPolicy=Never`.

**Pod in CrashLoopBackOff.** Check the logs: `kubectl -n trip-planner logs <pod-name>`

**meshctl list shows no agents.** Make sure the registry port-forward is running.

**Gateway returns "capability unavailable".** Wait 30 seconds for all agents
to complete registration.

## Recap

You deployed all thirteen agents to Kubernetes using two Helm charts.
The agent code is identical to Day 8. The DDDI pattern delivered on its
promise: the function you wrote on Day 1 runs in Kubernetes without
modification.

## See also

- `meshctl man deployment` -- deployment patterns
- `meshctl man security` -- TLS, entity trust, and certificate management

---

# Day 10 -- What You Built and Where to Go

Ten days ago you scaffolded a single tool agent. Today you have a 13-agent
trip planner running on Kubernetes with LLM-driven planning, a committee of
specialists, chat history, distributed tracing, and an HTTP API.

---

## Part 1: What you built

### By the numbers

| Metric | Count |
|--------|-------|
| Agents | **13** -- 5 tool, 2 LLM providers, 1 planner, 3 specialists, 1 gateway, 1 chat history |
| LLM providers | **2** with automatic failover (Claude + OpenAI) |
| Dependency patterns | Tier-1 (direct) and tier-2 (transitive) |
| Chat backend | Multi-turn conversations with Redis |
| Structured outputs | Committee aggregation via Pydantic models |
| Deployment targets | Docker Compose + Kubernetes with Helm |
| Observability | Distributed tracing via `meshctl trace`, Grafana dashboards, Tempo |

### The journey, day by day

| Day | What you built | Key concept |
|-----|---------------|-------------|
| 1 | `flight_search` -- a single tool agent | `meshctl scaffold`, `@mesh.tool` |
| 2 | 5 tool agents wired together | Dependency injection, capabilities |
| 3 | LLM planner with Jinja templates | `@mesh.llm`, observability, `meshctl trace` |
| 4 | Claude + OpenAI with automatic failover | Tag routing (`+claude`), tier-1/tier-2 |
| 5 | FastAPI chat gateway | `@mesh.route`, HTTP integration |
| 6 | Redis-backed chat history | Persistent conversations, session management |
| 7 | Committee of specialists | Structured outputs, multi-agent coordination |
| 8 | Docker Compose deployment | Containerized agents, `meshctl scaffold --compose` |
| 9 | Kubernetes with Helm | Helm charts, ingress, production observability |
| 10 | You are here | Production readiness, what's next |

Every day added capability without rewriting what came before.

### The code you didn't write

Over ten days you focused on business logic -- the trip planning domain. Here
is what you never had to build:

- No REST clients or HTTP handlers for inter-agent communication
- No service discovery code
- No environment-specific configuration files
- No sidecars or proxy containers
- No LLM vendor SDK imports in the planner
- No serialization/deserialization code for tool calls

---

## Part 2: Production readiness

### Security

MCP Mesh provides three layers of security: registration trust, agent-to-agent
mTLS, and authorization.

- **Registration trust** -- the registry validates agent identity via TLS
  certificates. Supports file-based certs, HashiCorp Vault PKI, and SPIRE.
- **Agent-to-agent mTLS** -- every inter-agent call is mutually authenticated.
- **Authorization** -- MCP Mesh propagates HTTP headers end-to-end.
- **Entity management** -- `meshctl entity register`, `meshctl entity list`,
  and `meshctl entity revoke` control which CAs are trusted.

### Observability

- **Distributed tracing** -- every tool call and inter-agent hop is traced.
- **Dashboards** -- Grafana ships with pre-configured views.
- **Alerting** -- connect Grafana alerting to Slack, PagerDuty, or email.

### Resource limits

Set CPU and memory limits in your Helm values files:

```yaml
agent:
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

### Health probes

Mesh agents expose health endpoints automatically (`/health`). The Helm
chart wires liveness and readiness probes.

### Secrets management

For production, use external-secrets-operator or sealed-secrets.

### Horizontal scaling

Tool agents are stateless -- run multiple replicas for throughput:

```yaml
agent:
  replicaCount: 3
```

---

## Part 3: Challenges

### Add OAuth authentication to the gateway

Protect the `/plan` endpoint with JWT tokens. Configure
`MCP_MESH_PROPAGATE_HEADERS` to forward the `Authorization` header.

### Integrate RAG with a knowledge-base agent

Scaffold a new agent that retrieves destination guides from a vector store.
Inject the retrieved context into the planner's prompt template.

### Add a Gemini provider

Scaffold a third LLM provider. Register it with `capability="llm"` and
`tags=["gemini"]`. Test three-way failover.

### Build a price monitor

Create a scheduled agent that checks flight prices daily. Wire a notification
agent for alerts via email or Slack.

### Swap a Python agent for TypeScript

Rewrite `weather-agent` in TypeScript. The planner doesn't know or care --
it discovers capabilities, not implementations.

### Add structured logging

Configure JSON logging with `trace_id` from mesh headers. Ship logs to
Grafana Loki.

### Build a mobile client

Create a web UI that talks to the gateway's `/plan` endpoint.

---

## The finished product

Ten days. Thirteen agents. Three LLM providers. One framework. You went from
`meshctl scaffold` to a Kubernetes-deployed, multi-user AI application -- and
the `flight_search` function you wrote in the first hour of Day 1 is still
running, unchanged, in a production pod. No rewrites. No migration layer. No
"now let's port it to the real stack." The code you wrote *is* the real stack.
That is what MCP Mesh was built for, and you just proved it works.

---

## Thank you

That's the TripPlanner tutorial. You started with a single Python function
and ended with a 13-agent system running on Kubernetes -- with LLM planning,
committee refinement, chat history, distributed tracing, and an HTTP API.
Every agent is a plain Python file. Every deployment target uses the same
code. The mesh handled the infrastructure so you could focus on the domain.

## See also

- `meshctl man overview` -- architecture overview
- `meshctl man decorators` -- the complete decorator reference
- `meshctl man deployment` -- Docker and Kubernetes deployment guides
- `meshctl man security` -- mTLS, registration trust, authorization
- `meshctl man observability` -- tracing, Grafana dashboards
- `meshctl man cli` -- meshctl commands and environment variables
