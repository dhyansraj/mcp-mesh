#!/usr/bin/env python3
"""
Generate MkDocs documentation from meshctl man pages.

This script reads the markdown source files from src/core/cli/man/content/
and generates MkDocs-compatible documentation in docs/python/, docs/java/,
and docs/typescript/.

Usage:
    python scripts/generate_docs_from_man.py

The script will:
1. Read source markdown files from Go project
2. Generate MkDocs pages with proper frontmatter and cross-references
3. Create navigation-friendly directory structure (overwrites only managed files)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Project root (relative to this script)
PROJECT_ROOT = Path(__file__).parent.parent
MAN_CONTENT_DIR = PROJECT_ROOT / "src" / "core" / "cli" / "man" / "content"
DOCS_DIR = PROJECT_ROOT / "docs"


# Guide metadata (mirrors content.go guideRegistry)
@dataclass
class Guide:
    name: str
    aliases: list[str]
    title: str
    description: str
    has_typescript_variant: bool = False
    has_java_variant: bool = False
    # Mapping to docs structure
    python_path: Optional[str] = None  # e.g., "getting-started/index.md"
    typescript_path: Optional[str] = None  # e.g., "getting-started/index.md"
    java_path: Optional[str] = None  # e.g., "getting-started/index.md"
    python_only: bool = False  # e.g., fastapi
    typescript_only: bool = False  # e.g., express
    java_only: bool = False  # e.g., spring-boot


# Guide registry - mirrors Go content.go with doc path mappings
GUIDES = [
    Guide(
        name="quickstart",
        aliases=["quick", "start", "hello"],
        title="Quick Start",
        description="Get started with MCP Mesh in minutes",
        has_typescript_variant=True,
        has_java_variant=True,
        python_path="getting-started/index.md",
        typescript_path="getting-started/index.md",
        java_path="getting-started/index.md",
    ),
    Guide(
        name="prerequisites",
        aliases=["prereq", "setup", "install"],
        title="Prerequisites",
        description="System requirements for Python, Java, and TypeScript development",
        has_typescript_variant=True,
        has_java_variant=True,
        python_path="getting-started/prerequisites.md",
        typescript_path="getting-started/prerequisites.md",
        java_path="getting-started/prerequisites.md",
    ),
    Guide(
        name="overview",
        aliases=["architecture", "arch"],
        title="Architecture Overview",
        description="Core architecture, agent coordination, and design philosophy",
        has_typescript_variant=False,
        has_java_variant=False,
        # Shared - goes to concepts, not SDK-specific
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="capabilities",
        aliases=["caps"],
        title="Capabilities",
        description="Named services that agents provide",
        has_typescript_variant=True,
        has_java_variant=True,
        python_path="capabilities-tags.md",
        typescript_path="capabilities-tags.md",
        java_path="capabilities-tags.md",
    ),
    Guide(
        name="tags",
        aliases=["tag-matching"],
        title="Tag Matching",
        description="Tag system with +/- operators for smart service selection",
        has_typescript_variant=True,
        has_java_variant=True,
        # Merged with capabilities
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="decorators",
        aliases=["decorator"],
        title="Decorators",
        description="Python decorators for mesh services",
        has_typescript_variant=True,
        has_java_variant=True,
        python_path="decorators.md",
        typescript_path="mesh-functions.md",
        java_path="annotations.md",
    ),
    Guide(
        name="dependency-injection",
        aliases=["di", "injection"],
        title="Dependency Injection",
        description="How DI works, proxy creation, and automatic wiring",
        has_typescript_variant=True,
        has_java_variant=True,
        python_path="dependency-injection.md",
        typescript_path="dependency-injection.md",
        java_path="dependency-injection.md",
    ),
    Guide(
        name="health",
        aliases=["health-checks", "heartbeat"],
        title="Health & Auto-Rewiring",
        description="Heartbeat system, health checks, and automatic topology updates",
        has_typescript_variant=True,
        has_java_variant=True,
        # Shared concept - not SDK specific
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="registry",
        aliases=["reg"],
        title="Registry",
        description="Registry role, agent registration, and dependency resolution",
        has_typescript_variant=False,
        has_java_variant=False,
        # Shared concept
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="llm",
        aliases=["llm-integration"],
        title="LLM Integration",
        description="LLM agents and tool filtering",
        has_typescript_variant=True,
        has_java_variant=True,
        python_path="llm/index.md",
        typescript_path="llm/index.md",
        java_path="llm/index.md",
    ),
    Guide(
        name="proxies",
        aliases=["proxy", "communication"],
        title="Proxy System",
        description="Inter-agent communication, proxy types, and configuration",
        has_typescript_variant=True,
        has_java_variant=True,
        # Advanced concept - not in main SDK docs
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="fastapi",
        aliases=["backend"],
        title="FastAPI Integration",
        description="@mesh.route for FastAPI backends",
        has_typescript_variant=False,
        has_java_variant=False,
        python_only=True,
        python_path="fastapi-integration.md",
    ),
    Guide(
        name="express",
        aliases=["route", "routes"],
        title="Express Integration",
        description="mesh.route() for Express backends",
        has_typescript_variant=False,
        has_java_variant=False,
        typescript_only=True,
        typescript_path="express-integration.md",
    ),
    Guide(
        name="spring-boot",
        aliases=["springboot"],
        title="Spring Boot Integration",
        description="@MeshRoute for Spring Boot REST backends",
        has_typescript_variant=False,
        has_java_variant=False,
        java_only=True,
        java_path="spring-boot-integration.md",
    ),
    Guide(
        name="environment",
        aliases=["env", "config"],
        title="Environment Variables",
        description="Configuration via environment variables",
        has_typescript_variant=False,
        has_java_variant=False,
        # Shared - referenced from both
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="deployment",
        aliases=["deploy"],
        title="Deployment",
        description="Local, Docker, and Kubernetes deployment",
        has_typescript_variant=True,
        has_java_variant=True,
        # Goes to deployment section, not SDK
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="testing",
        aliases=["curl", "mcp-api"],
        title="Testing",
        description="Testing agents with curl, MCP JSON-RPC syntax",
        has_typescript_variant=True,
        has_java_variant=True,
        python_path="examples.md",
        typescript_path="examples.md",
        java_path="examples.md",
    ),
    Guide(
        name="scaffold",
        aliases=["scaffolding", "generate", "gen", "new"],
        title="Scaffolding",
        description="Generate agents with meshctl scaffold",
        has_typescript_variant=False,
        has_java_variant=False,
        # CLI topic
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="cli",
        aliases=["commands", "call", "list", "status"],
        title="CLI Commands",
        description="meshctl call, list, status for development and testing",
        has_typescript_variant=False,
        has_java_variant=False,
        # CLI topic
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
    Guide(
        name="observability",
        aliases=["tracing", "monitoring", "tempo", "grafana"],
        title="Observability",
        description="Distributed tracing, Grafana dashboards, and monitoring",
        has_typescript_variant=False,
        has_java_variant=False,
        # Shared observability section
        python_path=None,
        typescript_path=None,
        java_path=None,
    ),
]


def read_man_page(name: str, runtime: str = "python") -> Optional[str]:
    """Read a man page source file."""
    if runtime == "java":
        filename = f"{name}_java.md"
    elif runtime == "typescript":
        filename = f"{name}_typescript.md"
    else:
        filename = f"{name}.md"

    filepath = MAN_CONTENT_DIR / filename
    if not filepath.exists():
        if runtime != "python":
            # Fall back to Python version
            return read_man_page(name, runtime="python")
        return None

    return filepath.read_text()


def generate_frontmatter(guide: Guide, runtime: str) -> str:
    """Generate MkDocs frontmatter."""
    title = guide.title
    if runtime == "python":
        title = f"{guide.title} (Python)"
    elif runtime == "java":
        title = f"{guide.title} (Java)"
    elif runtime == "typescript":
        title = f"{guide.title} (TypeScript)"

    return f"""---
title: {title}
description: {guide.description}
---

"""


def generate_crossref_banner(guide: Guide, runtime: str) -> str:
    """Generate cross-reference banner for runtime switching."""
    links = []

    if runtime != "python" and guide.python_path and not guide.python_only:
        path = f"../../python/{guide.python_path.replace('.md', '/')}"
        links.append(('🐍', f'Looking for Python? See <a href="{path}">Python {guide.title}</a>'))

    if runtime != "java" and guide.java_path and not guide.java_only:
        path = f"../../java/{guide.java_path.replace('.md', '/')}"
        links.append(('☕', f'Looking for Java? See <a href="{path}">Java {guide.title}</a>'))

    if runtime != "typescript" and guide.typescript_path and not guide.typescript_only:
        path = f"../../typescript/{guide.typescript_path.replace('.md', '/')}"
        links.append(('📘', f'Looking for TypeScript? See <a href="{path}">TypeScript {guide.title}</a>'))

    if not links:
        return ""

    parts = []
    for icon, text in links:
        parts.append(f'  <span class="runtime-crossref-icon">{icon}</span>\n  <span>{text}</span>')

    separators = '\n  <span> | </span>\n'.join(parts)
    return f'<div class="runtime-crossref">\n{separators}\n</div>\n\n'


def process_content(content: str, guide: Guide, runtime: str) -> str:
    """Process man page content for MkDocs."""
    # Remove the "See also: meshctl man X --typescript" footer if present
    # (we're adding our own cross-reference banner)
    lines = content.split("\n")
    processed_lines = []
    skip_footer = False

    for i, line in enumerate(lines):
        if line.strip().startswith("**See also:**") and "meshctl man" in line:
            skip_footer = True
            # Look ahead: if next line is not blank, reset skip_footer
            # to preserve subsequent non-footer content
            if i + 1 < len(lines) and lines[i + 1].strip() != "":
                skip_footer = False
            continue
        if skip_footer and line.strip() == "":
            skip_footer = False
            continue
        if not skip_footer:
            processed_lines.append(line)

    return "\n".join(processed_lines)


def generate_doc(guide: Guide, runtime: str) -> Optional[str]:
    """Generate a complete doc page."""
    # Determine source file
    if runtime == "java":
        use_runtime = "java" if guide.has_java_variant else "python"
    elif runtime == "typescript":
        use_runtime = "typescript" if guide.has_typescript_variant else "python"
    else:
        use_runtime = "python"

    content = read_man_page(guide.name, runtime=use_runtime)
    if content is None:
        print(f"  Warning: No source file for {guide.name}")
        return None

    # Build the doc
    doc = ""

    # Add cross-reference banner (if at least one other runtime has this page)
    other_paths = []
    if runtime != "python" and guide.python_path:
        other_paths.append("python")
    if runtime != "java" and guide.java_path:
        other_paths.append("java")
    if runtime != "typescript" and guide.typescript_path:
        other_paths.append("typescript")

    if other_paths and not getattr(guide, f'{runtime}_only', False):
        doc += generate_crossref_banner(guide, runtime)

    # Add processed content
    doc += process_content(content, guide, runtime)

    return doc


def ensure_dir(path: Path) -> None:
    """Ensure directory exists."""
    path.mkdir(parents=True, exist_ok=True)


def generate_sdk_index(runtime: str) -> str:
    """Generate the SDK index page."""
    if runtime == "python":
        return """# Python SDK

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See the <a href="../../java/">Java SDK</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See the <a href="../../typescript/">TypeScript SDK</a></span>
</div>

> Build distributed MCP agents with Python decorators and zero boilerplate

## Overview

The MCP Mesh Python SDK provides a decorator-based API for building distributed agent systems. Combined with FastMCP, you get:

- **`@mesh.tool`** - Register capabilities with dependency injection
- **`@mesh.agent`** - Configure agent servers with auto-run
- **`@mesh.llm`** - LLM-powered tools with automatic tool discovery
- **`@mesh.llm_provider`** - Zero-code LLM providers via LiteLLM
- **`@mesh.route`** - FastAPI routes with mesh DI

## Installation

```bash
# Install the SDK
pip install mcp-mesh

# Install the CLI (required for development)
npm install -g @mcpmesh/cli
```

## Quick Start

```bash
# View the quick start guide
meshctl man quickstart

# Or scaffold a new agent
meshctl scaffold --name my-agent
```

## Documentation

For comprehensive documentation, use the built-in man pages:

```bash
meshctl man --list              # List all topics
meshctl man <topic>             # View a topic
meshctl man <topic> --raw       # Get markdown output (LLM-friendly)
```

## Key Topics

| Topic | Command | Description |
|-------|---------|-------------|
| Quick Start | `meshctl man quickstart` | Get started in minutes |
| Decorators | `meshctl man decorators` | @mesh.tool, @mesh.agent, @mesh.llm |
| Dependency Injection | `meshctl man di` | How DI works |
| LLM Integration | `meshctl man llm` | Build AI-powered agents |
| Deployment | `meshctl man deployment` | Local, Docker, Kubernetes |

## Next Steps

<div class="grid-features">
<div class="feature-card recommended">
  <h3>Quick Start</h3>
  <p>Get your first agent running in 5 minutes</p>
  <a href="getting-started/">Start Tutorial →</a>
</div>
<div class="feature-card">
  <h3>Decorators Reference</h3>
  <p>Complete API reference for all decorators</p>
  <a href="decorators/">View Reference →</a>
</div>
<div class="feature-card">
  <h3>LLM Integration</h3>
  <p>Build AI-powered agents</p>
  <a href="llm/">Learn More →</a>
</div>
</div>
"""
    elif runtime == "java":
        return """# Java SDK

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See the <a href="../../python/">Python SDK</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See the <a href="../../typescript/">TypeScript SDK</a></span>
</div>

> Build distributed MCP agents with Java annotations and zero boilerplate

## Overview

The MCP Mesh Java SDK provides an annotation-based API for building distributed agent systems:

- **`@MeshAgent`** - Configure agent servers with auto-run
- **`@MeshTool`** - Register capabilities with dependency injection
- **`@MeshLlm`** - LLM-powered tools with automatic tool discovery
- **`@MeshLlmProvider`** - Zero-code LLM providers via LiteLLM
- **`@MeshRoute`** - Spring Boot routes with mesh DI

## Installation

```xml
<!-- Add to your pom.xml -->
<dependency>
    <groupId>io.mcpmesh</groupId>
    <artifactId>mcp-mesh</artifactId>
    <version>LATEST</version>
</dependency>
```

```bash
# Install the CLI (required for development)
npm install -g @mcpmesh/cli
```

## Quick Start

```bash
# View the quick start guide
meshctl man quickstart --java

# Or scaffold a new agent
meshctl scaffold --name my-agent --lang java
```

## Documentation

For comprehensive documentation, use the built-in man pages:

```bash
meshctl man --list              # List all topics
meshctl man <topic> --java      # View Java version
meshctl man <topic> --java --raw  # Get markdown output (LLM-friendly)
```

## Key Topics

| Topic | Command | Description |
|-------|---------|-------------|
| Quick Start | `meshctl man quickstart --java` | Get started in minutes |
| Annotations | `meshctl man decorators --java` | @MeshTool, @MeshAgent, @MeshLlm |
| Dependency Injection | `meshctl man di --java` | How DI works |
| LLM Integration | `meshctl man llm --java` | Build AI-powered agents |
| Deployment | `meshctl man deployment --java` | Local, Docker, Kubernetes |

## Next Steps

<div class="grid-features">
<div class="feature-card recommended">
  <h3>Quick Start</h3>
  <p>Get your first agent running in 5 minutes</p>
  <a href="getting-started/">Start Tutorial →</a>
</div>
<div class="feature-card">
  <h3>Annotations Reference</h3>
  <p>Complete API reference for all annotations</p>
  <a href="annotations/">View Reference →</a>
</div>
<div class="feature-card">
  <h3>LLM Integration</h3>
  <p>Build AI-powered agents</p>
  <a href="llm/">Learn More →</a>
</div>
</div>
"""
    else:  # typescript
        return """# TypeScript SDK

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See the <a href="../../python/">Python SDK</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See the <a href="../../java/">Java SDK</a></span>
</div>

> Build distributed MCP agents with TypeScript and zero boilerplate

## Overview

The MCP Mesh TypeScript SDK provides a function-based API for building distributed agent systems:

- **`mesh()`** - Wrap FastMCP with mesh capabilities
- **`agent.addTool()`** - Register tools with capabilities and tags
- **`mesh.llm()`** - Create LLM-powered tools
- **`agent.addLlmProvider()`** - Zero-code LLM providers

## Installation

```bash
# Install the SDK
npm install @mcpmesh/sdk

# Install the CLI (if not already installed)
npm install -g @mcpmesh/cli
```

## Quick Start

```bash
# View the quick start guide
meshctl man quickstart --typescript

# Or scaffold a new agent
meshctl scaffold --name my-agent --lang typescript
```

## Documentation

For comprehensive documentation, use the built-in man pages:

```bash
meshctl man --list                      # List all topics
meshctl man <topic> --typescript        # View TypeScript version
meshctl man <topic> --typescript --raw  # Get markdown output
```

## Key Topics

| Topic | Command | Description |
|-------|---------|-------------|
| Quick Start | `meshctl man quickstart --typescript` | Get started in minutes |
| Mesh Functions | `meshctl man decorators --typescript` | mesh(), addTool(), mesh.llm() |
| Dependency Injection | `meshctl man di --typescript` | How DI works |
| LLM Integration | `meshctl man llm --typescript` | Build AI-powered agents |
| Deployment | `meshctl man deployment --typescript` | Local, Docker, Kubernetes |

## Next Steps

<div class="grid-features">
<div class="feature-card recommended">
  <h3>Quick Start</h3>
  <p>Get your first agent running in 5 minutes</p>
  <a href="getting-started/">Start Tutorial →</a>
</div>
<div class="feature-card">
  <h3>Mesh Functions Reference</h3>
  <p>Complete API reference</p>
  <a href="mesh-functions/">View Reference →</a>
</div>
<div class="feature-card">
  <h3>LLM Integration</h3>
  <p>Build AI-powered agents</p>
  <a href="llm/">Learn More →</a>
</div>
</div>
"""


def main():
    print("=" * 60)
    print("Generating MkDocs documentation from meshctl man pages")
    print("=" * 60)

    # Check source directory exists
    if not MAN_CONTENT_DIR.exists():
        print(f"Error: Source directory not found: {MAN_CONTENT_DIR}")
        return 1

    print(f"\nSource: {MAN_CONTENT_DIR}")
    print(f"Output: {DOCS_DIR}/python/, {DOCS_DIR}/java/, and {DOCS_DIR}/typescript/")

    # Generate docs for each runtime
    for runtime in ["python", "java", "typescript"]:
        print(f"\n{'=' * 40}")
        print(f"Generating {runtime.upper()} docs")
        print("=" * 40)

        runtime_dir = DOCS_DIR / runtime
        ensure_dir(runtime_dir)

        # Generate SDK index page
        index_content = generate_sdk_index(runtime)
        index_path = runtime_dir / "index.md"
        index_path.write_text(index_content)
        print(f"  Created: {index_path.relative_to(DOCS_DIR)}")

        # Generate pages for each guide
        for guide in GUIDES:
            # Determine output path
            if runtime == "python":
                if guide.typescript_only or guide.java_only:
                    continue
                output_path = guide.python_path
            elif runtime == "java":
                if guide.python_only or guide.typescript_only:
                    continue
                output_path = guide.java_path
            else:
                if guide.python_only or guide.java_only:
                    continue
                output_path = guide.typescript_path

            if output_path is None:
                continue

            # Generate the doc
            doc = generate_doc(guide, runtime)
            if doc is None:
                continue

            # Write the file
            output_file = runtime_dir / output_path
            ensure_dir(output_file.parent)
            output_file.write_text(doc)
            print(f"  Created: {output_file.relative_to(DOCS_DIR)}")

    print("\n" + "=" * 60)
    print("Done! Run 'mkdocs serve' to preview the documentation.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    exit(main())
