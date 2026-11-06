"""Anthropic Messages API."""
from __future__ import annotations

import os
from typing import Any

import httpx

from .base import Completion, Image, Message


class AnthropicBrain:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.name = "anthropic"
        self.base_url = (cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
        self.model = cfg.get("model") or "claude-sonnet-4-5"
        key_env = cfg.get("api_key_env") or "ANTHROPIC_API_KEY"
        self.api_key = cfg.get("api_key") or os.environ.get(key_env, "")
        self.supports_images = True
        self.timeout = float(cfg.get("timeout_seconds", 120))
        self.max_tokens = int(cfg.get("max_output_tokens", 4000))
        self.temperature = cfg.get("temperature", 0.2)

    def complete(self, system: str, messages: list[Message], images: list[Image] | None = None, *, json: bool = True) -> Completion:
        msgs: list[dict[str, Any]] = []
        for i, m in enumerate(messages):
            if images and i == len(messages) - 1 and m.role == "user":
                parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
                for im in images:
                    if im.caption:
                        parts.append({"type": "text", "text": f"[screenshot: {im.caption}]"})
                    parts.append({"type": "image", "source": {"type": "base64", "media_type": im.mime, "data": im.base64}})
                msgs.append({"role": m.role, "content": parts})
            else:
                msgs.append({"role": m.role, "content": m.content})
        if json:
            msgs.append({"role": "assistant", "content": "{"})  # prefill to force a JSON object
        body = {"model": self.model, "system": system, "messages": msgs, "max_tokens": self.max_tokens, "temperature": self.temperature}
        headers = {"content-type": "application/json", "x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/v1/messages", json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
        text = "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")
        if json:
            text = "{" + text
        usage = data.get("usage") or {}
        return Completion(text=text, model=data.get("model", self.model), input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0), raw=data)
