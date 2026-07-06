"""Entry point for `python -m transcribe-provider` (run from examples/python/service-view/)."""

from . import main  # noqa: F401 — importing `main` triggers the @mesh.agent decorator
