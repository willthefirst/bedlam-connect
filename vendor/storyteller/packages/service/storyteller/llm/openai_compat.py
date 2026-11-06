"""OpenAI-compatible chat completions: OpenAI, Ollama, vLLM, LM Studio, most internal gateways."""
from __future__ import annotations

import os
from typing import Any

import httpx

from .base import Completion, Image, Message


class OpenAICompatibleBrain:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.name = "openai_compatible"
        self.base_url = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.model = cfg.get("model") or "gpt-4o-mini"
        key_env = cfg.get("api_key_env") or "OPENAI_API_KEY"
        self.api_key = cfg.get("api_key") or os.environ.get(key_env, "")
        self.supports_images = bool(cfg.get("supports_images", True))
        self.timeout = float(cfg.get("timeout_seconds", 120))
        self.extra_headers = dict(cfg.get("headers") or {})
        self.temperature = cfg.get("temperature", 0.2)

    def complete(self, system: str, messages: list[Message], images: list[Image] | None = None, *, json: bool = True) -> Completion:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for i, m in enumerate(messages):
            if images and self.supports_images and i == len(messages) - 1 and m.role == "user":
                parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
                for im in images:
                    if im.caption:
                        parts.append({"type": "text", "text": f"[screenshot: {im.caption}]"})
                    parts.append({"type": "image_url", "image_url": {"url": f"data:{im.mime};base64,{im.base64}"}})
                msgs.append({"role": m.role, "content": parts})
            else:
                msgs.append({"role": m.role, "content": m.content})
        body: dict[str, Any] = {"model": self.model, "messages": msgs, "temperature": self.temperature}
        if json:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            if r.status_code == 400 and json and "response_format" in r.text:
                body.pop("response_format")  # server doesn't support json mode; the prompt still asks for JSON
                r = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        return Completion(text=text, model=data.get("model", self.model), input_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("completion_tokens", 0), raw=data)
