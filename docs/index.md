---
title: Home
template: home.html
hide:
  - navigation
---

<!-- `hide: navigation` is LOAD-BEARING for the scroll section, not a styling
     preference. Material's primary sidebar is sticky and in-flow at >= 76.25em,
     and the section is a full-bleed 100vw band — so the sidebar sat on top of
     its left 266px, which is exactly where the copy column lives. Every beat's
     title, sub-line and description were underneath the site nav.

     Hiding it also makes the content column viewport-centred, which is why
     embed.css's breakout is a plain `calc(50% - 50vw)` with no correction. If
     the nav is ever restored here, that correction has to come back — see the
     note in src/ui/demo/embed.css.

     `hide: toc` is NOT needed: the secondary sidebar is not rendered on this
     page at all (verified in the built HTML). -->



# Distributed Service Mesh for AI Agents

You write the logic. The mesh discovers, connects, heals, and traces — across languages, machines, and clouds.

!!! tip "Complete Platform for AI Agents"
MCP Mesh is a complete platform for **building and deploying AI agents to production scale** — and it's all built on one idea, **DDDI**: you declare a capability, and the mesh resolves, types, heals, and hot-swaps it at runtime. [See how MCP Mesh compares →](00-why-mcp-mesh/index.md)

!!! info "What is DDDI?"
**Distributed Dynamic Dependency Injection** — dependencies are discovered, injected, and updated at runtime across machines, languages, and clouds. No configuration files, no restart required. [Learn more →](concepts/dddi.md)

---

## :rocket: Quick Overview

The same agent, in each language.

=== "Python"

    ```bash
    pip install mcp-mesh
    ```

    ```python
    from fastmcp import FastMCP
    import mesh

    app = FastMCP("TripPlanner")

    @app.tool()
    @mesh.tool(
        capability="plan_trip",
        dependencies=[
            {"capability": "weather", "tags": ["+claude"]},
            {"capability": "hotels",  "tags": ["+gpt"]},
            {"capability": "flights"},
            {"capability": "budget",  "tags": ["+claude"]},
        ],
    )
    async def plan_trip(
        destination: str,
        dates: str,
        weather: mesh.McpMeshTool = None,
        hotels:  mesh.McpMeshTool = None,
        flights: mesh.McpMeshTool = None,
        budget:  mesh.McpMeshTool = None,
    ) -> TripPlan:
        forecast = await weather(destination=destination, dates=dates)
        options  = await hotels(destination=destination, dates=dates)
        routes   = await flights(destination=destination, dates=dates)
        cost     = await budget(routes=routes, options=options)
        return TripPlan(forecast, options, routes, cost)

    @mesh.agent(name="trip-planner", auto_run=True)
    class TripAgent: pass
    ```

=== "Java"

    ```xml
    <dependency>
        <groupId>io.mcp-mesh</groupId>
        <artifactId>mcp-mesh-spring-boot-starter</artifactId>
        <version>3.7.0</version>
    </dependency>
    ```

    ```java
    import io.mcpmesh.MeshAgent;
    import io.mcpmesh.MeshTool;
    import io.mcpmesh.Param;
    import io.mcpmesh.Selector;
    import io.mcpmesh.types.McpMeshTool;
    import org.springframework.boot.SpringApplication;
    import org.springframework.boot.autoconfigure.SpringBootApplication;
    import java.util.Map;

    @MeshAgent(name = "trip-planner", version = "1.0.0", port = 8080)
    @SpringBootApplication
    public class TripPlannerApp {

        public static void main(String[] args) {
            SpringApplication.run(TripPlannerApp.class, args);
        }

        @MeshTool(
            capability = "plan_trip",
            dependencies = {
                @Selector(capability = "weather", tags = {"+claude"}),
                @Selector(capability = "hotels",  tags = {"+gpt"}),
                @Selector(capability = "flights"),
                @Selector(capability = "budget",  tags = {"+claude"})
            }
        )
        public TripPlan planTrip(
            @Param("destination") String destination,
            @Param("dates") String dates,
            McpMeshTool<Forecast> weather,
            McpMeshTool<HotelOptions> hotels,
            McpMeshTool<FlightRoutes> flights,
            McpMeshTool<Cost> budget
        ) {
            var args = Map.of("destination", destination, "dates", dates);
            var forecast = weather.call(args);
            var options  = hotels.call(args);
            var routes   = flights.call(args);
            var cost     = budget.call(Map.of("routes", routes, "options", options));
            return new TripPlan(forecast, options, routes, cost);
        }
    }
    ```

=== "TypeScript"

    ```bash
    npm install @mcpmesh/sdk
    ```

    ```typescript
    import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({ name: "TripPlanner", version: "1.0.0" });
    const agent = mesh(server, { name: "trip-planner", httpPort: 8080 });

    agent.addTool({
      name: "plan_trip",
      capability: "plan_trip",
      description: "Plan a trip by composing weather, hotels, flights, and budget",
      dependencies: [
        { capability: "weather", tags: ["+claude"] },
        { capability: "hotels",  tags: ["+gpt"] },
        { capability: "flights" },
        { capability: "budget",  tags: ["+claude"] },
      ],
      parameters: z.object({
        destination: z.string(),
        dates: z.string(),
      }),
      execute: async (
        { destination, dates },
        weather: McpMeshTool | null,
        hotels: McpMeshTool | null,
        flights: McpMeshTool | null,
        budget: McpMeshTool | null,
      ) => {
        const forecast = await weather!({ destination, dates });
        const options  = await hotels!({ destination, dates });
        const routes   = await flights!({ destination, dates });
        const cost     = await budget!({ routes, options });
        return { forecast, options, routes, cost };
      },
    });
    ```

!!! abstract "What just happened?"
    Four distributed calls, composed like a local function. Each dep could live in this process, another machine, another language. Mesh handles discovery, transport, retry, and failover — your function stays a function. Each dep is just another `@mesh.tool`, defined the same way — in this agent or another.

    Any dep can be a plain tool **or** an LLM agent — your code can't tell. `weather` could be a REST API *or* a Claude-powered reasoning agent returning a typed pydantic forecast. `+claude` means prefer the reasoning agent; if it dies, mesh auto-rewires to the API. When Claude recovers, mesh rewires back. No deploy, no config, no code change.

???+ example "See how the Claude-powered weather agent is built (10 lines)"
    ```python
    from fastmcp import FastMCP
    import mesh

    app = FastMCP("ClaudeWeather")

    @app.tool()
    @mesh.llm(
        system_prompt="file://prompts/weather.j2",
        provider={"capability": "llm", "tags": ["+claude"]},
    )
    @mesh.tool(capability="weather", tags=["+claude"])
    def weather(destination: str, dates: str,
                llm: mesh.MeshLlmAgent = None) -> Forecast:
        return llm(f"Forecast for {destination} on {dates}")

    @mesh.agent(name="claude-weather", auto_run=True)
    class Agent: pass
    ```

    The LLM orchestrates tools via the mesh `filter` pattern and returns a typed pydantic `Forecast` — no agentic loop to write.

??? example "Route by Python if/else, not config"
    ```python
    # Two providers of the same capability, wired at runtime
    weather = reasoning_weather if user.wants_explanation else api_weather
    forecast = await weather(destination, dates)
    ```

**[See the full TripPlanner tutorial →](https://mcp-mesh.ai/tutorial/)**

---

## :zap: Getting Started

Start with the CLI — fastest way to explore mesh, scaffold agents, and read documentation offline.

`meshctl` is a fully-featured command-line tool that follows you from your first agent through production and beyond: scaffolding, local dev, registry inspection, tracing, observability, deployment, and operations are all one command away. [Explore the full CLI reference →](cli/index.md)

```bash
# Install the CLI
npm install -g @mcpmesh/cli

# Explore commands
meshctl --help

# Built-in documentation
meshctl man
```

!!! tip "Turn your AI coding assistant into a mesh expert"
    Working with Claude Code, Cursor, Copilot, or any other AI coding assistant? Ask it to run `meshctl man` and read through the topics it surfaces. The built-in man pages cover every feature in depth — within a few minutes your assistant will be fluent in mesh, ready to scaffold agents, debug DDDI wiring, and answer architecture questions without you having to copy-paste docs into the chat.

<!-- No `---` above the mount on purpose: a 1px rule reads as "next section"
     punctuation, and the band announces itself far more loudly than a rule
     can. The separation is done with margin on #mesh-scroll in embed.css. -->
<!-- Scroll-driven topology section. The stylesheet is loaded eagerly by
     docs/overrides/home.html's extrahead block; the bundle is lazy, and the
     loader below sits beside the mount deliberately — in home.html it rendered
     in {% block tabs %}, BEFORE this content block, so `document.getElementById`
     returned null and the loader silently no-opped. Ordering is now structural
     rather than defensive. Rebuild with `make docs-scroll-build`. -->
<!-- The copy is INCLUDED, not written here: src/ui/demo/copy.generated.html is
     rendered from src/ui/demo/script.ts by the same build step that prerenders
     the animation, so the fourteen beats and the epilogue are in the served
     document and cannot drift from what the animation says. `make
     docs-scroll-prerender` rewrites it; CI fails on any difference.

     The skip link is first, and it is the only hand-written markup inside the
     mount. The bundle replaces everything in here on mount, so demo/static.ts
     lifts both it and the copy blocks out and puts them back.

     It is written unconditionally and GATED IN CSS on the arming class, since
     the served document cannot know whether the animation will run: unarmed,
     there is no scrolling story to skip and the offer would send a keyboard
     reader past the prose itself. See the rule in demo/embed.css. -->
<div id="mesh-scroll">
<a class="mesh-skip" data-mesh-skip href="#mesh-scroll-end">Skip the scrolling story</a>
--8<-- "src/ui/demo/copy.generated.html"
</div>
<div id="mesh-scroll-end" tabindex="-1"></div>

<script>
  /* Lazy-loads the bundle one viewport ahead of the section. No line comments
     and fully semicolon-terminated: mkdocs-minify runs with minify_html, and a
     minifier that collapsed newlines would swallow the rest of a // line. */
  (function () {
    "use strict";
    var el = document.getElementById("mesh-scroll");
    if (!el) { return; }
    /* 900px MUST match MIN_WIDTH in src/ui/vite.demo.config.ts, which gates
       the reserved min-height on the same query and is shared by both bundle
       configs. Below it the bundle is never fetched, the height is never
       reserved and the section is not rendered, rather than 185KB rendering a
       graph at ~0.23 zoom above 2205vh of pinned scroll. This is not a mobile
       fallback; it is declining to ship a known-broken one. */
    var wide = window.matchMedia("(min-width: 900px)");
    var src = "assets/mesh-scroll/mesh-scroll.js";
    var loaded = false;
    var armed = false;
    var load = function () {
      if (loaded) { return; }
      loaded = true;
      var s = document.createElement("script");
      s.src = src;
      s.defer = true;
      /* If the bundle cannot load, disarm: the reservation goes away and the
         section reverts to the copy it is already carrying, as linear prose.
         Covers CDN failure, a CSP block and a dropped connection.
         JavaScript disabled entirely needs no handling at all now, which is the
         point of arming rather than reserving unconditionally: this loader
         never runs, the class is never added, and the reservation was never
         applied. */
      s.onerror = function () {
        el.classList.remove("mesh-scroll-armed");
      };
      document.body.appendChild(s);
    };
    var arm = function () {
      if (armed || !wide.matches) { return; }
      armed = true;
      /* RESERVE THE HEIGHT, and do it here rather than in a base stylesheet
         rule. This runs inline, at parse time, before the section has been laid
         out — so the reservation still lands before first paint and a reader
         with JavaScript sees no shift. What changes is the reader who does NOT
         have JavaScript: nothing arms, no height is reserved, and the copy this
         section carries reads as ordinary prose instead of being buried under
         twenty-two empty screens. The class also swaps the section's pre-mount
         view to the opening beat alone. */
      el.className += " mesh-scroll-armed";
      if (!("IntersectionObserver" in window)) { load(); return; }
      var io = new IntersectionObserver(function (entries) {
        var i;
        for (i = 0; i < entries.length; i += 1) {
          if (entries[i].isIntersecting) { io.disconnect(); load(); return; }
        }
      }, { rootMargin: "100% 0px" });
      io.observe(el);
    };
    if (wide.addEventListener) { wide.addEventListener("change", arm); }
    arm();
  })();
</script>

<div class="center" markdown>

**Ready to get started?**

[Python SDK](python/getting-started/index.md){ .md-button .md-button--primary }
[Java SDK](java/getting-started/index.md){ .md-button .md-button--primary }
[TypeScript SDK](typescript/getting-started/index.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/dhyansraj/mcp-mesh){ .md-button }

[YouTube](https://www.youtube.com/@MCPMesh){ .md-button }
[Discord](https://discord.gg/KDFDREphWn){ .md-button }

**Star the repo** if MCP Mesh helps you build better AI systems! :star:

</div>
