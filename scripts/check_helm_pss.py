#!/usr/bin/env python3
"""Assert every pod spec rendered by the helm/ charts satisfies the
Pod Security Standards "restricted" profile with default values.

For each chart that renders workloads, runs `helm template` and checks every
container (init containers included):

  - seccompProfile.type RuntimeDefault/Localhost (pod- or container-level)
  - runAsNonRoot: true (pod- or container-level)
  - allowPrivilegeEscalation: false (container-level)
  - capabilities.drop contains ALL (container-level)

Also rejects restricted-profile spec violations: hostNetwork/hostPID/hostIPC,
privileged containers, and disallowed volume types (hostPath, etc.).

Usage: python3 scripts/check_helm_pss.py  (run from the repo root)
Exit code 0 = all checks pass.
"""

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
HELM_DIR = REPO_ROOT / "helm"

# chart dir -> extra helm template args (cover optional pods). Charts are
# auto-discovered (every helm/*/Chart.yaml); this map only adds args.
EXTRA_ARGS = {
    # umbrella: render the optional UI pod too
    "mcp-mesh-core": ["--set", "ui.enabled=true"],
}


def discover_charts() -> list[str]:
    return sorted(d.name for d in HELM_DIR.iterdir()
                  if (d / "Chart.yaml").is_file())

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet"}
POD_BEARING_KINDS = WORKLOAD_KINDS | {"Pod", "CronJob"}

ALLOWED_VOLUME_TYPES = {
    "configMap", "csi", "downwardAPI", "emptyDir", "ephemeral",
    "persistentVolumeClaim", "projected", "secret",
}


def build_dependencies(chart: str) -> None:
    """(Re)package charts/*.tgz for charts with dependencies, so the check
    templates the current local subcharts instead of stale archives (and
    works on fresh clones with no charts/ dir at all)."""
    chart_dir = HELM_DIR / chart
    with open(chart_dir / "Chart.yaml") as f:
        meta = yaml.safe_load(f)
    if not meta.get("dependencies"):
        return
    for cmd in (["helm", "dependency", "build", str(chart_dir)],
                ["helm", "dependency", "update", str(chart_dir)]):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return
    print(f"FAIL {chart}: helm dependency build/update failed:\n{result.stderr}")
    sys.exit(1)


def render(chart: str, extra_args: list[str]) -> str:
    cmd = ["helm", "template", "pss-check", str(HELM_DIR / chart), *extra_args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAIL {chart}: helm template failed:\n{result.stderr}")
        sys.exit(1)
    return result.stdout


def pod_spec_of(doc: dict):
    kind = doc.get("kind")
    if kind == "Pod":
        return doc.get("spec"), doc["metadata"].get("name", "?")
    if kind in WORKLOAD_KINDS:
        spec = doc.get("spec", {}).get("template", {}).get("spec")
        return spec, doc["metadata"].get("name", "?")
    if kind == "CronJob":
        spec = (doc.get("spec", {}).get("jobTemplate", {})
                .get("spec", {}).get("template", {}).get("spec"))
        return spec, doc["metadata"].get("name", "?")
    return None, None


def check_pod(chart: str, name: str, spec: dict) -> list[str]:
    errors = []
    pod_sc = spec.get("securityContext") or {}

    for field in ("hostNetwork", "hostPID", "hostIPC"):
        if spec.get(field):
            errors.append(f"{field} is set")

    for vol in spec.get("volumes") or []:
        types = set(vol.keys()) - {"name"}
        bad = types - ALLOWED_VOLUME_TYPES
        if bad:
            errors.append(f"volume {vol.get('name')}: disallowed type(s) {sorted(bad)}")

    containers = (spec.get("containers") or []) + (spec.get("initContainers") or []) \
        + (spec.get("ephemeralContainers") or [])
    for c in containers:
        cname = c.get("name", "?")
        sc = c.get("securityContext") or {}

        if sc.get("privileged"):
            errors.append(f"{cname}: privileged")

        seccomp = (sc.get("seccompProfile") or pod_sc.get("seccompProfile") or {}).get("type")
        if seccomp not in ("RuntimeDefault", "Localhost"):
            errors.append(f"{cname}: seccompProfile.type missing/invalid (got {seccomp!r})")

        run_as_non_root = sc.get("runAsNonRoot", pod_sc.get("runAsNonRoot"))
        if run_as_non_root is not True:
            errors.append(f"{cname}: runAsNonRoot != true (got {run_as_non_root!r})")

        run_as_user = sc.get("runAsUser", pod_sc.get("runAsUser"))
        if run_as_user == 0:
            errors.append(f"{cname}: runAsUser is 0")

        if sc.get("allowPrivilegeEscalation") is not False:
            errors.append(f"{cname}: allowPrivilegeEscalation != false")

        drops = (sc.get("capabilities") or {}).get("drop") or []
        if "ALL" not in drops:
            errors.append(f"{cname}: capabilities.drop missing ALL")
        adds = set((sc.get("capabilities") or {}).get("add") or [])
        if adds - {"NET_BIND_SERVICE"}:
            errors.append(f"{cname}: capabilities.add {sorted(adds)} not allowed")

    return [f"{name}/{e}" for e in errors]


def main() -> int:
    failures = 0
    for chart in discover_charts():
        build_dependencies(chart)
        rendered = render(chart, EXTRA_ARGS.get(chart, []))
        pods = 0
        errors = []
        for doc in yaml.safe_load_all(rendered):
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") not in POD_BEARING_KINDS:
                continue
            spec, name = pod_spec_of(doc)
            if spec is None:
                errors.append(
                    f"{doc.get('kind')}/{name or '?'}: "
                    "recognized workload kind but no pod spec found")
                continue
            pods += 1
            errors.extend(check_pod(chart, name, spec))
        if errors:
            failures += 1
            print(f"FAIL {chart} ({pods} pod spec(s)):")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"OK   {chart} ({pods} pod spec(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
