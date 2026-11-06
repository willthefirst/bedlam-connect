"""Configuration: storyteller.yaml with ST_ env overrides."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "site": {"key": "", "allowed_origins": ["*"], "brief_file": "brief.md"},
    "recording": {"default_enabled": False, "idle_timeout_minutes": 10, "mask_all_text": False, "keep_screenshots": False},
    # No default base_url: each brain supplies its own (OpenAI's for openai_compatible,
    # Anthropic's for anthropic). A shared default here leaked api.openai.com into the
    # Anthropic adapter whenever a site set `provider: anthropic` without a base_url.
    "llm": {"provider": "openai_compatible", "api_key_env": "LLM_API_KEY", "model": "gpt-4o-mini", "custom_module": None, "max_input_tokens": 60000},
    "consumer": {"base_url": "", "routes": {"write_story": "/internal/storyteller/stories", "read_visitor": "/internal/storyteller/visitors/{id}"}, "secret_env": "STORYTELLER_SECRET", "timeout_seconds": 5},
    "service": {"prefix": "/storyteller", "admin_token_env": "STORYTELLER_ADMIN_TOKEN", "buffer_dir": "./data", "finalize_every_seconds": 30},
    "timeline": {"signals": {}},
}


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _apply_env(cfg: dict) -> dict:
    """ST_SECTION__KEY=value overrides (e.g. ST_LLM__MODEL=gpt-4o). Nested with double underscores."""
    for name, val in os.environ.items():
        if not name.startswith("ST_") or "__" not in name:
            continue
        parts = [p.lower() for p in name[3:].split("__")]
        d = cfg
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        v: Any = val
        if val.lower() in ("true", "false"):
            v = val.lower() == "true"
        elif val.isdigit():
            v = int(val)
        d[parts[-1]] = v
    return cfg


class Config:
    def __init__(self, data: dict[str, Any], base_dir: Path) -> None:
        self.data = data
        self.base_dir = base_dir

    def __getattr__(self, k: str) -> Any:
        try:
            return self.data[k]
        except KeyError:
            raise AttributeError(k)

    def brief_text(self) -> str:
        p = Path(self.site.get("brief_file") or "brief.md")
        if not p.is_absolute():
            p = self.base_dir / p
        return p.read_text() if p.exists() else ""

    def secret(self) -> str:
        return os.environ.get(self.consumer.get("secret_env") or "STORYTELLER_SECRET", "")

    def admin_token(self) -> str:
        return os.environ.get(self.service.get("admin_token_env") or "STORYTELLER_ADMIN_TOKEN", "")


def load_config(path: str | None = None) -> Config:
    p = Path(path or os.environ.get("STORYTELLER_CONFIG") or "storyteller.yaml")
    data: dict[str, Any] = {}
    if p.exists():
        data = yaml.safe_load(p.read_text()) or {}
    cfg = _apply_env(_merge(DEFAULTS, data))
    return Config(cfg, p.parent.resolve() if p.exists() else Path.cwd())
