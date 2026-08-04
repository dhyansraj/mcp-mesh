#!/usr/bin/env bash
#
# Regenerate src/runtime/python/constraints.txt — the Python dependency lock
# (issue #1454).
#
#   scripts/lock_python_deps.sh              # minimal refresh
#   scripts/lock_python_deps.sh --upgrade    # deliberate dependency bump
#
# Why a constraints file and not a requirements file
# --------------------------------------------------
# A constraints file installs nothing. It only caps the version of whatever
# else is being installed, so an entry for a package that is not installed in
# a given environment is simply unused. That property is what makes one file
# correct for every platform we ship to, without any tool that understands
# universal resolution:
#
#   * linux/amd64 and linux/arm64 resolve to the IDENTICAL 112 pins (measured),
#     so the multi-arch runtime images share one lock.
#   * Python 3.11 resolves one extra package over 3.12 (backports-tarfile, a
#     `python_version < "3.12"` conditional). On 3.12 that entry is inert.
#   * Linux resolves two packages macOS does not (jeepney, secretstorage — the
#     dbus keyring backend). On macOS those entries are inert. Nothing resolves
#     on macOS that does not resolve on Linux.
#
# So the Linux/3.11 resolution is a superset of every environment we build in,
# and a superset is exactly what a constraints file wants to be. Generating it
# anywhere else would produce a subset and leave real packages uncapped, which
# is why this runs in a container rather than on your host.
#
# Why in Docker
# -------------
# Determinism across maintainers. Running pip-compile on a macOS laptop drops
# the two Linux-only entries above; running it on 3.12 drops a third. Pinning
# the interpreter and the platform here means any maintainer regenerating the
# file gets the same bytes, so a diff in this file is always a real dependency
# move and never a whose-laptop artifact.
#
# --upgrade is the 'cargo generate-lockfile' of this file
# -------------------------------------------------------
# Without it, pip-compile preserves the pins already in the output file and
# moves only what a manifest change forces — the analogue of
# `cargo update --package mcp-mesh-core`. With it, the whole graph is
# re-resolved. Both are legitimate; only one belongs in a release bump.
# `scripts/check_release_lockfiles.py` is the assertion that an --upgrade run
# never rides along inside a version bump.
#
# Hashes are deliberately absent; see the note in check_release_lockfiles.py.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_DIR="src/runtime/python"
OUT="${REPO_ROOT}/${PY_DIR}/constraints.txt"

# Resolved against the manifest PyPI PUBLISHES, not the one in the source tree.
# The two are not the same document, and the difference is load-bearing:
# packaging/pypi/pyproject.toml carries upper bounds that src/runtime/python's
# copy lacks on ten packages (rich<14.0.0, uvicorn<1.0.0, pydantic<3.0.0, ...).
# Resolving against the source manifest therefore produced a lock the published
# package cannot install — rich 15.0.0 against a published rich<14.0.0 — which
# failed the runtime image build outright.
#
# It also means CI, installing the source manifest unconstrained, was testing
# rich 15 while every user and every image got rich 13. Locking from the
# published side fixes both at once: the pins satisfy the published bounds by
# construction, and the source manifest's ranges are a superset of them, so the
# same file constrains an editable dev install just as well.
PYPI_MANIFEST="packaging/pypi/pyproject.toml"

# Pinned so a pip-tools release cannot reformat the file and present it as a
# dependency change. Bumping this is its own reviewed diff.
PIP_TOOLS_VERSION="7.6.0"

# 3.11 is the floor in requires-python AND the interpreter in both runtime
# images, so it is the resolution that has to be correct. See the superset
# argument above for why the higher versions do not need their own file.
IMAGE="python:3.11-slim"
PLATFORM="linux/amd64"

# The extras worth locking are the ones that ship behaviour. [litellm] is in
# because CI installs it (via [dev]) and because litellm has already shipped two
# releases bad enough to earn `!=` markers in the manifest. The dev tooling
# (pytest/black/ruff/mypy) is deliberately NOT locked: it is never shipped to a
# user, its drift fails loudly in CI rather than silently in production, and
# locking it would churn this file on every ruff release. [anthropic-bedrock]
# and [kubernetes] are out for the same reason plus one more — boto3 publishes
# most weekdays, so the lock would be stale the day after it was written.
EXTRAS=(--extra litellm)

UPGRADE=""
for arg in "$@"; do
    case "$arg" in
        --upgrade|-U)
            UPGRADE="--upgrade"
            ;;
        *)
            echo "unknown argument: $arg" >&2
            echo "usage: $0 [--upgrade]" >&2
            exit 2
            ;;
    esac
done

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required: this file must be generated on ${PLATFORM}/${IMAGE}" >&2
    exit 1
fi

echo "Resolving ${PYPI_MANIFEST} in ${IMAGE} (${PLATFORM})..."
[ -n "$UPGRADE" ] && echo "  --upgrade: re-resolving the ENTIRE graph, not just what changed"

BODY="$(docker run --rm --platform "${PLATFORM}" \
    -v "${REPO_ROOT}/${PY_DIR}:/src:ro" \
    -v "${REPO_ROOT}/${PYPI_MANIFEST}:/published-pyproject.toml:ro" \
    "${IMAGE}" bash -c "
set -euo pipefail
pip install --quiet --disable-pip-version-check 'pip-tools==${PIP_TOOLS_VERSION}' >&2
cp -r /src /work
# The published manifest, resolved in a tree that has the real packages beside
# it so hatchling can produce metadata. packaging/pypi/ holds no sources of its
# own, which is why this is a swap rather than a second checkout.
cp /published-pyproject.toml /work/pyproject.toml
cd /work
# --strip-extras is mandatory, not cosmetic: without it pip-compile emits
# 'google-auth[requests]==...' and four more like it, and pip rejects a
# constraints file containing an extra outright ('Constraints cannot have
# extras'). The file would be unusable for its one purpose.
#
# mcp-mesh-core is excluded on purpose. It is the one mesh distribution the
# published manifest depends on, and its version moves with every release —
# pinning it here would make the lock a second file a bump has to touch, and
# a stale pin would make the NEXT release's image unresolvable rather than
# merely undertested. scripts/check_release_lockfiles.py exempts mesh names
# from its comparison, so if that trade is ever revisited the guard is ready.
pip-compile --quiet \
    --strip-extras \
    --no-emit-index-url \
    --no-header \
    --unsafe-package mcp-mesh-core \
    ${UPGRADE} \
    ${EXTRAS[*]} \
    --output-file constraints.txt \
    pyproject.toml >&2
cat constraints.txt
")"

{
    cat <<'HEADER'
#
# mcp-mesh Python dependency lock — the transitive set the suite is green
# against and the set the runtime images install (issue #1454).
#
# DO NOT EDIT BY HAND. Regenerate:
#
#     scripts/lock_python_deps.sh              # minimal refresh
#     scripts/lock_python_deps.sh --upgrade    # deliberate dependency bump
#
# This is a CONSTRAINTS file. It installs nothing; it caps the version of
# whatever is installed alongside it:
#
#     pip install -e '.[dev]' -c constraints.txt
#
# Its scope is this repository: CI installs against it and the runtime images
# build against it. It is NOT shipped inside the published wheel, so a plain
# `pip install mcp-mesh` from PyPI is not governed by it.
#
# Resolved against packaging/pypi/pyproject.toml — the manifest PyPI publishes,
# whose bounds are tighter than the source tree's on ten packages. Pinning from
# the published side is what makes one file valid for the runtime images and
# for an editable CI install at the same time.
#
# Entries for packages a given environment does not install are inert, which is
# what lets one file cover linux/amd64, linux/arm64, macOS and Python 3.11-3.14
# with no markers. litellm is listed here and is still NOT part of a default
# install (#1383) — capping a version is not requesting it.
#
# A version bump must not move a single line below. That is asserted by
# scripts/check_release_lockfiles.py; moving these lines is its own reviewed PR.
#
HEADER
    printf '%s\n' "$BODY"
} > "$OUT"

PINS="$(grep -cE '^[A-Za-z0-9]' "$OUT" || true)"
echo "Wrote ${PY_DIR}/constraints.txt (${PINS} pins)"
echo
echo "Next:"
echo "  git diff --stat ${PY_DIR}/constraints.txt"
echo "  python3 scripts/check_release_lockfiles.py"
