# MCP Mesh Source Build Image
# Contains all tools needed to build Go, Rust, Python, and TypeScript packages

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Go 1.23 (architecture-aware)
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL https://go.dev/dl/go1.23.0.linux-${ARCH}.tar.gz | tar -C /usr/local -xzf - && \
    ln -s /usr/local/go/bin/go /usr/local/bin/go && \
    ln -s /usr/local/go/bin/gofmt /usr/local/bin/gofmt

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install maturin for building Rust Python extensions
RUN pip install --no-cache-dir maturin build wheel

# Install Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
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

# Create output directories
RUN mkdir -p /out/bin /out/wheels /out/packages /out/java-jars /out/native-libs /src /workspace

# Verify installations
RUN go version && rustc --version && python --version && node --version && npm --version && java -version && mvn --version | head -1

WORKDIR /workspace
