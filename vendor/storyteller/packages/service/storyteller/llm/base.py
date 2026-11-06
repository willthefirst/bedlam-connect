"""
The brain interface. The storyteller calls exactly one method:

    brain.complete(system, messages, images=None, json=True) -> Completion

Ship two implementations (OpenAI-compatible, Anthropic); anything else is one
consumer-written class with the same shape, named in config as "pkg.module:Class".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class Image:
    mime: str  # "image/jpeg" | "image/png"
    base64: str
    caption: str = ""


@dataclass
class Completion:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Any = field(default=None, repr=False)


@runtime_checkable
class Brain(Protocol):
    name: str
    supports_images: bool

    def complete(self, system: str, messages: list[Message], images: list[Image] | None = None, *, json: bool = True) -> Completion: ...


def load_brain(cfg: dict[str, Any]) -> Brain:
    """Instantiate a brain from the `llm` config section."""
    provider = (cfg.get("provider") or "openai_compatible").lower()
    if provider in ("openai", "openai_compatible", "ollama", "vllm"):
        from .openai_compat import OpenAICompatibleBrain

        return OpenAICompatibleBrain(cfg)
    if provider == "anthropic":
        from .anthropic import AnthropicBrain

        return AnthropicBrain(cfg)
    if provider == "custom":
        from .custom import load_custom

        return load_custom(cfg)
    raise ValueError(f"unknown llm.provider: {provider!r}")
