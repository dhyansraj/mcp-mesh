"""
Pipeline step that aborts startup if @mesh.tool was registered under both
``__main__.X`` and ``<module>.X`` (issue #1031).

Runs after all decorators have fired (so the global DI mapping is
populated) but before heartbeat config is prepared (so the user sees the
error immediately, before the agent starts serving traffic).
"""

import os
from typing import Any

from ...engine.dependency_injector import get_global_injector
from ...engine.dual_module_detection import detect_dual_module_registration
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class DualModuleCheckStep(PipelineStep):
    """
    Detect tools registered under both ``__main__.X`` and ``<module>.X``
    fully-qualified names and abort startup if found.

    This catches the ``python main.py`` + ``from main import X`` footgun
    where Python evaluates the entry script twice as two distinct module
    objects (``__main__`` and ``main``), the ``@mesh.tool`` decorator
    fires twice, and the resulting two registrations carry independent DI
    state. See :mod:`_mcp_mesh.engine.dual_module_detection` for details.
    """

    def __init__(self):
        super().__init__(
            name="dual-module-check",
            required=True,
            description=(
                "Abort if @mesh.tool was registered under both __main__.X "
                "and <module>.X (issue #1031)"
            ),
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult(message="No dual-module registrations detected")

        try:
            injector = get_global_injector()
            registry_keys = list(injector.iter_dependency_keys())

            collisions = detect_dual_module_registration(registry_keys)
            if not collisions:
                return result

            # Loud, clearly-framed error so the user sees the issue
            # immediately instead of debugging "why is my dependency
            # mysteriously None" at runtime. Emit as a SINGLE logger call
            # so JSON / structured-log formatters that prepend per-record
            # metadata don't shred the frame.
            lines = [
                "=" * 70,
                "Detected duplicate tool registrations under multiple module names:",
            ]
            for _suffix, main_key, other_key in collisions:
                lines.append(f"  - {main_key}")
                lines.append(f"  - {other_key}")
            lines.extend(
                [
                    "",
                    "This usually means you're running `python main.py` while another",
                    "module in your agent does `from main import X`. Python evaluates",
                    "main.py twice as separate modules, producing two independent",
                    "registrations with mismatched DI state.",
                    "",
                    "Fix: restructure your agent as a package and run with",
                    "`python -m pkg.main`. Sibling modules then `from pkg.main import X`",
                    "and Python reuses the same module instance.",
                    "=" * 70,
                ]
            )
            self.logger.error("\n".join(lines))

            # ``sys.exit(1)`` would only raise SystemExit in the CALLING
            # thread (the DebounceCoordinator's threading.Timer thread) —
            # the main thread would happily continue serving traffic with
            # broken DI state. ``os._exit`` is the process-wide
            # immediate-exit primitive; it skips Python finalizers /
            # atexit hooks / buffer flushes but that's appropriate here
            # because (a) the check fires BEFORE any traffic is served
            # so there's no in-flight state to drain, (b) the framed
            # error has already been logged synchronously above so the
            # user sees the diagnostic, and (c) the entire point of this
            # step is "refuse to start with broken DI state."
            os._exit(1)

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Dual-module check failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Dual-module check failed: {e}")

        return result
