package handlers

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

// JavaHandler implements LanguageHandler for Java/Spring Boot agents
type JavaHandler struct{}

// Language returns the language identifier
func (h *JavaHandler) Language() string {
	return "java"
}

// CanHandle checks if the given path is a Java file, JAR, or Maven project
func (h *JavaHandler) CanHandle(path string) bool {
	lowerPath := strings.ToLower(path)
	// Handle .jar files
	if strings.HasSuffix(lowerPath, ".jar") {
		return true
	}
	// Handle .java files
	if strings.HasSuffix(lowerPath, ".java") {
		return true
	}
	// Handle directories with pom.xml
	if info, err := os.Stat(path); err == nil && info.IsDir() {
		return fileExists(filepath.Join(path, "pom.xml"))
	}
	// Handle pom.xml directly
	if filepath.Base(lowerPath) == "pom.xml" {
		return true
	}
	return false
}

// DetectInDirectory checks if the directory contains Java/Maven markers
func (h *JavaHandler) DetectInDirectory(dir string) bool {
	// Use shared LanguageMarkers map
	for _, marker := range LanguageMarkers["java"] {
		if fileExists(filepath.Join(dir, marker)) {
			return true
		}
	}
	// Also check for .java files in src/main/java
	srcJavaDir := filepath.Join(dir, "src", "main", "java")
	if info, err := os.Stat(srcJavaDir); err == nil && info.IsDir() {
		return true
	}
	return false
}

// GetTemplates returns Java agent templates
func (h *JavaHandler) GetTemplates() map[string]string {
	return map[string]string{
		"pom.xml":                                     javaPomTemplate,
		"src/main/java/com/example/agent/Agent.java": javaMainTemplate,
		"Dockerfile":                                  h.GenerateDockerfile(),
	}
}

// GenerateAgent generates Java agent files
func (h *JavaHandler) GenerateAgent(config ScaffoldConfig) error {
	// Create output directory
	if err := os.MkdirAll(config.OutputDir, 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	// For now, return an error indicating scaffolding is not yet implemented
	return fmt.Errorf("Java agent scaffolding not yet implemented - use examples/java as templates")
}

// GenerateDockerfile returns Java Dockerfile content
func (h *JavaHandler) GenerateDockerfile() string {
	return `# Dockerfile for MCP Mesh Java agent
FROM eclipse-temurin:17-jdk-jammy

WORKDIR /app

# Copy Maven wrapper and pom.xml
COPY .mvn/ .mvn/
COPY mvnw pom.xml ./

# Download dependencies
RUN ./mvnw dependency:resolve -q

# Copy source code
COPY src/ src/

# Build the application
RUN ./mvnw package -DskipTests -q

# Run the agent
CMD ["java", "-jar", "target/*.jar"]
`
}

// GenerateHelmValues returns Java-specific Helm values
func (h *JavaHandler) GenerateHelmValues() map[string]interface{} {
	return map[string]interface{}{
		"runtime": "java",
		"image": map[string]interface{}{
			"repository": "eclipse-temurin",
			"tag":        "17-jdk-jammy",
		},
		"command": []string{"java", "-jar", "target/*.jar"},
	}
}

// ParseAgentFile extracts agent info from a Java file or pom.xml
func (h *JavaHandler) ParseAgentFile(path string) (*AgentInfo, error) {
	info := &AgentInfo{}

	// If it's a directory, look for pom.xml
	if stat, err := os.Stat(path); err == nil && stat.IsDir() {
		path = filepath.Join(path, "pom.xml")
	}

	// Try to extract from pom.xml
	if strings.HasSuffix(path, "pom.xml") {
		content, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("failed to read pom.xml: %w", err)
		}

		// Extract artifactId as name
		artifactIdRe := regexp.MustCompile(`<artifactId>([^<]+)</artifactId>`)
		if matches := artifactIdRe.FindSubmatch(content); len(matches) > 1 {
			info.Name = string(matches[1])
		}

		// Extract version
		versionRe := regexp.MustCompile(`<version>([^<]+)</version>`)
		if matches := versionRe.FindSubmatch(content); len(matches) > 1 {
			info.Version = string(matches[1])
		}
	}

	// Fall back to directory name if name not found
	if info.Name == "" {
		info.Name = filepath.Base(filepath.Dir(path))
	}

	return info, nil
}

// GetDockerImage returns the Java runtime Docker image
func (h *JavaHandler) GetDockerImage() string {
	return "eclipse-temurin:17-jdk-jammy"
}

// ValidatePrerequisites checks Java environment
func (h *JavaHandler) ValidatePrerequisites(dir string) error {
	// Check for Java
	javaVersion, err := getJavaVersion()
	if err != nil {
		return fmt.Errorf("java not found: %w. Install JDK 17+ from https://adoptium.net/", err)
	}

	// Check Java version is 17+
	if javaVersion < 17 {
		return fmt.Errorf("java version %d found, but Java 17+ is required. Install JDK 17+ from https://adoptium.net/", javaVersion)
	}

	// Check for Maven (required for Spring Boot agents)
	if _, err := exec.LookPath("mvn"); err != nil {
		return fmt.Errorf("mvn not found. Install Maven from https://maven.apache.org/")
	}

	// Check for pom.xml in directory
	pomPath := filepath.Join(dir, "pom.xml")
	if !fileExists(pomPath) {
		// Check if it's a JAR file (doesn't need pom.xml)
		entries, _ := os.ReadDir(dir)
		hasJar := false
		for _, entry := range entries {
			if strings.HasSuffix(entry.Name(), ".jar") {
				hasJar = true
				break
			}
		}
		if !hasJar {
			return fmt.Errorf("pom.xml not found in %s. MCP Mesh Java agents require a Maven project", dir)
		}
	}

	return nil
}

// getJavaVersion returns the major Java version (e.g., 17, 21)
func getJavaVersion() (int, error) {
	cmd := exec.Command("java", "-version")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return 0, err
	}

	// Parse version from output like:
	// openjdk version "17.0.13" 2024-10-15
	// or: java version "1.8.0_291"
	outputStr := string(output)
	versionRe := regexp.MustCompile(`version "(\d+)(?:\.(\d+))?`)
	matches := versionRe.FindStringSubmatch(outputStr)
	if len(matches) < 2 {
		return 0, fmt.Errorf("could not parse Java version from: %s", outputStr)
	}

	majorVersion, err := strconv.Atoi(matches[1])
	if err != nil {
		return 0, fmt.Errorf("invalid Java version number: %s", matches[1])
	}

	// Handle old versioning (1.8 = Java 8)
	if majorVersion == 1 && len(matches) > 2 {
		minorVersion, _ := strconv.Atoi(matches[2])
		return minorVersion, nil
	}

	return majorVersion, nil
}

// GetStartCommand returns the command to start a Java agent
func (h *JavaHandler) GetStartCommand(file string) []string {
	// If it's a JAR file, use java -jar
	if strings.HasSuffix(strings.ToLower(file), ".jar") {
		return []string{"java", "-jar", file}
	}

	// For directories or pom.xml, use mvn spring-boot:run
	// The working directory should be set to the project root
	return []string{"mvn", "spring-boot:run", "-q"}
}

// GetEnvironment returns Java-specific environment variables
func (h *JavaHandler) GetEnvironment() map[string]string {
	return map[string]string{
		// Disable Spring Boot banner for cleaner output
		"SPRING_MAIN_BANNER_MODE": "off",
	}
}

// FindProjectRoot walks up from the given path to find the Maven project root (directory containing pom.xml)
func (h *JavaHandler) FindProjectRoot(startPath string) (string, error) {
	// If startPath is a file, start from its directory
	info, err := os.Stat(startPath)
	if err != nil {
		return "", err
	}

	dir := startPath
	if !info.IsDir() {
		dir = filepath.Dir(startPath)
	}

	// Walk up looking for pom.xml
	for {
		pomPath := filepath.Join(dir, "pom.xml")
		if fileExists(pomPath) {
			return dir, nil
		}

		// Move up one directory
		parent := filepath.Dir(dir)
		if parent == dir {
			// Reached root
			return "", fmt.Errorf("no pom.xml found in parent directories of %s", startPath)
		}
		dir = parent
	}
}

// Template constants
const javaPomTemplate = `<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.0</version>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>{{.Name}}</artifactId>
    <version>{{.Version}}</version>

    <properties>
        <java.version>17</java.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>io.mcp-mesh</groupId>
            <artifactId>mcp-mesh-spring-boot-starter</artifactId>
            <version>0.9.4</version>
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
</project>
`

const javaMainTemplate = `package com.example.agent;

import io.mcpmesh.spring.MeshAgent;
import io.mcpmesh.spring.MeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MeshAgent(name = "{{.Name}}", version = "{{.Version}}")
public class Agent {

    public static void main(String[] args) {
        SpringApplication.run(Agent.class, args);
    }

    @MeshTool(
        name = "example",
        description = "{{.Description}}",
        capability = "{{.Capability}}"
    )
    public String example(String input) {
        return "Processed: " + input;
    }
}
`
