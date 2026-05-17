"""Unit tests for :class:`DualModuleCheckStep` (issue #1031).

The step runs from the DebounceCoordinator's ``threading.Timer`` thread.
``sys.exit(1)`` from a non-main thread only raises ``SystemExit`` in that
thread — the main thread would happily continue serving traffic with the
broken dual-module DI state. The check must therefore use ``os._exit(1)``
to terminate the process for real.

These tests verify both branches:

- Collision present: ``os._exit(1)`` is called AND the framed error message
  is logged in a single ``logger.error`` call.
- Clean registry: ``os._exit`` is NOT called and the step returns a
  successful :class:`PipelineResult`.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from _mcp_mesh.pipeline.mcp_startup.dual_module_check import DualModuleCheckStep
from _mcp_mesh.pipeline.shared import PipelineStatus


@pytest.mark.asyncio
async def test_dual_module_collision_triggers_os_exit(caplog):
    """A __main__ + sibling-module collision must call os._exit(1)."""
    step = DualModuleCheckStep()

    fake_injector = MagicMock()
    fake_injector.iter_dependency_keys.return_value = [
        "__main__.dispatch_llm_participant:dep_0",
        "main.dispatch_llm_participant:dep_0",
    ]

    with caplog.at_level(logging.ERROR), patch(
        "_mcp_mesh.pipeline.mcp_startup.dual_module_check.get_global_injector",
        return_value=fake_injector,
    ), patch(
        "_mcp_mesh.pipeline.mcp_startup.dual_module_check.os._exit"
    ) as mock_exit:
        await step.execute({})

    mock_exit.assert_called_once_with(1)

    # The framed error must be emitted as a SINGLE logger.error call so
    # JSON / structured-log formatters don't shred the frame across many
    # records with prepended metadata.
    framed_records = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and "Detected duplicate tool registrations" in r.message
    ]
    assert len(framed_records) == 1
    framed_msg = framed_records[0].message
    assert "__main__.dispatch_llm_participant:dep_0" in framed_msg
    assert "main.dispatch_llm_participant:dep_0" in framed_msg
    # Frame delimiter present.
    assert "=" * 70 in framed_msg


@pytest.mark.asyncio
async def test_clean_registry_returns_success_without_exiting():
    """A collision-free registry must NOT call os._exit and must succeed."""
    step = DualModuleCheckStep()

    fake_injector = MagicMock()
    fake_injector.iter_dependency_keys.return_value = [
        "pkg.foo:dep_0",
        "pkg.bar:dep_1",
        "__main__.solo:dep_0",
    ]

    with patch(
        "_mcp_mesh.pipeline.mcp_startup.dual_module_check.get_global_injector",
        return_value=fake_injector,
    ), patch(
        "_mcp_mesh.pipeline.mcp_startup.dual_module_check.os._exit"
    ) as mock_exit:
        result = await step.execute({})

    mock_exit.assert_not_called()
    assert result.status == PipelineStatus.SUCCESS
