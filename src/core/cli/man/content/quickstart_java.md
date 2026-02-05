# Quick Start

> Get started with MCP Mesh in minutes (Java/Spring Boot)

## Prerequisites

```bash
# Java 17+
java --version

# Maven
mvn --version

# Create project directory
mkdir my-mesh-project && cd my-mesh-project
```

## 1. Start the Registry

```bash
# Terminal 1: Start registry
meshctl start --registry-only --debug
```

## 2. Create Your First Agent

Create `GreeterAgentApplication.java`:

```java
package com.example.greeter;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(name = "greeter", version = "1.0.0",
           description = "Simple greeting service", port = 8080)
@SpringBootApplication
public class GreeterAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(GreeterAgentApplication.class, args);
    }

    @MeshTool(capability = "greeting",
              description = "Greet a user by name",
              tags = {"greeting", "utility", "java"})
    public GreetingResponse greet(
            @Param(value = "name", description = "The name to greet") String name) {
        return new GreetingResponse("Hello, " + name + "!");
    }

    record GreetingResponse(String message) {}
}
```

## 3. Add the Maven Dependency

Create `pom.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>4.0.2</version>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>greeter-agent</artifactId>
    <version>1.0.0</version>

    <dependencies>
        <dependency>
            <groupId>io.mcp-mesh</groupId>
            <artifactId>mcp-mesh-spring-boot-starter</artifactId>
            <version>0.9.0-beta.10</version>
        </dependency>
    </dependencies>
</project>
```

## 4. Build and Run

```bash
# Option A: Run directly with Maven
cd greeter
mvn spring-boot:run

# Option B: Use meshctl (auto-detects pom.xml)
meshctl start examples/java/basic-tool-agent --debug
```

`meshctl start` can start Java agents by pointing at a directory containing a `pom.xml`, a `.java` file, or a `.jar` file. For Maven projects, it runs `mvn spring-boot:run -q` under the hood.

## 5. Test the Agent

```bash
# Terminal 3: Call the agent
meshctl call greeter greeting --params '{"name": "World"}'
# Output: {"message": "Hello, World!"}

# List running agents
meshctl list
```

## 6. Add a Dependency

Create a second agent that depends on the greeter:

```java
package com.example.assistant;

import io.mcpmesh.*;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(name = "assistant", version = "1.0.0",
           description = "Assistant with mesh dependencies", port = 9001)
@SpringBootApplication
public class AssistantAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(AssistantAgentApplication.class, args);
    }

    @MeshTool(capability = "smart_greeting",
              description = "Enhanced greeting via mesh",
              tags = {"greeting", "assistant", "java"},
              dependencies = @Selector(capability = "greeting"))
    public GreetingResponse smartGreet(
            @Param(value = "name", description = "The name to greet") String name,
            McpMeshTool<String> greeting) {

        if (greeting != null && greeting.isAvailable()) {
            String baseGreeting = greeting.call("name", name);
            return new GreetingResponse(baseGreeting + " Welcome to MCP Mesh!");
        }
        return new GreetingResponse("Hello, " + name + "! (greeter unavailable)");
    }

    record GreetingResponse(String message) {}
}
```

```bash
# Start the assistant
meshctl start examples/java/dependency-agent --debug

# Call the smart greeting
meshctl call assistant smart_greeting --params '{"name": "Developer"}'
# Output: {"message": "Hello, Developer! Welcome to MCP Mesh!"}
```

## Next Steps

- `meshctl man decorators --java` - Learn all mesh annotations
- `meshctl man llm --java` - Add LLM capabilities
- `meshctl man capabilities --java` - Capabilities system
- `meshctl man dependency-injection --java` - How DI works

## See Also

- `meshctl scaffold --help` - All scaffold options
- `meshctl man prerequisites` - Full setup guide
