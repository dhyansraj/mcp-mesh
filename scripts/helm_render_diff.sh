#!/usr/bin/env bash
#
# Render the mcp-mesh-core umbrella at HEAD and at a base revision and print the
# diff between the two manifest streams.
#
# This is a REVIEWER AID, not a gate: it always exits 0 when both sides render.
# "Is this delta expected?" is a judgement about intent that CI cannot make — a
# chart PR is supposed to change the render, and the guards recently added to
# these charts change nothing at all on the default path. A job that went red on
# any delta would be red on every chart PR; a job that went red on an empty
# delta would have been red on the PRs that added those guards. What CI can do
# is put a trustworthy diff in front of the reviewer, which is the part that is
# tedious and easy to get wrong by hand:
#
#   * The baseline is rendered from a throwaway `git worktree`, never from the
#     working tree. helm/*/charts/*.tgz is gitignored, so a baseline rendered in
#     place would reuse whatever subchart archives happen to be lying around and
#     silently compare HEAD's subcharts against themselves. A fresh worktree has
#     no archives at all, so `helm dependency update` has to build them from
#     that revision's sources.
#
#   * `helm dependency update` runs on BOTH sides. Subchart archives are not
#     rebuilt just because a template changed (no version bump is involved), so
#     without this the umbrella renders stale subcharts on the head side too.
#
#   * The generated credentials are pinned. mcp-mesh-grafana's admin-password
#     and mcp-mesh-postgres's password are `randAlphaNum` when no cluster lookup
#     answers, so an unpinned render differs from itself on every invocation and
#     the diff is never clean.
#
#   * The grafana dashboards are synced from observability/ on both sides, the
#     same way helm-release.yml does it before packaging, so the diff covers the
#     manifests that are actually released rather than a dashboard-less variant.
#
# Usage: scripts/helm_render_diff.sh [BASE_REF]   (default: origin/main)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_REF="${1:-origin/main}"
CHART="helm/mcp-mesh-core"

# Applied identically to both sides. ui.enabled mirrors check_helm_pss.py: the
# UI pod is optional and would otherwise never appear in the diff at all.
RENDER_ARGS=(
  --set ui.enabled=true
  --set global.postgres.password=render-diff-pinned
  --set mcp-mesh-grafana.grafana.config.adminPassword=render-diff-pinned
)

WORKDIR="$(mktemp -d)"
cleanup() {
  git -C "$REPO_ROOT" worktree remove --force "$WORKDIR/base" >/dev/null 2>&1
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

# Render the umbrella of the tree rooted at $1 into $2.
render_tree() {
  local tree="$1" out="$2"
  if [ -d "$tree/observability/grafana/dashboards" ]; then
    mkdir -p "$tree/helm/mcp-mesh-grafana/files/dashboards"
    cp "$tree"/observability/grafana/dashboards/*.json \
       "$tree/helm/mcp-mesh-grafana/files/dashboards/" 2>/dev/null || true
  fi
  helm dependency update "$tree/$CHART" >"$out.deps" 2>&1 || {
    echo "helm dependency update failed for $tree:" >&2
    cat "$out.deps" >&2
    return 1
  }
  helm template mcp-core "$tree/$CHART" "${RENDER_ARGS[@]}" >"$out" 2>"$out.err"
}

BASE_SHA="$(git -C "$REPO_ROOT" merge-base HEAD "$BASE_REF" 2>/dev/null)"
if [ -z "$BASE_SHA" ]; then
  echo "helm-render-diff: no merge base with '$BASE_REF' — skipping the diff."
  echo "(Fetch the base branch, or pass a revision: scripts/helm_render_diff.sh <ref>)"
  exit 0
fi

echo "helm-render-diff: HEAD $(git -C "$REPO_ROOT" rev-parse --short HEAD)" \
     "vs merge-base $(git -C "$REPO_ROOT" rev-parse --short "$BASE_SHA") ($BASE_REF)"

if ! git -C "$REPO_ROOT" worktree add --detach "$WORKDIR/base" "$BASE_SHA" >/dev/null 2>&1; then
  echo "helm-render-diff: could not create a worktree at $BASE_SHA — skipping the diff."
  exit 0
fi

if ! render_tree "$WORKDIR/base" "$WORKDIR/base.yaml"; then
  echo "helm-render-diff: the BASE revision does not render — nothing to compare against."
  exit 0
fi
if [ ! -s "$WORKDIR/base.yaml" ]; then
  echo "helm-render-diff: the BASE revision rendered nothing:"
  cat "$WORKDIR/base.err"
  exit 0
fi

# HEAD renders from the working tree so uncommitted edits are visible locally.
if ! render_tree "$REPO_ROOT" "$WORKDIR/head.yaml" || [ ! -s "$WORKDIR/head.yaml" ]; then
  echo "helm-render-diff: HEAD does not render:"
  cat "$WORKDIR/head.yaml.err" 2>/dev/null
  echo "(the lint and PSS steps own this failure — not reporting it twice)"
  exit 0
fi

if diff -u "$WORKDIR/base.yaml" "$WORKDIR/head.yaml" \
     --label "base ($(git -C "$REPO_ROOT" rev-parse --short "$BASE_SHA"))" \
     --label "head" >"$WORKDIR/diff"; then
  echo "No change to the rendered umbrella manifests."
else
  echo "Rendered umbrella manifests changed ($(grep -c '^[+-][^+-]' "$WORKDIR/diff") line(s)):"
  echo
  cat "$WORKDIR/diff"
  echo
  echo "Review the delta above against the intent of this change."
fi

exit 0
