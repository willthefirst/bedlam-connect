"""Load a consumer-written brain: llm.custom_module = "mypkg.brains:JevBrain" (class or factory taking the llm config dict)."""
from __future__ import annotations

import importlib
from typing import Any

from .base import Brain


def load_custom(cfg: dict[str, Any]) -> Brain:
    spec = cfg.get("custom_module")
    if not spec or ":" not in spec:
        raise ValueError('llm.custom_module must look like "package.module:ClassName"')
    mod_name, attr = spec.split(":", 1)
    obj = getattr(importlib.import_module(mod_name), attr)
    brain = obj(cfg)
    if not hasattr(brain, "complete"):
        raise TypeError(f"{spec} does not implement complete(system, messages, images=None, *, json=True)")
    if not hasattr(brain, "supports_images"):
        brain.supports_images = False
    if not hasattr(brain, "name"):
        brain.name = attr
    return brain
