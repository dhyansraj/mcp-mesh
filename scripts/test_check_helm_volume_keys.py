#!/usr/bin/env python3
"""Checks for scripts/check_helm_volume_keys.py (#1461).

The analysis in that script is pure functions over parsed manifests, so almost
everything here drives it from literal dicts rather than rendering charts. That
is deliberate: a guard tested only by "the real tree is clean today" passes for
the wrong reason the moment its logic is broken, which is how the defect it
pins got in. Each failure mode is proven separately to go red.

Only the end-to-end tests need `helm` on PATH and skip without it.
"""

import importlib.util
import pathlib
import shutil

import yaml

_spec = importlib.util.spec_from_file_location(
    "check_helm_volume_keys",
    pathlib.Path(__file__).with_name("check_helm_volume_keys.py"),
)
cvk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvk)

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
HELM_DIR = PROJECT_ROOT / "helm"


def _requires_helm() -> bool:
    """True when the caller should bail out. Under pytest this raises Skipped
    instead of returning, so the run reports it rather than passing quietly."""
    if shutil.which("helm"):
        return False
    try:
        import pytest

        pytest.skip("helm is not installed")
    except ImportError:
        pass
    return True


def _deployment(volumes, mounts=(), name="dep", init_mounts=()):
    return {
        "kind": "Deployment",
        "metadata": {"name": name},
        "spec": {
            "template": {
                "spec": {
                    "volumes": list(volumes),
                    "containers": [
                        {
                            "name": "app",
                            "volumeMounts": [{"name": m, "mountPath": "/x"} for m in mounts],
                        }
                    ],
                    "initContainers": [
                        {
                            "name": "init",
                            "volumeMounts": [
                                {"name": m, "mountPath": "/x"} for m in init_mounts
                            ],
                        }
                    ]
                    if init_mounts
                    else [],
                }
            }
        },
    }


def _spec_of(doc):
    return doc["spec"]["template"]["spec"]


# --------------------------------------------------------------------------
# Assertion 1: a type change must be a key change. The real one.
# --------------------------------------------------------------------------


def test_a_type_swap_under_a_stable_name_is_flagged():
    """The #1461 defect exactly: one merge key, two different objects."""
    found = cvk.type_collisions(
        {
            "persistence on": {"dep": {"storage": "persistentVolumeClaim"}},
            "persistence off": {"dep": {"storage": "emptyDir"}},
        }
    )
    assert len(found) == 1, found
    assert "'storage'" in found[0]
    assert "persistentVolumeClaim" in found[0] and "emptyDir" in found[0]


def test_the_fix_shape_is_not_flagged():
    """Type carried in the name: the two states share no key, so server-side
    apply sees remove-item plus add-item and a dual-type volume is not
    representable."""
    assert (
        cvk.type_collisions(
            {
                "persistence on": {"dep": {"storage": "persistentVolumeClaim"}},
                "persistence off": {"dep": {"storage-ephemeral": "emptyDir"}},
            }
        )
        == []
    )


def test_an_add_remove_volume_is_not_flagged():
    """mcp-mesh-agent's shape — the whole volume inside the conditional. There
    is no second type to collide with, so this must stay green or the check
    would be demanding a rename nobody needs."""
    assert (
        cvk.type_collisions(
            {
                "persistence on": {"dep": {"data": "persistentVolumeClaim"}},
                "persistence off": {"dep": {}},
            }
        )
        == []
    )


def test_all_state_pairs_are_compared_not_just_neighbours():
    """The registry has four states and the collision is between two of them
    that are not adjacent in declaration order. Comparing consecutive states
    only would call that tree clean."""
    found = cvk.type_collisions(
        {
            "a": {"dep": {"data": "persistentVolumeClaim"}},
            "b": {"dep": {}},
            "c": {"dep": {"data": "emptyDir"}},
        }
    )
    assert len(found) == 1, found
    assert "'a'" in found[0] and "'c'" in found[0]


def test_a_collision_in_a_different_workload_is_reported_per_workload():
    found = cvk.type_collisions(
        {
            "on": {
                "dep-a": {"storage": "persistentVolumeClaim"},
                "dep-b": {"storage": "configMap"},
            },
            "off": {
                "dep-a": {"storage": "emptyDir"},
                "dep-b": {"storage": "configMap"},
            },
        }
    )
    assert len(found) == 1, found
    assert found[0].startswith("dep-a:")


def test_a_volume_becoming_a_claim_template_collides():
    """Converting a StatefulSet volumeClaimTemplate into a pod volume of the
    same name is the same defect wearing different clothes."""
    found = cvk.type_collisions(
        {
            "on": {"sts": {"pgdata": cvk.VOLUME_CLAIM_TEMPLATE}},
            "off": {"sts": {"pgdata": "emptyDir"}},
        }
    )
    assert len(found) == 1, found


# --------------------------------------------------------------------------
# Assertion 2: mounts must resolve. The trap the #1461 fix itself can spring.
# --------------------------------------------------------------------------


def test_a_mount_naming_no_volume_is_flagged():
    """Renaming the volume and forgetting the mount — the exact way a fix for
    assertion 1 produces a differently invalid Deployment."""
    doc = _deployment([{"name": "storage-ephemeral", "emptyDir": {}}], mounts=["storage"])
    found = cvk.spec_problems(doc, _spec_of(doc))
    assert len(found) == 1, found
    assert "volumeMount 'storage' names no volume" in found[0]


def test_a_mount_in_an_init_container_is_checked_too():
    doc = _deployment(
        [{"name": "data", "emptyDir": {}}], mounts=["data"], init_mounts=["gone"]
    )
    found = cvk.spec_problems(doc, _spec_of(doc))
    assert len(found) == 1, found
    assert "init:" in found[0] and "'gone'" in found[0]


def test_a_mount_resolving_to_a_claim_template_is_accepted():
    """A StatefulSet mount names its volumeClaimTemplate, not a pod volume.
    Without this the check would report every StatefulSet as broken."""
    doc = {
        "kind": "StatefulSet",
        "metadata": {"name": "sts"},
        "spec": {
            "volumeClaimTemplates": [{"metadata": {"name": "pgdata"}}],
            "template": {
                "spec": {
                    "volumes": [],
                    "containers": [
                        {"name": "db", "volumeMounts": [{"name": "pgdata"}]}
                    ],
                }
            },
        },
    }
    assert cvk.spec_problems(doc, doc["spec"]["template"]["spec"]) == []


def test_a_clean_spec_is_silent():
    doc = _deployment(
        [{"name": "data", "emptyDir": {}}, {"name": "cfg", "configMap": {"name": "c"}}],
        mounts=["data", "cfg"],
    )
    assert cvk.spec_problems(doc, _spec_of(doc)) == []


# --------------------------------------------------------------------------
# Assertion 3: one type per volume
# --------------------------------------------------------------------------


def test_a_dual_type_volume_is_flagged():
    """What the API server actually rejects, should a chart ever render it
    directly rather than have SSA merge it into existence."""
    doc = _deployment(
        [{"name": "storage", "emptyDir": {}, "persistentVolumeClaim": {"claimName": "c"}}],
        mounts=["storage"],
    )
    found = cvk.spec_problems(doc, _spec_of(doc))
    assert len(found) == 1, found
    assert "declares 2 types" in found[0]


def test_a_typeless_volume_is_flagged():
    doc = _deployment([{"name": "storage"}], mounts=["storage"])
    found = cvk.spec_problems(doc, _spec_of(doc))
    assert any("declares no type" in p for p in found), found


def test_a_duplicated_volume_name_is_flagged():
    doc = _deployment(
        [{"name": "storage", "emptyDir": {}}, {"name": "storage", "emptyDir": {}}],
        mounts=["storage"],
    )
    found = cvk.spec_problems(doc, _spec_of(doc))
    assert any("used more than once" in p for p in found), found


def test_a_malformed_volume_still_indexes_so_it_can_collide():
    """A dual-type volume must not vanish from the index — dropping it would
    make assertion 1 go quiet on the worst possible render."""
    doc = _deployment([{"name": "storage", "emptyDir": {}, "configMap": {}}])
    assert cvk.volume_index(doc, _spec_of(doc)) == {"storage": "<2 types>"}


def test_non_workload_documents_are_ignored():
    index, problems = cvk.index_render(
        [
            None,
            {"kind": "Service", "metadata": {"name": "svc"}, "spec": {}},
            _deployment([{"name": "data", "emptyDir": {}}], mounts=["data"]),
        ]
    )
    assert list(index) == ["dep"]
    assert problems == []


# --------------------------------------------------------------------------
# The declared matrix must actually cover the tree
# --------------------------------------------------------------------------


def _values(chart: str) -> dict:
    return yaml.safe_load((HELM_DIR / chart / "values.yaml").read_text()) or {}


def _has_persistence_toggle(values: dict) -> bool:
    if isinstance(values, dict):
        if isinstance(values.get("persistence"), dict) and "enabled" in values["persistence"]:
            return True
        return any(_has_persistence_toggle(v) for v in values.values())
    return False


def test_every_chart_with_a_persistence_toggle_is_rendered_in_both_states():
    """A chart that grows a persistence toggle without a STATES entry gets
    rendered once, and assertion 1 needs two states to say anything — so it
    would join the tree already covered, silently uncovered."""
    uncovered = []
    for chart in cvk.discover_charts(HELM_DIR):
        if not _has_persistence_toggle(_values(chart)):
            continue
        if len(cvk.STATES.get(chart, [])) < 2:
            uncovered.append(chart)
    assert not uncovered, (
        "these charts toggle persistence but are not rendered in two states: "
        f"{uncovered}"
    )


def test_the_registry_matrix_keeps_its_second_dimension():
    """The registry's data volume is gated on `persistence.enabled OR
    database.type == sqlite`. Toggling persistence alone never renders the
    state that swapped type — sqlite with persistence off — so dropping the
    database dimension turns this chart into a false green while the defect is
    still there. Verified: pre-fix, the only collisions reported for the
    registry involve the sqlite-off state."""
    db_types = {
        (s.values.get("registry") or {}).get("database", {}).get("type")
        for s in cvk.STATES["mcp-mesh-registry"]
    }
    assert db_types == {"sqlite", "postgres"}, db_types
    persistence = {s.values["persistence"]["enabled"] for s in cvk.STATES["mcp-mesh-registry"]}
    assert persistence == {True, False}


def test_the_matrix_names_only_charts_that_exist():
    """A renamed chart would leave a STATES entry matching nothing, and the
    chart itself would fall back to a single default render."""
    charts = set(cvk.discover_charts(HELM_DIR))
    assert set(cvk.STATES) <= charts, set(cvk.STATES) - charts


def test_redis_persistence_state_names_a_claim():
    """The chart refuses persistence.enabled without existingClaim, so a state
    that omits it fails the render instead of being checked."""
    on = next(s for s in cvk.STATES["mcp-mesh-redis"] if s.values["persistence"]["enabled"])
    assert on.values["persistence"].get("existingClaim")


# --------------------------------------------------------------------------
# End to end, against the real charts
# --------------------------------------------------------------------------


def test_the_tree_is_clean():
    if _requires_helm():
        return
    assert cvk.main([]) == 0


def test_the_check_goes_red_on_a_chart_that_swaps_type(tmp_path):
    """Proves the whole pipeline, not just the pure functions: a minimal chart
    with the #1461 shape must fail, and the same chart with the name carrying
    the type must pass. Without this, a wiring mistake between rendering and
    analysis would leave every assertion above true and the script useless."""
    if _requires_helm():
        return

    def chart(root: pathlib.Path, volume_name: str) -> None:
        templates = root / "bad-chart" / "templates"
        templates.mkdir(parents=True)
        (root / "bad-chart" / "Chart.yaml").write_text(
            "apiVersion: v2\nname: bad-chart\nversion: 0.0.0\n"
        )
        (root / "bad-chart" / "values.yaml").write_text("persistence:\n  enabled: false\n")
        (templates / "deployment.yaml").write_text(
            f"""\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bad
spec:
  template:
    spec:
      containers:
        - name: app
          volumeMounts:
            - name: {volume_name}
              mountPath: /data
      volumes:
        - name: {volume_name}
          {{{{- if .Values.persistence.enabled }}}}
          persistentVolumeClaim:
            claimName: c
          {{{{- else }}}}
          emptyDir: {{}}
          {{{{- end }}}}
"""
        )

    stable = tmp_path / "stable"
    chart(stable, "storage")
    keyed = tmp_path / "keyed"
    chart(keyed, '{{ if .Values.persistence.enabled }}storage{{ else }}storage-ephemeral{{ end }}')

    states = [
        cvk.State("on", {"persistence": {"enabled": True}}),
        cvk.State("off", {"persistence": {"enabled": False}}),
    ]
    cvk.STATES["bad-chart"] = states
    try:
        assert cvk.main(["--helm-dir", str(stable)]) == 1
        assert cvk.main(["--helm-dir", str(keyed)]) == 0
    finally:
        del cvk.STATES["bad-chart"]
        cvk.check_helm_pss.HELM_DIR = HELM_DIR


if __name__ == "__main__":
    import tempfile

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        if fn.__code__.co_argcount:
            with tempfile.TemporaryDirectory() as d:
                fn(pathlib.Path(d))
        else:
            fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
