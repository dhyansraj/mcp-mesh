#!/bin/bash
# Build script for Data Processor Agent Docker image

set -e

# Configuration
IMAGE_NAME="data-processor-agent"
IMAGE_TAG="${IMAGE_TAG:-latest}"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"

echo "🏗️  Building Data Processor Agent Docker image..."
echo "📦 Image: ${FULL_IMAGE_NAME}"

# Build the Docker image
docker build \
    --tag "${FULL_IMAGE_NAME}" \
    --build-arg BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    --build-arg VCS_REF="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
    .

echo "✅ Build completed successfully!"
echo "🚀 To run the agent:"
echo "   docker run -p 9090:9090 ${FULL_IMAGE_NAME}"
echo ""
echo "🔧 To run with custom configuration:"
echo "   docker run -p 9090:9090 -e AGENT_NAME=my-processor ${FULL_IMAGE_NAME}"
echo ""
echo "📊 Image information:"
docker images "${IMAGE_NAME}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"