"""
Pipeline step that aborts startup if @mesh.tool was registered under both
``__main__.X`` and ``<module>.X`` (issue #1031).

Runs after all decorators have fired (so the global DI mapping is
populated) but before heartbeat config is prepared (so the user sees the
error immediately, before the agent starts serving traffic).
"""

import sys
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
            registry_keys = list(injector._dependency_mapping.keys())

            collisions = detect_dual_module_registration(registry_keys)
            if not collisions:
                return result

            # Loud, clearly-framed error so the user sees the issue
            # immediately instead of debugging "why is my dependency
            # mysteriously None" at runtime.
            self.logger.error("=" * 70)
            self.logger.error(
                "Detected duplicate tool registrations under multiple module names:"
            )
            for _suffix, main_key, other_key in collisions:
                self.logger.error(f"  - {main_key}")
                self.logger.error(f"  - {other_key}")
            self.logger.error("")
            self.logger.error(
                "This usually means you're running `python main.py` while another"
            )
            self.logger.error(
                "module in your agent does `from main import X`. Python evaluates"
            )
            self.logger.error(
                "main.py twice as separate modules, producing two independent"
            )
            self.logger.error(
                "registrations with mismatched DI state."
            )
            self.logger.error("")
            self.logger.error(
                "Fix: restructure your agent as a package and run with"
            )
            self.logger.error(
                "`python -m pkg.main`. Sibling modules then `from pkg.main import X`"
            )
            self.logger.error(
                "and Python reuses the same module instance."
            )
            self.logger.error("=" * 70)

            sys.exit(1)

        except SystemExit:
            # Re-raise SystemExit so the process actually exits — don't let
            # the broad except below swallow it as a "failed" pipeline step.
            raise
        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Dual-module check failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Dual-module check failed: {e}")

        return result
