# coding: utf-8

from typing import ClassVar, Dict, List, Tuple  # noqa: F401

from pydantic import StrictStr


class BaseMonitoringApi:
    subclasses: ClassVar[Tuple] = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseMonitoringApi.subclasses = BaseMonitoringApi.subclasses + (cls,)

    async def get_agent_metrics(
        self,
    ) -> str:
        """Returns Prometheus metrics for agent monitoring.  🤖 AI NOTE: Standard Prometheus metrics endpoint."""
        ...
