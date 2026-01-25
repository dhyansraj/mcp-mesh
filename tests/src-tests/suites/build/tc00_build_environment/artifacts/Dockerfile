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

# Create output directories
RUN mkdir -p /out/bin /out/wheels /out/packages /src /workspace

# Verify installations
RUN go version && rustc --version && python --version && node --version && npm --version

WORKDIR /workspace
