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
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    build-essential \
    redis-server \
    tini \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Eclipse Temurin JDK 17 (architecture-aware)
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
RUN curl -fsSL https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz | tar -xzf - -C /opt && \
    ln -s /opt/apache-maven-3.9.6 /opt/maven && \
    ln -s /opt/maven/bin/mvn /usr/local/bin/mvn
ENV MAVEN_HOME=/opt/maven
ENV PATH="${MAVEN_HOME}/bin:${PATH}"

# Verify Node.js, Java, and Maven installation
RUN node --version && npm --version && java -version && mvn --version | head -1

# Install Tempo for distributed tracing (architecture-aware)
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/grafana/tempo/releases/download/v2.7.1/tempo_2.7.1_linux_${ARCH}.deb" -o /tmp/tempo.deb && \
    dpkg -i /tmp/tempo.deb && rm /tmp/tempo.deb

# Copy Tempo configuration
COPY tempo.yaml /etc/tempo/tempo.yaml
RUN mkdir -p /var/tempo && chown -R root:root /var/tempo

# Pre-install MCP Mesh Java SDK from Maven Central
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
RUN pip install --no-cache-dir click rich pyyaml jsonpath-ng requests flask docker

# Create mcp-mesh user for security (matching official runtime images)
RUN groupadd -r mcp-mesh && useradd -r -g mcp-mesh mcp-mesh

# Create workspace directory
RUN mkdir -p /workspace && chown mcp-mesh:mcp-mesh /workspace

# Set working directory
WORKDIR /workspace

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
