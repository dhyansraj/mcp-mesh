"""Issue #1617: ``mesh.a2a`` is both the ``@mesh.a2a`` decorator and the
``mesh/a2a.py`` submodule (home of ``mesh.a2a.mount``).

Importing the submodule binds it as the ``mesh.a2a`` package attribute, after
which the package ``__getattr__`` is never consulted again. Every spelling
must keep working whatever the import order, so each scenario runs in a fresh
interpreter: in-process, an earlier test may already have imported the
submodule and hidden the failing order.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import mesh

_PKG_ROOT = str(Path(mesh.__file__).resolve().parent.parent)

_PRELUDE = """
import mesh

def _assert_decorates(path):
    @mesh.a2a(path=path)
    def handler():
        return "ok"

    assert handler() == "ok"
    assert handler._mesh_a2a_metadata["path"] == path
"""


def _run(body: str) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (_PKG_ROOT, env.get("PYTHONPATH")) if p
    )
    env["MCP_MESH_ENABLED"] = "false"
    env["MCP_MESH_AUTO_RUN"] = "false"
    script = textwrap.dedent(_PRELUDE) + textwrap.dedent(body) + "\nprint('PASS')\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0 and "PASS" in result.stdout.splitlines(), (
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


SCENARIOS = {
    "decorator_only": """
        _assert_decorates("/a")
    """,
    "import_submodule_then_decorate": """
        import mesh.a2a
        _assert_decorates("/a")
    """,
    "from_submodule_import_then_decorate": """
        from mesh.a2a import mount
        assert callable(mount)
        _assert_decorates("/a")
    """,
    "decorate_then_import_submodule_then_decorate": """
        _assert_decorates("/a")
        import mesh.a2a
        from mesh.a2a import get_cached_public_url
        assert get_cached_public_url("/a", "x") is None
        _assert_decorates("/b")
    """,
    "mount_then_decorate": """
        from fastapi import FastAPI

        app = FastAPI()

        @mesh.a2a.mount(app, path="/mounted")
        def mounted():
            return "ok"

        _assert_decorates("/a")
    """,
    "import_submodule_then_mount": """
        import mesh.a2a
        from fastapi import FastAPI

        app = FastAPI()

        @mesh.a2a.mount(app, path="/mounted")
        def mounted():
            return "ok"

        assert any(r.path == "/mounted" for r in app.routes)
    """,
    "decorator_attribute_stable_across_import": """
        before = mesh.a2a
        import mesh.a2a
        assert mesh.a2a is before
    """,
}


@pytest.mark.parametrize("body", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_mesh_a2a_spellings_work_in_any_import_order(body):
    _run(body)
