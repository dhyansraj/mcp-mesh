#!/bin/bash
set -euo pipefail

# Publish Java SDK modules to Maven Central via Sonatype Central Portal REST API
# Bundles all module artifacts into a single ZIP and uploads via the portal API
# Usage: ./publish-java.sh <VERSION>
# Expects: SONATYPE_USERNAME, SONATYPE_TOKEN environment variables
# Run from: src/runtime/java/ directory (the parent POM directory)

VERSION="${1:?Usage: $0 <VERSION>}"

# Modules to publish (order matters for dependency resolution)
MODULES=(
    "mcp-mesh-bom"
    "mcp-mesh-core"
    "mcp-mesh-sdk"
    "mcp-mesh-native"
    "mcp-mesh-spring-boot-starter"
    "mcp-mesh-spring-ai"
)

# BOM module is pom-packaging only (no JARs)
BOM_MODULE="mcp-mesh-bom"

# Maven coordinates
GROUP_ID_PATH="io/mcp-mesh"

# Sonatype Central Portal API
SONATYPE_API="https://central.sonatype.com/api/v1/publisher/upload"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Validate environment
if [ -z "${SONATYPE_USERNAME:-}" ]; then
    error "SONATYPE_USERNAME environment variable is required"
    exit 1
fi

if [ -z "${SONATYPE_TOKEN:-}" ]; then
    error "SONATYPE_TOKEN environment variable is required"
    exit 1
fi

log "Publishing Java SDK version: ${VERSION}"
log "Modules: ${MODULES[*]}"

# Create temporary working directory for the bundle
BUNDLE_DIR=$(mktemp -d)
trap 'rm -rf "$BUNDLE_DIR"' EXIT

log "Bundle staging directory: ${BUNDLE_DIR}"

# Process each module
for MODULE in "${MODULES[@]}"; do
    ARTIFACT_ID="${MODULE}"
    TARGET_DIR="${MODULE}/target"
    BUNDLE_MODULE_DIR="${BUNDLE_DIR}/${GROUP_ID_PATH}/${ARTIFACT_ID}/${VERSION}"

    log "Processing module: ${MODULE}"

    if [ ! -d "${TARGET_DIR}" ]; then
        error "Target directory not found: ${TARGET_DIR}"
        exit 1
    fi

    mkdir -p "${BUNDLE_MODULE_DIR}"

    # Collect artifacts based on module type
    if [ "${MODULE}" = "${BOM_MODULE}" ]; then
        # BOM module: pom-packaging only (.pom + .pom.asc)
        log "  BOM module - collecting POM artifacts only"
        ARTIFACTS=()

        POM_FILE="${TARGET_DIR}/${ARTIFACT_ID}-${VERSION}.pom"
        if [ -f "${POM_FILE}" ]; then
            cp "${POM_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${POM_FILE}")
            log "  Collected: $(basename "${POM_FILE}")"
        else
            error "  POM file not found: ${POM_FILE}"
            exit 1
        fi

        # GPG signature for POM
        if [ -f "${POM_FILE}.asc" ]; then
            cp "${POM_FILE}.asc" "${BUNDLE_MODULE_DIR}/"
            log "  Collected: $(basename "${POM_FILE}").asc"
        else
            error "  GPG signature not found: ${POM_FILE}.asc"
            exit 1
        fi
    else
        # Standard module: JAR, sources, javadoc, POM + all .asc signatures
        log "  Standard module - collecting all artifacts"
        ARTIFACTS=()

        # Main JAR
        JAR_FILE="${TARGET_DIR}/${ARTIFACT_ID}-${VERSION}.jar"
        if [ -f "${JAR_FILE}" ]; then
            cp "${JAR_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${JAR_FILE}")
            log "  Collected: $(basename "${JAR_FILE}")"
        else
            error "  JAR file not found: ${JAR_FILE}"
            exit 1
        fi

        # Sources JAR
        SOURCES_FILE="${TARGET_DIR}/${ARTIFACT_ID}-${VERSION}-sources.jar"
        if [ -f "${SOURCES_FILE}" ]; then
            cp "${SOURCES_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${SOURCES_FILE}")
            log "  Collected: $(basename "${SOURCES_FILE}")"
        else
            error "  Sources JAR not found: ${SOURCES_FILE}"
            exit 1
        fi

        # Javadoc JAR
        JAVADOC_FILE="${TARGET_DIR}/${ARTIFACT_ID}-${VERSION}-javadoc.jar"
        if [ -f "${JAVADOC_FILE}" ]; then
            cp "${JAVADOC_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${JAVADOC_FILE}")
            log "  Collected: $(basename "${JAVADOC_FILE}")"
        else
            error "  Javadoc JAR not found: ${JAVADOC_FILE}"
            exit 1
        fi

        # POM file
        POM_FILE="${TARGET_DIR}/${ARTIFACT_ID}-${VERSION}.pom"
        if [ -f "${POM_FILE}" ]; then
            cp "${POM_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${POM_FILE}")
            log "  Collected: $(basename "${POM_FILE}")"
        else
            error "  POM file not found: ${POM_FILE}"
            exit 1
        fi

        # GPG signatures (.asc files)
        for ARTIFACT in "${ARTIFACTS[@]}"; do
            ASC_FILE="${ARTIFACT}.asc"
            if [ -f "${ASC_FILE}" ]; then
                cp "${ASC_FILE}" "${BUNDLE_MODULE_DIR}/"
                log "  Collected: $(basename "${ASC_FILE}")"
            else
                error "  GPG signature not found: ${ASC_FILE}"
                exit 1
            fi
        done
    fi

    # Generate checksums for all non-signature artifacts
    log "  Generating checksums..."
    for FILE in "${BUNDLE_MODULE_DIR}"/*; do
        BASENAME=$(basename "${FILE}")
        # Skip .asc, .md5, and .sha1 files
        if [[ "${BASENAME}" == *.asc ]] || [[ "${BASENAME}" == *.md5 ]] || [[ "${BASENAME}" == *.sha1 ]]; then
            continue
        fi
        md5sum "${FILE}" | awk '{print $1}' > "${FILE}.md5"
        sha1sum "${FILE}" | awk '{print $1}' > "${FILE}.sha1"
        log "  Generated checksums for: ${BASENAME}"
    done

    success "  Module ${MODULE} staged"
done

# Create the bundle ZIP
BUNDLE_ZIP=$(mktemp /tmp/mcp-mesh-java-bundle-XXXXXX.zip)
log "Creating bundle ZIP: ${BUNDLE_ZIP}"

(cd "${BUNDLE_DIR}" && zip -r "${BUNDLE_ZIP}" .)

BUNDLE_SIZE=$(du -sh "${BUNDLE_ZIP}" | cut -f1)
log "Bundle size: ${BUNDLE_SIZE}"

# List bundle contents
log "Bundle contents:"
(cd "${BUNDLE_DIR}" && find . -type f | sort | while read -r f; do
    echo "  ${f}"
done)

# Upload to Sonatype Central Portal
log "Uploading bundle to Sonatype Central Portal..."

TOKEN=$(echo -n "${SONATYPE_USERNAME}:${SONATYPE_TOKEN}" | base64)

HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    "${SONATYPE_API}?publishingType=AUTOMATIC" \
    -H "Authorization: Bearer ${TOKEN}" \
    -F "bundle=@${BUNDLE_ZIP}")

HTTP_BODY=$(echo "$HTTP_RESPONSE" | head -n -1)
HTTP_STATUS=$(echo "$HTTP_RESPONSE" | tail -n 1)

# Clean up bundle ZIP
rm -f "${BUNDLE_ZIP}"

if [ "${HTTP_STATUS}" -ge 200 ] && [ "${HTTP_STATUS}" -lt 300 ]; then
    success "Bundle uploaded successfully (HTTP ${HTTP_STATUS})"
    if [ -n "${HTTP_BODY}" ]; then
        log "Deployment ID: ${HTTP_BODY}"
    fi
    log "Monitor status at: https://central.sonatype.com/publishing"
else
    error "Upload failed with HTTP ${HTTP_STATUS}"
    error "Response: ${HTTP_BODY}"
    exit 1
fi

success "Java SDK ${VERSION} published to Maven Central"
