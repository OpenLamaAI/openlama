"""Channel interface."""
from __future__ import annotations
from abc import ABC, abstractmethod


class Channel(ABC):
    @abstractmethod
    async def start(self): ...

    @abstractmethod
    async def stop(self): ...
