"""Config defaults must not leak one provider's base_url into another's."""
from pathlib import Path

from storyteller.config import load_config
from storyteller.llm import load_brain


def _cfg(tmp_path: Path, body: str):
    p = tmp_path / "storyteller.yaml"
    p.write_text(body)
    return load_config(str(p))


def test_anthropic_without_base_url_talks_to_anthropic(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    cfg = _cfg(tmp_path, "llm:\n  provider: anthropic\n  model: claude-sonnet-4-5\n")
    brain = load_brain(cfg.llm)
    assert brain.name == "anthropic"
    assert brain.base_url == "https://api.anthropic.com"


def test_openai_compatible_still_defaults_to_openai(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    cfg = _cfg(tmp_path, "llm:\n  provider: openai_compatible\n")
    brain = load_brain(cfg.llm)
    assert brain.base_url == "https://api.openai.com/v1"


def test_explicit_base_url_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    cfg = _cfg(tmp_path, "llm:\n  provider: openai_compatible\n  base_url: http://ollama:11434/v1/\n")
    assert load_brain(cfg.llm).base_url == "http://ollama:11434/v1"
