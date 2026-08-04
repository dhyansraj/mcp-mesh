#!/usr/bin/env python3
"""Assert that a pod volume never changes TYPE while keeping the same NAME.

Kubernetes merges `spec.template.spec.volumes` by `name`. A chart that renders

    - name: storage
      {{- if .Values.persistence.enabled }}
      persistentVolumeClaim: {...}
      {{- else }}
      emptyDir: {}
      {{- end }}

is therefore describing two different objects under one merge key. Under
server-side apply, if the `persistentVolumeClaim` field set is owned by a
different field manager than the one now applying `emptyDir`, both survive the
merge and the API server rejects the object outright:

    spec.template.spec.volumes[1].persistentVolumeClaim: Forbidden:
      may not specify more than 1 volume type

The Deployment then sticks unsyncable until someone deletes it by hand. This
happened on the 3.3.2 -> 3.4.0 upgrade when tempo's `persistence.enabled`
default flipped, and it is bidirectional — re-enabling persistence hits the
identical failure in reverse (#1461).

The fix is to make the name carry the type, so that toggling persistence is a
*key* change: remove-item plus add-item on distinct keys, which is always
representable. This check pins that fix. It renders each chart in every state
that moves a persistence toggle and asserts:

  1. No volume name maps to two different types across any pair of states.
     This is the real assertion — a direct statement of "a type change must be
     a key change". Collapsing a conditional volume name back to a constant
     turns it red.
  2. Every volumeMount name resolves to a volume of that name, in every state.
     Assertion 1 is satisfied by renaming, and renaming is exactly how the
     matching mount gets left behind — that mistake produces a differently
     invalid Deployment, so the two must be checked together.
  3. No volume declares more than one type in a single render.

StatefulSet volumeClaimTemplates participate as the pseudo-type
`volumeClaimTemplate`: they are named storage a mount can resolve against, and
converting one into a pod volume of the same name is the same defect class.

WHAT THIS CANNOT SEE: field-manager ownership. Every assertion here is made
against `helm template` output, so this proves the *charts* never ask for an
unrepresentable merge. It does not exercise a real server-side apply against a
live API server with real ownership history, which is the mechanism that
turned the chart bug into an outage. A genuine SSA-upgrade test remains an open
question — do not read a green run here as closing it.

Usage: python3 scripts/check_helm_volume_keys.py  (run from anywhere)
       python3 scripts/check_helm_volume_keys.py --helm-dir path/to/helm
Exit code 0 = every chart keeps volume type and volume name in lockstep.
"""

import argparse
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_helm_pss  # noqa: E402
from check_helm_pss import (  # noqa: E402
    HELM_DIR,
    POD_BEARING_KINDS,
    build_dependencies,
    pod_spec_of,
)

VOLUME_CLAIM_TEMPLATE = "volumeClaimTemplate"

# Keys that appear on a volume entry without being a volume type.
NON_TYPE_VOLUME_KEYS = {"name"}


@dataclass(frozen=True)
class State:
    """One render of one chart: a label and the values that produce it."""

    label: str
    values: dict = field(default_factory=dict)


# Every chart whose values carry a persistence toggle, rendered in each state
# that toggle can put it in. scripts/test_check_helm_volume_keys.py asserts
# this covers all of them, so a new chart with a persistence block cannot land
# uncovered.
#
# Charts with no persistence toggle are still rendered (single default state)
# so assertions 2 and 3 cover them; only assertion 1 needs two states to say
# anything.
STATES: dict[str, list[State]] = {
    "mcp-mesh-tempo": [
        State("persistence on", {"tempo": {"persistence": {"enabled": True}}}),
        State("persistence off", {"tempo": {"persistence": {"enabled": False}}}),
    ],
    "mcp-mesh-grafana": [
        State("persistence on", {"grafana": {"persistence": {"enabled": True}}}),
        State("persistence off", {"grafana": {"persistence": {"enabled": False}}}),
    ],
    # The registry's data volume is gated on `persistence.enabled OR
    # database.type == sqlite`, so toggling persistence alone leaves the state
    # that actually swapped type (sqlite with persistence off, which renders an
    # emptyDir under the same name the PVC uses) unrendered. Both dimensions.
    "mcp-mesh-registry": [
        State(
            "postgres, persistence on",
            {"persistence": {"enabled": True}, "registry": {"database": {"type": "postgres"}}},
        ),
        State(
            "postgres, persistence off",
            {"persistence": {"enabled": False}, "registry": {"database": {"type": "postgres"}}},
        ),
        State(
            "sqlite, persistence on",
            {"persistence": {"enabled": True}, "registry": {"database": {"type": "sqlite"}}},
        ),
        State(
            "sqlite, persistence off",
            {"persistence": {"enabled": False}, "registry": {"database": {"type": "sqlite"}}},
        ),
    ],
    # This chart renders no PVC, so persistence.enabled requires an
    # existingClaim — a template-time guard fails the render without one.
    "mcp-mesh-redis": [
        State(
            "persistence on",
            {"persistence": {"enabled": True, "existingClaim": "some-claim"}},
        ),
        State("persistence off", {"persistence": {"enabled": False}}),
    ],
    # Not affected today: the whole volume sits inside the conditional, so
    # toggling persistence adds or removes a list item rather than swapping a
    # type under a stable key. Covered anyway — adding an `else` branch here is
    # precisely how it would become affected.
    "mcp-mesh-agent": [
        State("persistence on", {"persistence": {"enabled": True}}),
        State("persistence off", {"persistence": {"enabled": False}}),
    ],
    # postgres-data is a StatefulSet volumeClaimTemplate rather than a pod
    # volume, which is why this chart has never been at risk. Rendered so that
    # converting it into a pod volume under the same name would be caught.
    "mcp-mesh-postgres": [
        State("persistence on", {"persistence": {"enabled": True}}),
        State("persistence off", {"persistence": {"enabled": False}}),
    ],
    # The umbrella is what most installations actually apply, and it is where
    # a subchart's toggle reaches a user. ui.enabled renders the optional pod.
    "mcp-mesh-core": [
        State("defaults", {"ui": {"enabled": True}}),
        State(
            "persistence on everywhere",
            {
                "ui": {"enabled": True},
                "mcp-mesh-tempo": {"tempo": {"persistence": {"enabled": True}}},
                "mcp-mesh-grafana": {"grafana": {"persistence": {"enabled": True}}},
                "mcp-mesh-registry": {"persistence": {"enabled": True}},
                "mcp-mesh-redis": {
                    "persistence": {"enabled": True, "existingClaim": "some-claim"}
                },
            },
        ),
        State(
            "persistence off everywhere",
            {
                "ui": {"enabled": True},
                "mcp-mesh-tempo": {"tempo": {"persistence": {"enabled": False}}},
                "mcp-mesh-grafana": {"grafana": {"persistence": {"enabled": False}}},
                "mcp-mesh-registry": {"persistence": {"enabled": False}},
                "mcp-mesh-redis": {"persistence": {"enabled": False}},
            },
        ),
    ],
}


# ---------------------------------------------------------------------------
# Analysis. Pure functions over already-parsed manifests: no helm, no yaml, so
# scripts/test_check_helm_volume_keys.py can drive them from literal dicts.
# ---------------------------------------------------------------------------


def volume_types(vol: dict) -> list[str]:
    """The type keys on one volume entry. Exactly one is legal."""
    return sorted(set(vol) - NON_TYPE_VOLUME_KEYS)


def volume_index(doc: dict, spec: dict) -> dict[str, str]:
    """name -> type for everything a volumeMount in this workload can name.

    A volume with zero or several types maps to a marker rather than being
    dropped, so that assertion 1 still has something to compare and does not
    silently go quiet on a malformed render.
    """
    index: dict[str, str] = {}
    for vol in spec.get("volumes") or []:
        types = volume_types(vol)
        index[vol.get("name")] = types[0] if len(types) == 1 else f"<{len(types)} types>"
    if doc.get("kind") == "StatefulSet":
        for vct in doc.get("spec", {}).get("volumeClaimTemplates") or []:
            index[vct.get("metadata", {}).get("name")] = VOLUME_CLAIM_TEMPLATE
    return index


def spec_problems(doc: dict, spec: dict) -> list[str]:
    """Assertions 2 and 3, against a single rendered workload."""
    problems = []
    volumes = spec.get("volumes") or []

    for vol in volumes:
        types = volume_types(vol)
        if len(types) > 1:
            problems.append(
                f"volume {vol.get('name')!r} declares {len(types)} types "
                f"({', '.join(types)}); a volume may specify exactly one"
            )
        elif not types:
            problems.append(f"volume {vol.get('name')!r} declares no type")

    names = [v.get("name") for v in volumes]
    for dupe in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"volume name {dupe!r} is used more than once")

    index = volume_index(doc, spec)
    containers = (spec.get("containers") or []) + (spec.get("initContainers") or [])
    for c in containers:
        for mount in c.get("volumeMounts") or []:
            if mount.get("name") not in index:
                problems.append(
                    f"{c.get('name')}: volumeMount {mount.get('name')!r} names no "
                    f"volume in this pod (have: {sorted(index) or 'none'})"
                )
    return problems


def type_collisions(per_state: dict[str, dict[str, dict[str, str]]]) -> list[str]:
    """Assertion 1.

    `per_state` is {state label: {workload name: {volume name: type}}}. A
    volume name that appears in two states carrying different types is a merge
    key describing two different objects — the #1461 defect.
    """
    problems = []
    for left, right in combinations(sorted(per_state), 2):
        workloads = set(per_state[left]) & set(per_state[right])
        for workload in sorted(workloads):
            a, b = per_state[left][workload], per_state[right][workload]
            for name in sorted(set(a) & set(b)):
                if a[name] != b[name]:
                    problems.append(
                        f"{workload}: volume {name!r} is {a[name]} with {left!r} but "
                        f"{b[name]} with {right!r} — a volume that changes type must "
                        f"change name, or server-side apply can merge both types "
                        f"under this one key and the API server rejects the object"
                    )
    return problems


def index_render(docs) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Walk parsed manifests once: build the per-workload volume index and
    collect the single-render problems."""
    index: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") not in POD_BEARING_KINDS:
            continue
        spec, name = pod_spec_of(doc)
        if spec is None:
            continue
        index[name] = volume_index(doc, spec)
        problems.extend(f"{name}/{p}" for p in spec_problems(doc, spec))
    return index, problems


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render(chart: str, state: State, helm_dir: Path) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as values_file:
        yaml.safe_dump(state.values, values_file)
        values_file.flush()
        result = subprocess.run(
            [
                "helm",
                "template",
                "volume-keys",
                str(helm_dir / chart),
                "--values",
                values_file.name,
            ],
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        print(f"FAIL {chart} [{state.label}]: helm template failed:\n{result.stderr}")
        sys.exit(1)
    return result.stdout


def discover_charts(helm_dir: Path) -> list[str]:
    return sorted(d.name for d in helm_dir.iterdir() if (d / "Chart.yaml").is_file())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--helm-dir",
        type=Path,
        default=HELM_DIR,
        help="chart directory to check (default: helm/ in this repo). Point it "
        "at a worktree to confirm the check goes red on an older tree.",
    )
    args = parser.parse_args(argv)
    helm_dir = args.helm_dir.resolve()
    # build_dependencies packages subcharts relative to its own module global.
    check_helm_pss.HELM_DIR = helm_dir

    charts = discover_charts(helm_dir)
    failures = 0
    for chart in charts:
        build_dependencies(chart)
        states = STATES.get(chart) or [State("defaults")]
        per_state: dict[str, dict[str, dict[str, str]]] = {}
        problems: list[str] = []
        for state in states:
            docs = list(yaml.safe_load_all(render(chart, state, helm_dir)))
            index, found = index_render(docs)
            per_state[state.label] = index
            problems.extend(f"[{state.label}] {p}" for p in found)
        problems.extend(type_collisions(per_state))

        if problems:
            failures += 1
            print(f"FAIL {chart} ({len(states)} state(s)):")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"OK   {chart} ({len(states)} state(s))")

    print(
        f"\n{len(charts) - failures}/{len(charts)} charts keep volume name "
        "and type in lockstep"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
