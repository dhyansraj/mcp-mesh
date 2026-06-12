# tsuite-mesh Base Image
# Pre-built image with all MCP Mesh packages for faster test execution
#
# Build args:
#   VERSION - The MCP Mesh version (e.g., 0.8.0)
#   PIP_VERSION - The pip version format (e.g., 0.8.0)

FROM python:3.11-slim

ARG VERSION
ARG PIP_VERSION

# Validate build args
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    if [ -z "$PIP_VERSION" ]; then echo "PIP_VERSION build arg is required" && exit 1; fi

# Install system dependencies, tini (init), and Node.js 22
# (apt pinning is brittle for a test image; --no-install-recommends bloat is
# acceptable here; pipefail predates this change)
# hadolint ignore=DL3008,DL3015,DL4006
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    wget \
    git \
    build-essential \
    redis-server \
    tini \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Eclipse Temurin JDK 17 (architecture-aware)
# (pipefail predates this change)
# hadolint ignore=DL4006
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) JAVA_ARCH="x64" ;; \
      arm64) JAVA_ARCH="aarch64" ;; \
      *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.13%2B11/OpenJDK17U-jdk_${JAVA_ARCH}_linux_hotspot_17.0.13_11.tar.gz" | tar -xzf - -C /opt && \
    ln -s /opt/jdk-17.0.13+11 /opt/java && \
    ln -s /opt/java/bin/java /usr/local/bin/java && \
    ln -s /opt/java/bin/javac /usr/local/bin/javac && \
    ln -s /opt/java/bin/jar /usr/local/bin/jar
ENV JAVA_HOME=/opt/java
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Install Maven 3.9.6
# (pipefail predates this change)
# hadolint ignore=DL4006
RUN curl -fsSL https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz | tar -xzf - -C /opt && \
    ln -s /opt/apache-maven-3.9.6 /opt/maven && \
    ln -s /opt/maven/bin/mvn /usr/local/bin/mvn
ENV MAVEN_HOME=/opt/maven
ENV PATH="${MAVEN_HOME}/bin:${PATH}"

# Harden npm against registry transients (intermittent ETIMEDOUT / spurious
# "notarget" from registry.npmjs.org on fresh test containers). Baking this
# into the global npmrc means every npm invocation in test containers —
# including those via the framework `npm-install` handler — retries fetches
# automatically; no per-test config needed. npm's defaults (2 retries,
# 10s min backoff) give up too easily; 5 retries starting at 2s recovers
# faster from blips and survives longer ones. Mirrors the src-tests
# tc06_build_local_image Dockerfile.
RUN npm config set --location=global \
      fetch-retries=5 \
      fetch-retry-mintimeout=2000 \
      fetch-retry-maxtimeout=30000 && \
    npm config get fetch-retries

# Verify Node.js, Java, and Maven installation
# (pipefail predates this change)
# hadolint ignore=DL4006
RUN node --version && npm --version && java -version && mvn --version | head -1

# Install Tempo for distributed tracing (architecture-aware)
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/grafana/tempo/releases/download/v2.7.1/tempo_2.7.1_linux_${ARCH}.deb" -o /tmp/tempo.deb && \
    dpkg -i /tmp/tempo.deb && rm /tmp/tempo.deb

# Copy Tempo configuration
COPY tempo.yaml /etc/tempo/tempo.yaml
RUN mkdir -p /var/tempo && chown -R root:root /var/tempo

# Pre-install MCP Mesh Java SDK from Maven Central (cd is scoped to this RUN;
# the directory is removed at the end, so WORKDIR would be wrong here)
# hadolint ignore=DL3003
RUN mkdir -p /tmp/java-sdk-install && \
    printf '<?xml version="1.0" encoding="UTF-8"?>\n\
<project xmlns="http://maven.apache.org/POM/4.0.0"\n\
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n\
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">\n\
    <modelVersion>4.0.0</modelVersion>\n\
    <groupId>io.tsuite</groupId>\n\
    <artifactId>java-sdk-prefetch</artifactId>\n\
    <version>1.0.0</version>\n\
    <dependencies>\n\
        <dependency>\n\
            <groupId>io.mcp-mesh</groupId>\n\
            <artifactId>mcp-mesh-spring-boot-starter</artifactId>\n\
            <version>%s</version>\n\
        </dependency>\n\
    </dependencies>\n\
</project>\n' "${VERSION}" > /tmp/java-sdk-install/pom.xml && \
    cd /tmp/java-sdk-install && \
    echo "Resolving mcp-mesh-spring-boot-starter:${VERSION} dependencies..." && \
    mvn dependency:resolve -q && \
    echo "Java SDK dependencies resolved:" && \
    ls /root/.m2/repository/io/mcp-mesh/ && \
    rm -rf /tmp/java-sdk-install

# Install MCP Mesh npm packages globally
RUN echo "Installing npm packages @mcpmesh/*@${VERSION}..." && \
    npm install -g @mcpmesh/cli@${VERSION} && \
    npm install -g @mcpmesh/sdk@${VERSION} && \
    npm install -g @mcpmesh/core@${VERSION}

# Verify meshctl installation
RUN meshctl --version

# Install MCP Mesh pip package
RUN echo "Installing pip package mcp-mesh==${PIP_VERSION}..." && \
    pip install --no-cache-dir mcp-mesh==${PIP_VERSION}

# Verify mesh module installation
RUN python -c "import mesh; print('mesh module imported successfully')"

# Install tsuite dependencies for running tests inside container
# (pip pinning is brittle for a test image; separate RUN predates this change)
# hadolint ignore=DL3013,DL3059
RUN pip install --no-cache-dir click rich pyyaml jsonpath-ng requests flask docker

# Create mcp-mesh user for security (matching official runtime images)
RUN groupadd -r mcp-mesh && useradd -r -g mcp-mesh mcp-mesh

# Create workspace directory
RUN mkdir -p /workspace && chown mcp-mesh:mcp-mesh /workspace

# Set working directory
WORKDIR /workspace

# Copy tsuite runner binaries for Docker/K8s test execution
COPY bin/tsuite-runner-linux-amd64 /usr/local/bin/tsuite-runner-linux-amd64
COPY bin/tsuite-runner-linux-arm64 /usr/local/bin/tsuite-runner-linux-arm64
COPY bin/select-runner /usr/local/bin/select-runner
RUN chmod +x /usr/local/bin/select-runner /usr/local/bin/tsuite-runner-linux-* 2>/dev/null || true

# Labels for identification
LABEL org.opencontainers.image.title="tsuite-mesh"
LABEL org.opencontainers.image.description="MCP Mesh Test Suite Base Image"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL mcp-mesh.cli.version="${VERSION}"
LABEL mcp-mesh.sdk.version="${VERSION}"
LABEL mcp-mesh.pip.version="${PIP_VERSION}"
LABEL mcp-mesh.java.version="${VERSION}"

# Use tini as init to properly reap zombie processes
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command
CMD ["bash"]
