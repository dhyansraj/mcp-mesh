# Getting Started (Java)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">&#x1F40D;</span>
  <span>Looking for Python? See <a href="../../../python/local-development/01-getting-started/">Python Getting Started</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">&#x1F4D8;</span>
  <span>Looking for TypeScript? See <a href="../../../typescript/local-development/01-getting-started/">TypeScript Getting Started</a></span>
</div>

> Install meshctl CLI and set up a Java project

## Prerequisites

- **Node.js 18+** - for meshctl CLI
- **Java 17+** - for agent development
- **Maven 3.9+** - for building

## Install meshctl CLI

```bash
npm install -g @mcpmesh/cli

# Verify
meshctl --version
```

## Set Up a Java Project

The recommended way is to use `meshctl scaffold` (see next page). If you prefer manual setup, add the Spring Boot starter to your `pom.xml`:

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>4.0.2</version>
    <relativePath/>
</parent>

<properties>
    <java.version>17</java.version>
</properties>

<dependencies>
    <dependency>
        <groupId>io.mcp-mesh</groupId>
        <artifactId>mcp-mesh-spring-boot-starter</artifactId>
        <version>0.9.0-beta.10</version>
    </dependency>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
</dependencies>

<build>
    <plugins>
        <plugin>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-maven-plugin</artifactId>
        </plugin>
    </plugins>
</build>
```

## Quick Start

```bash
# 1. Scaffold an agent (interactive wizard)
meshctl scaffold

# 2. Edit the generated Application.java to add your tool logic

# 3. Run agent
meshctl start hello/ --debug
```

The scaffolded code includes placeholder tools -- edit the `@MeshTool` methods to add your logic.

## Next Steps

Continue to [Scaffold Agents](./02-scaffold.md) ->
