# Brains (LLM adapters)

The storyteller calls one method:

```python
class Brain(Protocol):
    name: str
    supports_images: bool
    def complete(self, system: str, messages: list[Message], images: list[Image] | None = None, *, json: bool = True) -> Completion: ...
```
`Message(role, content)`, `Image(mime, base64, caption)`, `Completion(text, model, input_tokens, output_tokens)` live in `storyteller.llm.base`.

Built in:
- `openai_compatible` — `/chat/completions`. Covers OpenAI, Ollama, vLLM, LM Studio and most internal gateways. Config: `base_url`, `model`, `api_key_env`, optional `headers`, `supports_images`.
- `anthropic` — Messages API. Config: `model`, `api_key_env`.

Your own: put a class with that method anywhere importable, then
```yaml
llm:
  provider: custom
  custom_module: "mycompany.brains:JevBrain"   # class or factory; receives the llm config dict
```
Keep `json=True` meaning "return a single JSON object"; the prompt already asks for it, so the flag is only a hint for servers with a JSON mode. The storyteller validates the reply and retries once with the validation errors.

Tested models: fill in as you go.

| model | provider | stories OK | structured output OK | notes |
|---|---|---|---|---|
| fake-llm (examples/fake_llm.py) | openai_compatible | n/a | yes | for wiring tests only |
