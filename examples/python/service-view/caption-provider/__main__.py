"""Entry point for `python -m caption-provider` (run from examples/python/service-view/)."""

from . import main  # noqa: F401 — importing `main` triggers the @mesh.agent decorator
