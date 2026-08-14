# Homepage scroll — copy draft

**Frame:** DDDI told as an organic story. Relationships form and dissolve; the mesh is the
infrastructure that makes that ordinary. Metaphor lives in the *structure and verbs*, never
in the vocabulary — the words *society, organism, life, born, citizen* must not appear on
screen. The one exception is "Life goes on," which earns it because the picture proves it
literally in the same frame.

**Division of labour per beat:**

| slot | job | voice |
|---|---|---|
| **Title** | the need — why this moment exists | narrative |
| **Sub-line** | the code that caused it | mono, literal |
| **Description** | what the mesh did about it | plain, mechanical |

Previously title and description both explained mechanism, leaving motive unspoken.

---

## Chapter names

Proposed: `01 ARRIVE` · `02 THINK` · `03 SURVIVE` · `04 OPEN` · `05 GROW`

(Current: BUILD / THINK / SURVIVE / EXPOSE / SHIP. `SURVIVE` already fits and stays.
`GROW` is more honest than `SHIP` since chapter 5 is polyglot + replicas, not deployment.)

---

# 01 ARRIVE

### B1 — It starts with one.
**sub:** `@mesh.tool(capability="flight_search")`

This is the mesh dashboard. Every card is a running agent; every line is a dependency the
mesh resolved on its own. Right now there is one agent — a plain Python function that
searches flights. No server code, no registration call, no config file.

### B2 — It needs what it doesn't have.
**sub:** `dependencies=["user_preferences"]`

The flight agent needs preferences it cannot provide itself. It names the capability — not
a host, not a port, not a URL — and the mesh finds whoever offers it and injects it as a
callable parameter. Four more agents come up, and two relationships form without either
side being told where the other lives.

---

# 02 THINK

### B3 — Now it needs to reason.
**sub:** `@mesh.llm(provider={"capability": "llm"})`

Some problems don't decompose into function calls. The planner needs a model, so it asks
for one the same way anything else asks for anything — by capability. It imports no vendor
SDK and reads no API key. A provider agent advertises `llm`, and that is the whole
integration.

### B4 — Reasoning picks its own collaborators.
**sub:** `filter=[{"capability": "flight_search"}, …]`

Instead of a fixed call graph, the planner declares what *kind* of help the model may
recruit. The mesh resolves everything matching and hands them over as callable tools. Add
a new agent to the mesh tomorrow and the model can reach it — with no redeploy and no
change to this code.

### B5 — And the ones that asked are now asked. *(new beat)*
**sub:** `capability="flight_search"` — *consumed, and consuming*

Every consumer is also a provider. The flight agent that needed preferences a moment ago is
now what the planner is looking for; the same card carries an edge in each direction. No one
brokered the introduction and nothing was registered twice. This is the whole idea — not a
call graph with a root, but a set of mutual needs that happen to resolve.

---

# 03 SURVIVE

### B6 — A better one arrives.
**sub:** `provider={"capability":"llm","tags":["+claude"]}`

A second provider joins, offering the same `llm` capability. The planner never named an
endpoint, so nothing has to be rewired to consider it — it expresses a *preference* with a
tag and the registry scores the candidates. Both remain eligible. One simply wins.

### B7 — It dies.
**sub:** `meshctl stop claude-provider`

The preferred provider stops. Its heartbeat lapses, the registry ages it out, and the
planner's dependency count drops. Nothing crashed and nothing was alerted. The mesh has
simply stopped counting on something that is no longer there.

### B8 — Life goes on.
**sub:** *no deploy · no config · no code change*

The planner's requirement was a capability, not an address — and something else already
satisfies it. Traffic moves. Exactly one edge on this screen changed; every other
relationship is untouched, and no agent was restarted to make it happen.

### B9 — The old one returns.
**sub:** `+claude` *scores higher — both are ready*

It comes back, and traffic returns to it. Not because the substitute failed — it stayed
healthy and connected the entire time — but because preference is scored continuously, not
decided once at startup. Relationships here are never permanent, in either direction.

---

# 04 OPEN

### B10 — The outside world wants in.
**sub:** `@mesh.route(dependencies=["trip_planning"])`

A five-line HTTP handler inherits the entire mesh. It provides no capability of its own and
contains no business logic — it declares what it needs and becomes a front door. The same
agents are also reachable over MCP and A2A without changing a line.

### B11 — One need, many minds.
**sub:** `-> BudgetAnalysis` — *typed, validated, retried*

Three specialists resolve as ordinary callables and run at once. Each returns a typed model
rather than a blob of text, and the mesh retries the call if a response doesn't match the
schema. Fan-out costs one line, because parallelism was never the hard part — knowing who
to call was.

---

# 05 GROW

### B12 — Rewritten. Nobody noticed.
**sub:** `weather-agent -> TypeScript · hotel-agent -> Java`

Two agents were replaced with implementations in different languages. Same capabilities,
same names, same relationships. Look at the graph: nothing moved. Their dependents were
never told, because a dependent asks for a capability and has no way to express a
preference about the language behind it.

### B13 — More of it. Same relationships.
**sub:** `replicaCount: 3`

Three instances register under one name and collapse into a single card. Nothing
re-resolves and no consumer is reconfigured — behind a Kubernetes Service the mesh resolves
the name once and Kubernetes spreads the calls across whoever is healthy.

> **Accuracy note:** do NOT write "the mesh routes to any healthy instance."
> `audit.md:153` — *"The registry does not load balance… it selects exactly one winner per
> dependency, deterministically."* Distribution is Kubernetes', via Service DNS.

### B14 — Nothing here was wired by hand.
**sub:** `twelve agents · three languages · every edge resolved itself`

*(No description paragraph. Full-bleed frame.)*

---

# THE THRESHOLD — before B1

A title card that opens the section. It exists to give the reader a transition into the
piece — without it, the page goes from ordinary docs prose straight into `01 ARRIVE`, which
reads as a jump cut. Restored after being cut once: the problem was its old copy
("Scroll to build a mesh, give it a brain, and then take one away" — pre-reframe voice),
not the slide itself.

> **eyebrow:** `MCP MESH`
> ### One agent becomes twelve.
> Keep scrolling. They find each other.

*Deliberately no metaphor in the words — see the frame note at the top. The title says what
the reader is about to watch; the sub-line instructs the scroll and plants the hook.*

*Voice note — this card has now failed twice, and both failures are instructive because it is
the one surface in the piece with no picture beneath it, so the words carry themselves alone.*

*Attempt 1, "Scroll. Along the way, one of them dies." — teased the failure beat and read as a
film trailer. "Dies" earns its place as B7's **title**, where the graph is showing a node go
dark and the copy around it is clinical. It has nothing to anchor it on a title card.*

*Attempt 2, "Scroll. Nobody wires them together." — accurate, unmelodramatic, and **it spent
the ending**. It is the same reveal as B14's "Nothing here was wired by hand": both verdicts,
both negative constructions. The finale then lands on a reader who was told the answer twenty
screens earlier.*

*What works: the threshold makes a **promise**, the finale delivers a **verdict**. "They find
each other" and "Nothing here was wired by hand" are the same fact in different grammatical
roles — invitation, then conclusion. Setup and payoff, not repetition.*

*Rejected: "You only write the first one." Strong line, second-person, pairs neatly with B1 —
but it is **not true**. Twelve agents get written in this piece; what nobody writes is the
connections. It implies the other eleven appear unaided, which the section does not claim and
cannot support. A hero line a skeptical reader can falsify is expensive on a page whose whole
credibility rests on being real dashboard output.*

*Also rejected: any variant naming the organic metaphor (children choosing their own people,
arranged marriage). It is a superb **pitch** analogy and belongs in a talk or a README intro.
On the page it costs a sentence of setup before it pays, and the animation already is the
analogy — shown, not told. See the frame note at the top.*

---

# THE REVEAL — after the scroll completes

The graph clears. Same cinematic treatment — same left rail, same accent, same typography —
but the subject changes from a topology to the things a topology cannot draw.

## Headline

> ### Infrastructure that expects agents.
> **sub:** `MCP · A2A · REST` — *three protocols, three languages, three vendors, one decorator*

*Voice note: the old headline ("And everything the graph can't show") was defensive — it opened
the epilogue by naming a limitation, right where the piece should be accelerating. The claim
here is a paradigm one: existing infrastructure was built for services that sit still, and
agents are not that. Mesh is a substrate for things that rewire themselves, and it arrives
complete rather than assembled from parts. The six phases below are the proof; the headline
should assert, not apologise. Keep the metaphor out of the words — "expects" carries it.*

Then the six lifecycle phases reveal in sequence, matching
`docs/dev-to-production.md` (nav: *From Dev to Production*), whose canonical order is
**Learn → Develop → Test → Deploy → Secure → Observe**, with Observe looping back to Develop.

---

### LEARN
The man pages are compiled into the binary, so they describe the version you actually have
rather than whatever shipped last. Seventeen topics answer in Python, TypeScript or Java. A
`--raw` mode turns your AI coding assistant into a mesh expert, and a ten-day tutorial ships
inside the CLI.

### DEVELOP
Python, TypeScript, and Java agents discover and call each other through a shared Rust core.
One scaffold command emits the agent, its Dockerfile, and its Helm values. Claude, GPT, and
Gemini are native; a hundred more arrive through LiteLLM, the Vercel AI SDK, or Spring AI.

### TEST
Nothing points at a URL, so nothing needs repointing to test. Run an ordinary agent as a
stand-in on your laptop — no mock framework, no special annotation — and the local registry
wires your consumer to it. What differs between laptop and production is who registered,
never your code.

### DEPLOY
The same agent code runs on a laptop, in Docker Compose, and on Kubernetes with no changes.
Nothing in it names where anything lives, so there is nothing to repoint when it moves. The
health probes Kubernetes wants are already served, and scaling is one value in a file.

### SECURE
Every inter-agent call is mutually authenticated. Identity is checked with X.509 before a
registration is accepted, backed by files, HashiCorp Vault PKI, or SPIRE workload identity.
Certificates rotate through the heartbeat without a restart — and on Linux, private keys
live in tmpfs and never touch disk.

### OBSERVE
Spans cross language boundaries into one trace tree: a Python call into Java into TypeScript
reads as a single trace. Redis carries the stream, Tempo stores it, and three Grafana
dashboards come prebuilt. `meshctl trace` renders the call tree in your terminal.

---

## Final CTA

> ### Build one yourself.
> `npm install -g @mcpmesh/cli` · `meshctl scaffold`

*(`meshctl` is the CLI and ships via npm; `pip install mcp-mesh` is the Python SDK, which
the scaffold's generated `requirements.txt` pulls in. Leading with the SDK installer next to
a `meshctl` command was simply wrong.)*

---

# Claims deliberately excluded

Verified against the man pages; each of these appears somewhere in `docs/` but is not
supported, and must not reach the homepage.

| Claim | Where it appears | Reality |
|---|---|---|
| Prometheus ships with the platform | `comparison.md:135`, `07-observability.md:16` | No chart, no compose service. Only a Grafana datasource pointed at an external Prometheus. |
| Circuit breaker | `comparison.md:96` | Unsupported anywhere else. The only thing so named is the consumer-local service-view `min_available` floor, which has no wire effect. |
| RBAC support | `index.md:246` | No RBAC subsystem. The legitimate reference is *Kubernetes* RBAC. |
| Load balancing / replicas add throughput | implied widely | `audit.md:153` explicitly disclaims it. |
| Hot reload — code changes without restart | `comparison.md:17` | `--watch` restarts the process. What rewires without restart is *dependencies*. |
| Retry built into the resolver | `comparison.md:97` | Per-dependency `retry_count`, default `0` (off). Not resolver-level. |
| N-way fan-out via `filter_mode="all"` | `comparison.md:64` | `filter_mode` selects which tools an LLM may see. Not a fan-out RPC primitive. |
| Monolith mode | `comparison.md:30` | No man page or decorator backing it. |
| tsuite ships with mesh | `comparison.md:42` | Separate repository. |
| "The production code *is* the test code" | `comparison.md` | Implies you test against production agents. The real mechanism is local-registry substitution: an ordinary stand-in agent on the laptop, consumer unchanged. Still live in `docs/` — not fixed here. |
| Streaming (unqualified) | — | Producing a stream is Python-only; Java cannot originate one; TS consumer parity pending. Omitted rather than qualified. |
| A2A with OAuth/mTLS | — | *"future work"* — bearer token only. |
