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
SONATYPE_STATUS_API="https://central.sonatype.com/api/v1/publisher/status"

# GPG key used to sign artifacts that maven-gpg-plugin does not sign (the BOM).
# The trailing '!' pins the primary key rather than letting gpg pick the default
# signing subkey. This MUST match the -Dgpg.keyname value used by Maven in
# .github/workflows/release.yml, otherwise the bundle mixes two signing keys and
# Central rejects the deployment. The workflow exports GPG_KEYNAME; the default
# below only applies to manual/local runs.
GPG_KEYNAME="${GPG_KEYNAME:-F94266795DCA259D!}"

# Deployment status polling bounds
POLL_INTERVAL_SECONDS=15
POLL_TIMEOUT_SECONDS=1800

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

    mkdir -p "${BUNDLE_MODULE_DIR}"

    # Collect artifacts based on module type
    if [ "${MODULE}" = "${BOM_MODULE}" ]; then
        # BOM module: pom-packaging only - no JARs.
        #
        # Two paths exist here, and the Maven one is the expected path:
        #   1. `mvn verify` with -Dgpg.skip=false runs maven-gpg-plugin's
        #      sign-artifacts execution (declared directly in mcp-mesh-bom/pom.xml
        #      because the BOM has no <parent> to inherit it from). For pom
        #      packaging the plugin copies the module's pom.xml to
        #      target/<finalName>.pom and signs THAT file, writing
        #      target/<finalName>.pom.asc alongside it. finalName defaults to
        #      <artifactId>-<version>, i.e. exactly POM_FILE below - so both the
        #      POM and its signature are picked up straight from target/ and are
        #      guaranteed to be over identical bytes.
        #   2. Fallback: if target/ has no POM (Maven not run, or signing
        #      skipped), copy the source pom.xml in and sign it here. This is
        #      defense in depth only; it must use the same pinned key as Maven,
        #      otherwise the bundle mixes signing keys and Central rejects it.
        log "  BOM module - collecting POM artifacts only"

        # Create target dir if Maven didn't
        mkdir -p "${TARGET_DIR}"

        POM_FILE="${TARGET_DIR}/${ARTIFACT_ID}-${VERSION}.pom"

        # If POM not in target, copy from module directory.
        # Any pre-existing .asc signs the previous bytes, so drop it: the
        # signature must always be regenerated together with the POM.
        if [ ! -f "${POM_FILE}" ]; then
            log "  POM not in target/, copying from module directory"
            cp "${MODULE}/pom.xml" "${POM_FILE}"
            rm -f "${POM_FILE}.asc"
        else
            log "  Using Maven-produced POM from target/"
        fi

        cp "${POM_FILE}" "${BUNDLE_MODULE_DIR}/"
        log "  Collected: $(basename "${POM_FILE}")"

        # GPG signature - only sign if maven-gpg-plugin did not already.
        if [ ! -f "${POM_FILE}.asc" ]; then
            log "  No Maven signature found; signing POM with GPG (key: ${GPG_KEYNAME})..."
            gpg --local-user "${GPG_KEYNAME}" --batch --armor --detach-sign "${POM_FILE}"
        else
            log "  Using Maven-produced GPG signature"
        fi
        cp "${POM_FILE}.asc" "${BUNDLE_MODULE_DIR}/"
        log "  Collected: $(basename "${POM_FILE}").asc"
    else
        if [ ! -d "${TARGET_DIR}" ]; then
            error "Target directory not found: ${TARGET_DIR}"
            exit 1
        fi
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

        # Sources JAR (create empty placeholder for native/resource-only modules)
        SOURCES_FILE="${TARGET_DIR}/${ARTIFACT_ID}-${VERSION}-sources.jar"
        if [ -f "${SOURCES_FILE}" ]; then
            cp "${SOURCES_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${SOURCES_FILE}")
            log "  Collected: $(basename "${SOURCES_FILE}")"
        else
            log "  Sources JAR not found, creating empty placeholder"
            mkdir -p /tmp/empty-sources
            jar cf "${SOURCES_FILE}" -C /tmp/empty-sources .
            rm -rf /tmp/empty-sources
            gpg --batch --armor --detach-sign "${SOURCES_FILE}"
            cp "${SOURCES_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${SOURCES_FILE}")
            log "  Created empty: $(basename "${SOURCES_FILE}")"
        fi

        # Javadoc JAR (create empty placeholder for native/resource-only modules)
        JAVADOC_FILE="${TARGET_DIR}/${ARTIFACT_ID}-${VERSION}-javadoc.jar"
        if [ -f "${JAVADOC_FILE}" ]; then
            cp "${JAVADOC_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${JAVADOC_FILE}")
            log "  Collected: $(basename "${JAVADOC_FILE}")"
        else
            log "  Javadoc JAR not found, creating empty placeholder"
            mkdir -p /tmp/empty-javadoc
            jar cf "${JAVADOC_FILE}" -C /tmp/empty-javadoc .
            rm -rf /tmp/empty-javadoc
            gpg --batch --armor --detach-sign "${JAVADOC_FILE}"
            cp "${JAVADOC_FILE}" "${BUNDLE_MODULE_DIR}/"
            ARTIFACTS+=("${JAVADOC_FILE}")
            log "  Created empty: $(basename "${JAVADOC_FILE}")"
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
rm -f "${BUNDLE_ZIP}"  # mktemp creates empty file; zip fails trying to update it as existing archive
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

TOKEN=$(printf '%s' "${SONATYPE_USERNAME}:${SONATYPE_TOKEN}" | openssl base64 -A)

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
else
    error "Upload failed with HTTP ${HTTP_STATUS}"
    error "Response: ${HTTP_BODY}"
    exit 1
fi

# The upload response body is the deployment ID. Upload acceptance is NOT
# publication: with publishingType=AUTOMATIC the portal still has to validate
# the bundle (signatures, POM metadata, checksums) before releasing it, and that
# validation can fail after the upload returned 2xx.
DEPLOYMENT_ID=$(printf '%s' "${HTTP_BODY}" | tr -d '[:space:]')
if [ -z "${DEPLOYMENT_ID}" ]; then
    error "Upload accepted but no deployment ID was returned; cannot verify publication"
    exit 1
fi

PORTAL_URL="https://central.sonatype.com/publishing/deployments"
log "Deployment ID: ${DEPLOYMENT_ID}"
log "Monitor status at: ${PORTAL_URL}"

# Extract .deploymentState from a status response body
deployment_state() {
    if command -v jq >/dev/null 2>&1; then
        printf '%s' "$1" | jq -r '.deploymentState // empty' 2>/dev/null || true
    else
        printf '%s' "$1" | tr -d ' \n' \
            | sed -n 's/.*"deploymentState":"\([A-Z_]*\)".*/\1/p' || true
    fi
}

# Pretty-print a status response body (validation errors live in .errors)
dump_status_body() {
    if command -v jq >/dev/null 2>&1; then
        printf '%s' "$1" | jq . 2>/dev/null || printf '%s\n' "$1"
    else
        printf '%s\n' "$1"
    fi
}

# Poll the deployment until it reaches a terminal state.
# States (Sonatype Publisher API): PENDING, VALIDATING, VALIDATED, PUBLISHING,
# PUBLISHED, FAILED. With AUTOMATIC publishing, PUBLISHED is the success
# terminal state and FAILED is the failure terminal state; the rest are
# transitional.
log "Waiting for deployment ${DEPLOYMENT_ID} to reach a terminal state..."

DEADLINE=$(( $(date +%s) + POLL_TIMEOUT_SECONDS ))
LAST_STATE=""
LAST_BODY=""

while [ "$(date +%s)" -lt "${DEADLINE}" ]; do
    STATUS_BODY=$(curl -s -X POST \
        "${SONATYPE_STATUS_API}?id=${DEPLOYMENT_ID}" \
        -H "Authorization: Bearer ${TOKEN}") || STATUS_BODY=""
    STATE=$(deployment_state "${STATUS_BODY}")

    if [ -n "${STATUS_BODY}" ]; then
        LAST_BODY="${STATUS_BODY}"
    fi

    if [ -z "${STATE}" ]; then
        log "  Could not read deployment state (transient?), retrying..."
    else
        if [ "${STATE}" != "${LAST_STATE}" ]; then
            log "  Deployment state: ${STATE}"
            LAST_STATE="${STATE}"
        fi

        case "${STATE}" in
            PUBLISHED)
                success "Deployment ${DEPLOYMENT_ID} published to Maven Central"
                success "Java SDK ${VERSION} published to Maven Central"
                exit 0
                ;;
            FAILED)
                error "Deployment ${DEPLOYMENT_ID} FAILED validation"
                error "Central reported the following component errors:"
                dump_status_body "${STATUS_BODY}" >&2
                error "Inspect at: ${PORTAL_URL}"
                exit 1
                ;;
            PENDING|VALIDATING|VALIDATED|PUBLISHING)
                # Transitional; keep polling. VALIDATED is not treated as
                # success here: with AUTOMATIC it advances to PUBLISHING on its
                # own, and reporting success before the artifacts are on Central
                # is exactly the failure mode this polling exists to prevent.
                :
                ;;
            *)
                log "  Unrecognized deployment state '${STATE}', continuing to poll"
                ;;
        esac
    fi

    sleep "${POLL_INTERVAL_SECONDS}"
done

error "Timed out after ${POLL_TIMEOUT_SECONDS}s waiting for deployment to publish"
error "Deployment ID: ${DEPLOYMENT_ID}"
error "Last observed state: ${LAST_STATE:-unknown}"
if [ -n "${LAST_BODY}" ]; then
    error "Last status response:"
    dump_status_body "${LAST_BODY}" >&2
fi
error "Inspect at: ${PORTAL_URL}"
exit 1
