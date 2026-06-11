# MCP Mesh Java Runtime - Pre-caches SDK from Maven Central
# Supports linux/amd64, linux/arm64

FROM --platform=$TARGETPLATFORM eclipse-temurin:17-jdk-jammy

ARG VERSION

# Install runtime dependencies. uid/gid pinned to 999: the helm
# mcp-mesh-agent chart forces runAsUser/runAsGroup/fsGroup 999, which must
# match this user so files chowned to mcp-mesh in-image stay writable.
# hadolint ignore=DL3008,DL3015
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    maven \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r -g 999 mcp-mesh \
    && useradd -r -u 999 -g mcp-mesh mcp-mesh

# Pre-cache SDK dependencies from Maven Central (cd is scoped to this RUN;
# the directory is removed at the end, so WORKDIR would be wrong here)
# hadolint ignore=DL3003
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    echo "Pre-caching io.mcp-mesh SDK ${VERSION} from Maven Central" && \
    mkdir -p /tmp/warmup && \
    printf '%s\n' \
    '<?xml version="1.0" encoding="UTF-8"?>' \
    '<project xmlns="http://maven.apache.org/POM/4.0.0"' \
    '         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' \
    '         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">' \
    '    <modelVersion>4.0.0</modelVersion>' \
    '    <groupId>io.mcp-mesh</groupId>' \
    '    <artifactId>warmup</artifactId>' \
    '    <version>1.0.0</version>' \
    '    <repositories>' \
    '        <repository>' \
    '            <id>spring-milestones</id>' \
    '            <name>Spring Milestones</name>' \
    '            <url>https://repo.spring.io/milestone</url>' \
    '            <snapshots>' \
    '                <enabled>false</enabled>' \
    '            </snapshots>' \
    '        </repository>' \
    '    </repositories>' \
    '    <dependencies>' \
    '        <dependency>' \
    '            <groupId>io.mcp-mesh</groupId>' \
    '            <artifactId>mcp-mesh-spring-boot-starter</artifactId>' \
    "            <version>${VERSION}</version>" \
    '        </dependency>' \
    '    </dependencies>' \
    '</project>' > /tmp/warmup/pom.xml && \
    cd /tmp/warmup && mvn dependency:resolve -q && \
    rm -rf /tmp/warmup

# Create app directory
RUN mkdir -p /app && chown mcp-mesh:mcp-mesh /app

# Switch to non-root user
USER mcp-mesh
WORKDIR /app

# Health check endpoint (Spring Boot actuator)
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
    CMD wget --spider -q http://localhost:8080/health || exit 1

EXPOSE 8080

# Default entrypoint - agents will override with their JAR
ENTRYPOINT ["java", "-jar"]
