"""Source adapters. Each adapter parses one source's raw payload into an
AdapterResult. Register live adapters in REGISTRY so the CLI can find them."""
from __future__ import annotations

from typing import Callable

# adapter_id -> module providing fetch()/parse(); populated by import side effects.
REGISTRY: dict[str, Callable] = {}


def register(adapter_id: str):
    def _wrap(fn):
        REGISTRY[adapter_id] = fn
        return fn
    return _wrap
