# tsuite-mesh:local - Built from local source
# Contains MCP Mesh packages built from source code
#
# This image is built by src-tests after compiling all packages.
# It mirrors tsuite-mesh:X.Y.Z but uses locally built artifacts.

FROM python:3.11-slim

# Install system dependencies, tini (init), and Node.js 22
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    jq \
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

# Install Maven
RUN curl -fsSL https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz | tar -xzf - -C /opt && \
    ln -s /opt/apache-maven-3.9.6 /opt/maven && \
    ln -s /opt/maven/bin/mvn /usr/local/bin/mvn
ENV MAVEN_HOME=/opt/maven
ENV PATH="${MAVEN_HOME}/bin:${PATH}"

# Install Tempo for distributed tracing (architecture-aware)
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/grafana/tempo/releases/download/v2.7.1/tempo_2.7.1_linux_${ARCH}.deb" -o /tmp/tempo.deb && \
    dpkg -i /tmp/tempo.deb && rm /tmp/tempo.deb

# Copy Tempo configuration
COPY tempo.yaml /etc/tempo/tempo.yaml
RUN mkdir -p /var/tempo && chown -R root:root /var/tempo

# Verify Node.js and Java installation
RUN node --version && npm --version && java -version && mvn --version | head -1

# Create directories for local packages
RUN mkdir -p /wheels /packages /java-jars /native-libs /workspace

# Copy locally built artifacts
COPY wheels/*.whl /wheels/
COPY packages/*.tgz /packages/
COPY bin/meshctl /usr/local/bin/meshctl
COPY bin/mcp-mesh-registry /usr/local/bin/mcp-mesh-registry

# Copy tsuite runner binaries for Docker/K8s test execution
COPY bin/tsuite-runner-linux-amd64 /usr/local/bin/tsuite-runner-linux-amd64
COPY bin/tsuite-runner-linux-arm64 /usr/local/bin/tsuite-runner-linux-arm64
COPY bin/select-runner /usr/local/bin/select-runner

# Copy Java JARs and native FFI library (optional - may not exist)
COPY java-jars/ /java-jars/
COPY native-libs/ /native-libs/

# Copy Maven repository structure for Java SDK (preserves POMs and metadata)
COPY m2-repo/ /root/.m2/repository/io/

# Make binaries executable
RUN chmod +x /usr/local/bin/meshctl /usr/local/bin/mcp-mesh-registry
RUN chmod +x /usr/local/bin/select-runner /usr/local/bin/tsuite-runner-linux-* 2>/dev/null || true

# Install Python packages from local wheels (direct path to ensure local version is used)
RUN pip install --no-cache-dir /wheels/mcp_mesh_core-*.whl /wheels/mcp_mesh-*.whl

# Verify mesh module installation
RUN python -c "import mesh; print('mesh module imported successfully')"

# Install meshctl CLI from local tarball (if exists) or use binary
RUN if ls /packages/mcpmesh-cli-*.tgz 1> /dev/null 2>&1; then \
        npm install -g /packages/mcpmesh-cli-*.tgz; \
    else \
        echo "Using meshctl binary from /usr/local/bin"; \
    fi

# Verify meshctl installation
RUN meshctl --version

# Install TypeScript core bindings globally (SDK depends on this)
RUN npm install -g /packages/mcpmesh-core-*.tgz

# Install TypeScript SDK globally from local tarball
RUN npm install -g /packages/mcpmesh-sdk-*.tgz

# Verify Java SDK installation (installed via m2-repo copy above)
RUN if [ -d "/root/.m2/repository/io/mcp-mesh" ]; then \
        echo "Java SDK installed in Maven repository:"; \
        ls -la /root/.m2/repository/io/mcp-mesh/; \
    else \
        echo "No Java SDK found in Maven repository (optional)"; \
    fi

# Set native library path for Java agents (needed for src-tests builds where
# the JAR only contains the host platform's native lib, not the Linux .so)
ENV MESH_NATIVE_LIB_PATH=/native-libs

# Install tsuite dependencies for running tests inside container
RUN pip install --no-cache-dir click rich pyyaml jsonpath-ng requests flask docker

# Create mcp-mesh user for security (matching official runtime images)
RUN groupadd -r mcp-mesh && useradd -r -g mcp-mesh mcp-mesh

# Set ownership
RUN chown -R mcp-mesh:mcp-mesh /workspace /wheels /packages

# Set working directory
WORKDIR /workspace

# Labels for identification
LABEL org.opencontainers.image.title="tsuite-mesh"
LABEL org.opencontainers.image.description="MCP Mesh Test Suite Base Image (Local Build)"
LABEL org.opencontainers.image.version="local"
LABEL mcp-mesh.build.type="local"

# Use tini as init to properly reap zombie processes
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command
CMD ["bash"]
